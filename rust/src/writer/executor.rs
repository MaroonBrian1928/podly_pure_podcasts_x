use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

use serde_json::Value;
use tokio::sync::oneshot;

use super::actions::{error, ActionRegistry};
use super::database;
use super::protocol::{Command, RpcError};

#[derive(Debug)]
pub enum AdmissionError {
    NotReady,
    CapacityExhausted,
    PayloadTooLarge,
}

#[derive(Debug)]
pub struct ExecutionResult {
    pub command_id: String,
    pub result: Result<Value, RpcError>,
}

struct ByteBudget {
    used: Mutex<usize>,
    maximum: usize,
}

struct CapacityReservation {
    budget: Arc<ByteBudget>,
    bytes: usize,
    entries_used: Arc<AtomicUsize>,
}

impl Drop for CapacityReservation {
    fn drop(&mut self) {
        let mut used = self.budget.used.lock().expect("byte budget poisoned");
        *used = used.saturating_sub(self.bytes);
        self.entries_used.fetch_sub(1, Ordering::AcqRel);
    }
}

struct WorkItem {
    command: Command,
    _reservation: CapacityReservation,
    response: Option<oneshot::Sender<ExecutionResult>>,
}

pub struct Admission {
    pub response: Option<oneshot::Receiver<ExecutionResult>>,
}

pub struct WriterExecutor {
    sender: Mutex<Option<SyncSender<WorkItem>>>,
    accepting: Arc<AtomicBool>,
    byte_budget: Arc<ByteBudget>,
    entries_used: Arc<AtomicUsize>,
    maximum_entries: usize,
    thread: Mutex<Option<JoinHandle<()>>>,
}

impl WriterExecutor {
    pub fn start(
        db_path: &Path,
        queue_entries: usize,
        queue_bytes: usize,
        registry: ActionRegistry,
    ) -> anyhow::Result<Self> {
        let (sender, receiver) = mpsc::sync_channel::<WorkItem>(queue_entries);
        let (started_tx, started_rx) = mpsc::sync_channel(1);
        let path = db_path.to_owned();
        let accepting = Arc::new(AtomicBool::new(false));
        let thread_accepting = Arc::clone(&accepting);
        let worker = thread::Builder::new()
            .name("podly-sqlite-writer".to_owned())
            .spawn(move || {
                let connection = match database::open_ready(&path) {
                    Ok(connection) => connection,
                    Err(error) => {
                        let _ = started_tx.send(Err(error.to_string()));
                        return;
                    }
                };
                thread_accepting.store(true, Ordering::Release);
                let _ = started_tx.send(Ok(()));

                while let Ok(work) = receiver.recv() {
                    let result = execute_one(&connection, &registry, &work.command);
                    if let Some(response) = work.response {
                        let _ = response.send(ExecutionResult {
                            command_id: work.command.command_id,
                            result,
                        });
                    }
                }
                thread_accepting.store(false, Ordering::Release);
            })?;

        match started_rx.recv()? {
            Ok(()) => Ok(Self {
                sender: Mutex::new(Some(sender)),
                accepting,
                byte_budget: Arc::new(ByteBudget {
                    used: Mutex::new(0),
                    maximum: queue_bytes,
                }),
                entries_used: Arc::new(AtomicUsize::new(0)),
                maximum_entries: queue_entries,
                thread: Mutex::new(Some(worker)),
            }),
            Err(message) => {
                let _ = worker.join();
                anyhow::bail!(message)
            }
        }
    }

    pub fn submit(
        &self,
        command: Command,
        serialized_bytes: usize,
    ) -> Result<Admission, AdmissionError> {
        if !self.accepting.load(Ordering::Acquire) {
            return Err(AdmissionError::NotReady);
        }
        let reservation = self.reserve(serialized_bytes)?;
        let (response_tx, response_rx) = command.wait.then(oneshot::channel).unzip();
        let work = WorkItem {
            command,
            _reservation: reservation,
            response: response_tx,
        };
        let sender = self.sender.lock().expect("writer sender poisoned");
        let Some(sender) = sender.as_ref() else {
            return Err(AdmissionError::NotReady);
        };
        match sender.try_send(work) {
            Ok(()) => Ok(Admission {
                response: response_rx,
            }),
            Err(TrySendError::Full(_)) => Err(AdmissionError::CapacityExhausted),
            Err(TrySendError::Disconnected(_)) => Err(AdmissionError::NotReady),
        }
    }

    pub fn stop_admission(&self) {
        self.accepting.store(false, Ordering::Release);
    }

    pub fn is_accepting(&self) -> bool {
        self.accepting.load(Ordering::Acquire)
    }

    pub fn available_entries(&self) -> usize {
        self.maximum_entries
            .saturating_sub(self.entries_used.load(Ordering::Acquire))
    }

    pub fn available_bytes(&self) -> usize {
        let used = self.byte_budget.used.lock().expect("byte budget poisoned");
        self.byte_budget.maximum.saturating_sub(*used)
    }

    pub fn shutdown(&self) -> thread::Result<()> {
        self.stop_admission();
        self.sender.lock().expect("writer sender poisoned").take();
        if let Some(worker) = self.thread.lock().expect("writer thread poisoned").take() {
            worker.join()
        } else {
            Ok(())
        }
    }

    fn reserve(&self, bytes: usize) -> Result<CapacityReservation, AdmissionError> {
        self.entries_used
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |used| {
                (used < self.maximum_entries).then_some(used + 1)
            })
            .map_err(|_| AdmissionError::CapacityExhausted)?;
        if bytes > self.byte_budget.maximum {
            self.entries_used.fetch_sub(1, Ordering::AcqRel);
            return Err(AdmissionError::PayloadTooLarge);
        }
        let mut used = self.byte_budget.used.lock().expect("byte budget poisoned");
        let Some(next) = used.checked_add(bytes) else {
            self.entries_used.fetch_sub(1, Ordering::AcqRel);
            return Err(AdmissionError::CapacityExhausted);
        };
        if next > self.byte_budget.maximum {
            self.entries_used.fetch_sub(1, Ordering::AcqRel);
            return Err(AdmissionError::CapacityExhausted);
        }
        *used = next;
        Ok(CapacityReservation {
            budget: Arc::clone(&self.byte_budget),
            bytes,
            entries_used: Arc::clone(&self.entries_used),
        })
    }
}

impl Drop for WriterExecutor {
    fn drop(&mut self) {
        self.stop_admission();
        self.sender.lock().expect("writer sender poisoned").take();
        if let Some(worker) = self.thread.lock().expect("writer thread poisoned").take() {
            let _ = worker.join();
        }
    }
}

fn execute_one(
    connection: &rusqlite::Connection,
    registry: &ActionRegistry,
    command: &Command,
) -> Result<Value, RpcError> {
    if let Some(result) = registry.execute_non_atomic(connection, &command.operation) {
        return result;
    }
    let transaction = connection
        .unchecked_transaction()
        .map_err(|_| error("database_error", "could not begin transaction"))?;
    let result = registry.execute(&transaction, &command.operation);
    match result {
        Ok(value) => transaction
            .commit()
            .map(|()| value)
            .map_err(|_| error("commit_failed", "database commit failed")),
        Err(error) => {
            let _ = transaction.rollback();
            Err(error)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::sync::{Arc, Barrier};

    use serde_json::{Map, Value};
    use tempfile::NamedTempFile;

    use super::*;
    use crate::writer::protocol::Operation;

    fn seed_revision(connection: &rusqlite::Connection) {
        connection
            .execute(
                "CREATE TABLE alembic_version(version_num TEXT NOT NULL)",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO alembic_version(version_num) VALUES (?1)",
                [crate::writer::database::EXPECTED_SCHEMA_REVISION],
            )
            .unwrap();
    }

    fn command(action: &str, params: BTreeMap<&str, Value>, wait: bool) -> Command {
        Command {
            version: 1,
            command_id: action.to_owned(),
            wait,
            operation: Operation::Action {
                action: action.to_owned(),
                params: params
                    .into_iter()
                    .map(|(key, value)| (key.to_owned(), value))
                    .collect::<Map<_, _>>(),
            },
        }
    }

    #[test]
    fn executor_commits_on_one_owner_thread() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        connection
            .execute("CREATE TABLE writer_test_events(value TEXT NOT NULL)", [])
            .unwrap();
        drop(connection);
        let executor =
            WriterExecutor::start(file.path(), 2, 1024, ActionRegistry::with_test_actions())
                .unwrap();

        let mut params = BTreeMap::new();
        params.insert("value", Value::String("committed".to_owned()));
        let reply = executor
            .submit(command("__test_insert", params, true), 100)
            .unwrap()
            .response
            .unwrap()
            .blocking_recv()
            .unwrap();
        assert!(reply.result.is_ok());
        executor.shutdown().unwrap();

        let connection = rusqlite::Connection::open(file.path()).unwrap();
        let count: i64 = connection
            .query_row("SELECT COUNT(*) FROM writer_test_events", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, 1);
    }

    #[test]
    fn aggregate_byte_budget_rejects_without_admission() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        drop(connection);
        let executor =
            WriterExecutor::start(file.path(), 1, 5, ActionRegistry::with_test_actions()).unwrap();
        let result = executor.submit(command("__test_noop", BTreeMap::new(), false), 6);
        assert!(matches!(result, Err(AdmissionError::PayloadTooLarge)));
        executor.shutdown().unwrap();
    }

    #[test]
    fn transaction_failure_rolls_back_prior_subcommands() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        connection
            .execute("CREATE TABLE writer_test_events(value TEXT NOT NULL)", [])
            .unwrap();
        drop(connection);
        let registry = ActionRegistry::with_test_actions();
        let executor = WriterExecutor::start(file.path(), 2, 1024, registry).unwrap();
        let insert = Operation::Action {
            action: "__test_insert".to_owned(),
            params: Map::from_iter([("value".to_owned(), Value::String("rolled-back".to_owned()))]),
        };
        let unsupported = Operation::Action {
            action: "not_registered".to_owned(),
            params: Map::new(),
        };
        let command = Command {
            version: 1,
            command_id: "transaction".to_owned(),
            wait: true,
            operation: Operation::Transaction {
                commands: vec![
                    crate::writer::protocol::TransactionCommand {
                        command_id: "first".to_owned(),
                        operation: insert,
                    },
                    crate::writer::protocol::TransactionCommand {
                        command_id: "second".to_owned(),
                        operation: unsupported,
                    },
                ],
            },
        };
        let reply = executor
            .submit(command, 100)
            .unwrap()
            .response
            .unwrap()
            .blocking_recv()
            .unwrap();
        assert!(reply.result.is_err());
        executor.shutdown().unwrap();

        let connection = rusqlite::Connection::open(file.path()).unwrap();
        let count: i64 = connection
            .query_row("SELECT COUNT(*) FROM writer_test_events", [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, 0);
    }

    #[test]
    fn reachable_generic_update_preserves_numeric_shape_and_ignores_unknown_fields() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        connection
            .execute(
                "CREATE TABLE post(
                    id INTEGER PRIMARY KEY,
                    duration INTEGER,
                    whitelisted BOOLEAN NOT NULL,
                    transcript_word_timestamps JSON,
                    processed_audio_path TEXT
                )",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO post(id, duration, whitelisted) VALUES (1, 90, 0)",
                [],
            )
            .unwrap();
        drop(connection);
        let executor =
            WriterExecutor::start(file.path(), 4, 4096, ActionRegistry::default()).unwrap();
        let command = Command {
            version: 1,
            command_id: "generic-update".to_owned(),
            wait: true,
            operation: Operation::Update {
                model: "Post".to_owned(),
                id: Value::from(1),
                data: Map::from_iter([
                    ("duration".to_owned(), Value::from(90.5)),
                    ("whitelisted".to_owned(), Value::Bool(true)),
                    (
                        "transcript_word_timestamps".to_owned(),
                        serde_json::json!([{"word": "hello", "start": 0.0}]),
                    ),
                    ("unknown_legacy_field".to_owned(), Value::from("ignored")),
                ]),
            },
        };
        let result = executor
            .submit(command, 512)
            .unwrap()
            .response
            .unwrap()
            .blocking_recv()
            .unwrap();
        assert!(result.result.is_ok());
        let missing = Command {
            version: 1,
            command_id: "missing-update".to_owned(),
            wait: true,
            operation: Operation::Update {
                model: "Post".to_owned(),
                id: Value::from(999),
                data: Map::from_iter([("processed_audio_path".to_owned(), Value::Null)]),
            },
        };
        let missing = executor
            .submit(missing, 128)
            .unwrap()
            .response
            .unwrap()
            .blocking_recv()
            .unwrap();
        assert_eq!(missing.result.unwrap_err().code, "not_found");
        executor.shutdown().unwrap();

        let connection = rusqlite::Connection::open(file.path()).unwrap();
        let row = connection
            .query_row(
                "SELECT duration, typeof(duration), whitelisted, transcript_word_timestamps FROM post WHERE id=1",
                [],
                |row| {
                    Ok((
                        row.get::<_, f64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, i64>(2)?,
                        row.get::<_, String>(3)?,
                    ))
                },
            )
            .unwrap();
        assert_eq!(row.0, 90.5);
        assert_eq!(row.1, "real");
        assert_eq!(row.2, 1);
        assert_eq!(
            serde_json::from_str::<Value>(&row.3).unwrap(),
            serde_json::json!([{"word": "hello", "start": 0.0}])
        );
    }

    #[test]
    fn concurrent_dequeue_requests_claim_exactly_one_job() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        connection
            .execute(
                "CREATE TABLE processing_job(
                    id TEXT PRIMARY KEY,jobs_manager_run_id TEXT,post_guid TEXT NOT NULL,
                    status TEXT NOT NULL,started_at DATETIME,created_at DATETIME
                 )",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO processing_job VALUES
                    ('job',NULL,'guid','pending',NULL,'2026-01-01')",
                [],
            )
            .unwrap();
        drop(connection);

        let executor = Arc::new(
            WriterExecutor::start(file.path(), 16, 16 * 1024, ActionRegistry::default()).unwrap(),
        );
        let barrier = Arc::new(Barrier::new(9));
        let workers = (0..8)
            .map(|index| {
                let executor = Arc::clone(&executor);
                let barrier = Arc::clone(&barrier);
                thread::spawn(move || {
                    barrier.wait();
                    let mut command = command("dequeue_job", BTreeMap::new(), true);
                    command.command_id = format!("dequeue-{index}");
                    executor
                        .submit(command, 128)
                        .unwrap()
                        .response
                        .unwrap()
                        .blocking_recv()
                        .unwrap()
                        .result
                        .unwrap()
                })
            })
            .collect::<Vec<_>>();
        barrier.wait();
        let results = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| !result.is_null()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_null()).count(), 7);
        executor.shutdown().unwrap();

        let connection = rusqlite::Connection::open(file.path()).unwrap();
        let running: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM processing_job WHERE status='running'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(running, 1);
    }

    #[test]
    fn concurrent_cancel_and_completion_always_finish_cancelled() {
        let file = NamedTempFile::new().unwrap();
        let connection = rusqlite::Connection::open(file.path()).unwrap();
        seed_revision(&connection);
        connection
            .execute(
                "CREATE TABLE processing_job(
                    id TEXT PRIMARY KEY,jobs_manager_run_id TEXT,post_guid TEXT NOT NULL,
                    status TEXT NOT NULL,current_step INTEGER,step_name TEXT,total_steps INTEGER,
                    progress_percentage REAL,started_at DATETIME,completed_at DATETIME,
                    error_message TEXT,scheduler_job_id TEXT,created_at DATETIME,
                    requested_by_user_id INTEGER,billing_user_id INTEGER,stage_history JSON,
                    ad_windows_count INTEGER,had_classification_parse_error BOOLEAN NOT NULL,
                    auto_retry_attempted BOOLEAN NOT NULL
                 )",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO processing_job VALUES (
                    'job',NULL,'guid','running',1,'Working',4,25.0,'2026-01-01',NULL,
                    NULL,NULL,'2026-01-01',NULL,NULL,'[]',NULL,0,0)",
                [],
            )
            .unwrap();
        drop(connection);

        let executor = Arc::new(
            WriterExecutor::start(file.path(), 4, 4096, ActionRegistry::default()).unwrap(),
        );
        let barrier = Arc::new(Barrier::new(3));
        let cancel = {
            let executor = Arc::clone(&executor);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                executor
                    .submit(
                        command(
                            "mark_cancelled",
                            BTreeMap::from([
                                ("job_id", Value::String("job".to_owned())),
                                ("reason", Value::String("Stopped".to_owned())),
                            ]),
                            true,
                        ),
                        256,
                    )
                    .unwrap()
                    .response
                    .unwrap()
                    .blocking_recv()
                    .unwrap()
            })
        };
        let complete = {
            let executor = Arc::clone(&executor);
            let barrier = Arc::clone(&barrier);
            thread::spawn(move || {
                barrier.wait();
                executor
                    .submit(
                        command(
                            "update_job_status",
                            BTreeMap::from([
                                ("job_id", Value::String("job".to_owned())),
                                ("status", Value::String("completed".to_owned())),
                                ("step", Value::from(4)),
                                ("step_name", Value::String("Completed".to_owned())),
                            ]),
                            true,
                        ),
                        256,
                    )
                    .unwrap()
                    .response
                    .unwrap()
                    .blocking_recv()
                    .unwrap()
            })
        };
        barrier.wait();
        assert!(cancel.join().unwrap().result.is_ok());
        assert!(complete.join().unwrap().result.is_ok());
        executor.shutdown().unwrap();

        let connection = rusqlite::Connection::open(file.path()).unwrap();
        let row: (String, String, String) = connection
            .query_row(
                "SELECT status,step_name,error_message FROM processing_job WHERE id='job'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(
            row,
            ("cancelled".into(), "Stopped".into(), "Stopped".into())
        );
    }
}
