use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, NaiveDateTime, Utc};
use clap::{Args, Parser, Subcommand, ValueEnum};
use id3::frame::{Chapter as Id3Chapter, Content, Frame, TableOfContents};
use id3::{Tag, TagLike, Version};
use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Parser)]
#[command(name = "podly_tools")]
#[command(about = "Short-lived Podly helper process for file-heavy work")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Audio(AudioCommand),
    Feed(FeedCommand),
    Transcript(TranscriptCommand),
    Chapters(ChaptersCommand),
}

#[derive(Args)]
struct AudioCommand {
    #[command(subcommand)]
    command: AudioSubcommand,
}

#[derive(Subcommand)]
enum AudioSubcommand {
    Probe(AudioProbeArgs),
    Cut(AudioCutArgs),
    Bleep(AudioBleepArgs),
    Split(AudioSplitArgs),
}

#[derive(Args)]
struct AudioProbeArgs {
    #[arg(long)]
    input: PathBuf,
}

#[derive(Args)]
struct AudioCutArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long = "windows-json")]
    windows_json: PathBuf,
    #[arg(long)]
    mode: CutMode,
    #[arg(long = "fade-ms")]
    fade_ms: u32,
    #[arg(long)]
    encoding: Encoding,
}

#[derive(Args)]
struct AudioBleepArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long = "windows-json")]
    windows_json: PathBuf,
    #[arg(long = "beep-frequency-hz")]
    beep_frequency_hz: u32,
    #[arg(long = "beep-volume")]
    beep_volume: f32,
    #[arg(long = "duck-volume")]
    duck_volume: f32,
    #[arg(long)]
    encoding: Encoding,
}

#[derive(Args)]
struct AudioSplitArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long = "out-dir")]
    out_dir: PathBuf,
    #[arg(long = "chunk-size-bytes")]
    chunk_size_bytes: u64,
}

#[derive(Clone, ValueEnum)]
enum CutMode {
    Fade,
    Exact,
}

#[derive(Clone, ValueEnum)]
enum Encoding {
    Vbr,
    Cbr,
}

#[derive(Args)]
struct FeedCommand {
    #[command(subcommand)]
    command: FeedSubcommand,
}

#[derive(Subcommand)]
enum FeedSubcommand {
    Render(FeedRenderArgs),
    RenderAggregate(FeedRenderAggregateArgs),
}

#[derive(Args)]
struct FeedRenderArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "feed-id")]
    feed_id: i64,
    #[arg(long = "base-url")]
    base_url: String,
    #[arg(long = "include-unprocessed")]
    include_unprocessed: bool,
    #[arg(long = "feed-token")]
    feed_token: Option<String>,
    #[arg(long = "feed-secret")]
    feed_secret: Option<String>,
}

#[derive(Args)]
struct FeedRenderAggregateArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "user-id")]
    user_id: i64,
    #[arg(long = "base-url")]
    base_url: String,
    #[arg(long = "require-auth")]
    require_auth: bool,
    #[arg(long = "limit-per-feed")]
    limit_per_feed: usize,
    #[arg(long = "feed-token")]
    feed_token: Option<String>,
    #[arg(long = "feed-secret")]
    feed_secret: Option<String>,
}

#[derive(Args)]
struct TranscriptCommand {
    #[command(subcommand)]
    command: TranscriptSubcommand,
}

#[derive(Subcommand)]
enum TranscriptSubcommand {
    NormalizeWordTimestamps(TranscriptNormalizeArgs),
    ExportWordTimestamps(TranscriptExportArgs),
}

#[derive(Args)]
struct TranscriptNormalizeArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Args)]
struct TranscriptExportArgs {
    #[arg(long)]
    db: PathBuf,
    #[arg(long = "post-id")]
    post_id: i64,
}

#[derive(Args)]
struct ChaptersCommand {
    #[command(subcommand)]
    command: ChaptersSubcommand,
}

#[derive(Subcommand)]
enum ChaptersSubcommand {
    Write(ChaptersWriteArgs),
}

#[derive(Args)]
struct ChaptersWriteArgs {
    #[arg(long)]
    audio: PathBuf,
    #[arg(long = "chapters-json")]
    chapters_json: PathBuf,
    #[arg(long = "removed-windows-json")]
    removed_windows_json: PathBuf,
}

#[derive(Serialize)]
struct ProbeResponse {
    duration_ms: u64,
}

#[derive(Serialize)]
struct OkResponse {
    ok: bool,
}

#[derive(Serialize)]
struct SplitResponse {
    chunks: Vec<SplitChunk>,
}

#[derive(Serialize)]
struct SplitChunk {
    path: String,
    offset_ms: u64,
}

#[derive(Deserialize)]
struct WindowMs(u64, u64);

#[derive(Serialize)]
struct NormalizedWordSegment {
    sequence_num: i64,
    words: Vec<NormalizedWord>,
}

#[derive(Serialize)]
struct NormalizedWord {
    word: String,
    start: f64,
    end: f64,
    score: Option<f64>,
}

#[derive(Serialize)]
struct TranscriptExportResponse {
    transcript_word_timestamps: Value,
}

#[derive(Serialize)]
struct XmlResponse {
    xml: String,
}

struct FeedRow {
    id: i64,
    title: String,
    description: Option<String>,
    image_url: Option<String>,
    last_changed_at: Option<String>,
}

struct PostRow {
    feed_title: Option<String>,
    title: String,
    guid: String,
    processed_audio_path: Option<String>,
    description: Option<String>,
    release_date: Option<String>,
    duration: Option<i64>,
    image_url: Option<String>,
    chapter_data: Option<String>,
}

struct RssBuildArgs<'a> {
    title: &'a str,
    link: &'a str,
    description: &'a str,
    image_url: Option<&'a str>,
    image_title: &'a str,
    last_build_date: &'a str,
    base_url: &'a str,
    feed_token: Option<&'a str>,
    feed_secret: Option<&'a str>,
    posts: &'a [PostRow],
    prepend_feed_title: bool,
}

#[derive(Deserialize)]
struct ChapterPayload {
    title: String,
    start_time_ms: u32,
    end_time_ms: u32,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Audio(audio) => match audio.command {
            AudioSubcommand::Probe(args) => print_json(&probe_audio_path(&args.input)?),
            AudioSubcommand::Cut(args) => print_json(&cut_audio(args)?),
            AudioSubcommand::Bleep(args) => print_json(&bleep_audio(args)?),
            AudioSubcommand::Split(args) => print_json(&split_audio(args)?),
        },
        Commands::Feed(feed) => match feed.command {
            FeedSubcommand::Render(args) => print_json(&render_feed(args)?),
            FeedSubcommand::RenderAggregate(args) => print_json(&render_aggregate_feed(args)?),
        },
        Commands::Transcript(transcript) => match transcript.command {
            TranscriptSubcommand::NormalizeWordTimestamps(args) => {
                print_json(&normalize_word_timestamps(args)?)
            }
            TranscriptSubcommand::ExportWordTimestamps(args) => {
                print_json(&export_word_timestamps(args)?)
            }
        },
        Commands::Chapters(chapters) => match chapters.command {
            ChaptersSubcommand::Write(args) => print_json(&write_chapters(args)?),
        },
    }
}

fn probe_audio_path(input: &Path) -> Result<ProbeResponse> {
    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("error")
        .arg("-show_entries")
        .arg("format=duration")
        .arg("-of")
        .arg("json")
        .arg(input)
        .output()
        .with_context(|| "failed to run ffprobe")?;

    if !output.status.success() {
        return Err(anyhow!(
            "ffprobe failed with status {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }

    let payload: Value =
        serde_json::from_slice(&output.stdout).context("failed to parse ffprobe JSON")?;
    let duration_seconds = payload
        .get("format")
        .and_then(|format| format.get("duration"))
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("ffprobe response did not include format.duration"))?
        .parse::<f64>()
        .context("ffprobe duration was not a number")?;

    if !duration_seconds.is_finite() || duration_seconds < 0.0 {
        return Err(anyhow!("ffprobe duration was invalid"));
    }

    Ok(ProbeResponse {
        duration_ms: (duration_seconds * 1000.0).round() as u64,
    })
}

fn cut_audio(args: AudioCutArgs) -> Result<OkResponse> {
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let windows = read_windows_ms(&args.windows_json)?;

    match args.mode {
        CutMode::Exact => cut_audio_simple(
            &args.input,
            &args.output,
            &windows,
            duration_ms,
            &args.encoding,
        )?,
        CutMode::Fade => cut_audio_with_fade(
            &args.input,
            &args.output,
            &windows,
            duration_ms,
            args.fade_ms,
            &args.encoding,
        )?,
    }

    Ok(OkResponse { ok: true })
}

fn bleep_audio(args: AudioBleepArgs) -> Result<OkResponse> {
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let windows = read_windows_ms(&args.windows_json)?;
    if windows.is_empty() {
        fs::copy(&args.input, &args.output).with_context(|| "failed to copy input audio")?;
        return Ok(OkResponse { ok: true });
    }

    let condition = build_window_condition(&windows);
    let filter = format!(
        "[0:a]volume='if(gt({condition},0),{duck},1)':eval=frame[ducked];\
         sine=frequency={freq}:duration={duration:.3}:sample_rate=44100,\
         volume='if(gt({condition},0),{beep},0)':eval=frame[beep];\
         [ducked][beep]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]",
        condition = condition,
        duck = args.duck_volume,
        freq = args.beep_frequency_hz,
        duration = duration_ms as f64 / 1000.0,
        beep = args.beep_volume,
    );

    run_filtered_output(&args.input, &args.output, &filter, &args.encoding)?;
    Ok(OkResponse { ok: true })
}

fn split_audio(args: AudioSplitArgs) -> Result<SplitResponse> {
    if args.chunk_size_bytes == 0 {
        return Err(anyhow!("chunk_size_bytes must be a positive integer"));
    }

    fs::create_dir_all(&args.out_dir).with_context(|| "failed to create output directory")?;
    let duration_ms = probe_audio_path(&args.input)?.duration_ms;
    let file_size_bytes = fs::metadata(&args.input)
        .with_context(|| "failed to read input metadata")?
        .len();
    if file_size_bytes == 0 {
        return Err(anyhow!("cannot split zero-byte audio file"));
    }

    let chunk_ratio = args.chunk_size_bytes as f64 / file_size_bytes as f64;
    let chunk_duration_ms = ((duration_ms as f64 * chunk_ratio).ceil() as u64).max(1);
    let num_chunks = ((duration_ms as f64 / chunk_duration_ms as f64).ceil() as u64).max(1);

    let mut chunks = Vec::new();
    for index in 0..num_chunks {
        let start_offset_ms = index * chunk_duration_ms;
        if start_offset_ms >= duration_ms {
            break;
        }
        let end_offset_ms = duration_ms.min((index + 1) * chunk_duration_ms);
        let output_path = args.out_dir.join(format!("{index}.mp3"));
        trim_file(&args.input, &output_path, start_offset_ms, end_offset_ms)?;
        chunks.push(SplitChunk {
            path: output_path.to_string_lossy().into_owned(),
            offset_ms: start_offset_ms,
        });
    }

    Ok(SplitResponse { chunks })
}

fn cut_audio_with_fade(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    fade_ms: u32,
    encoding: &Encoding,
) -> Result<()> {
    let fade_ms = fade_ms as u64;
    let mut streams = Vec::new();
    let mut last_end = 0;
    for (start_ms, end_ms) in windows {
        if *start_ms > last_end {
            streams.push((last_end, *start_ms, None));
        }
        streams.push((*start_ms, (*start_ms + fade_ms).min(*end_ms), Some("out")));
        streams.push((end_ms.saturating_sub(fade_ms), *end_ms, Some("in")));
        last_end = *end_ms;
    }
    if last_end < duration_ms {
        streams.push((last_end, duration_ms, None));
    }

    let mut filter_parts = Vec::new();
    let mut labels = Vec::new();
    for (index, (start_ms, end_ms, fade)) in streams.iter().enumerate() {
        if end_ms <= start_ms {
            continue;
        }
        let label = format!("a{index}");
        let mut part = format!(
            "[0:a]atrim=start={:.3}:end={:.3},asetpts=PTS-STARTPTS",
            *start_ms as f64 / 1000.0,
            *end_ms as f64 / 1000.0
        );
        if let Some(direction) = fade {
            part.push_str(&format!(
                ",afade=t={direction}:ss=0:d={:.3}",
                fade_ms as f64 / 1000.0
            ));
        }
        part.push_str(&format!("[{label}]"));
        filter_parts.push(part);
        labels.push(format!("[{label}]"));
    }

    if labels.is_empty() {
        return Err(anyhow!("no audio segments to keep after removal"));
    }

    filter_parts.push(format!(
        "{}concat=n={}:v=0:a=1[out]",
        labels.join(""),
        labels.len()
    ));
    run_filtered_output(input, output, &filter_parts.join(";"), encoding)
}

fn cut_audio_simple(
    input: &Path,
    output: &Path,
    windows: &[(u64, u64)],
    duration_ms: u64,
    encoding: &Encoding,
) -> Result<()> {
    let keep_segments = keep_segments(windows, duration_ms);
    if keep_segments.is_empty() {
        return Err(anyhow!("no audio segments to keep after removal"));
    }

    let temp_dir = tempfile::tempdir().with_context(|| "failed to create temp directory")?;
    let mut segment_files = Vec::new();
    for (index, (start_ms, end_ms)) in keep_segments.iter().enumerate() {
        let segment_path = temp_dir.path().join(format!("segment_{index}.mp3"));
        trim_file_reencoded(input, &segment_path, *start_ms, *end_ms, encoding)?;
        segment_files.push(segment_path);
    }

    let concat_list_path = temp_dir.path().join("concat_list.txt");
    let mut concat_list =
        fs::File::create(&concat_list_path).with_context(|| "failed to create concat list")?;
    for segment_file in segment_files {
        writeln!(concat_list, "file '{}'", segment_file.display())
            .with_context(|| "failed to write concat list")?;
    }

    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-f")
        .arg("concat")
        .arg("-safe")
        .arg("0")
        .arg("-i")
        .arg(concat_list_path)
        .arg("-codec:a")
        .arg("libmp3lame");
    add_encoding_args(&mut command, encoding);
    command.arg(output);
    run_command(command, "ffmpeg concat")
}

fn trim_file(input: &Path, output: &Path, start_ms: u64, end_ms: u64) -> Result<()> {
    let duration_ms = end_ms.saturating_sub(start_ms);
    if duration_ms == 0 {
        return Ok(());
    }

    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-ss")
        .arg(format!("{:.3}", start_ms as f64 / 1000.0))
        .arg("-t")
        .arg(format!("{:.3}", duration_ms as f64 / 1000.0))
        .arg("-i")
        .arg(input)
        .arg("-codec:a")
        .arg("copy")
        .arg("-vn")
        .arg(output);
    run_command(command, "ffmpeg trim")
}

fn trim_file_reencoded(
    input: &Path,
    output: &Path,
    start_ms: u64,
    end_ms: u64,
    encoding: &Encoding,
) -> Result<()> {
    let duration_ms = end_ms.saturating_sub(start_ms);
    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-ss")
        .arg(format!("{:.3}", start_ms as f64 / 1000.0))
        .arg("-t")
        .arg(format!("{:.3}", duration_ms as f64 / 1000.0))
        .arg("-i")
        .arg(input)
        .arg("-codec:a")
        .arg("libmp3lame");
    add_encoding_args(&mut command, encoding);
    command.arg(output);
    run_command(command, "ffmpeg segment")
}

fn run_filtered_output(
    input: &Path,
    output: &Path,
    filter: &str,
    encoding: &Encoding,
) -> Result<()> {
    let mut command = Command::new("ffmpeg");
    command
        .arg("-y")
        .arg("-v")
        .arg("error")
        .arg("-i")
        .arg(input)
        .arg("-filter_complex")
        .arg(filter)
        .arg("-map")
        .arg("[out]")
        .arg("-codec:a")
        .arg("libmp3lame");
    add_encoding_args(&mut command, encoding);
    command.arg(output);
    run_command(command, "ffmpeg filter")
}

fn run_command(mut command: Command, label: &str) -> Result<()> {
    let output = command
        .output()
        .with_context(|| format!("failed to run {label}"))?;
    if !output.status.success() {
        return Err(anyhow!(
            "{label} failed with status {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

fn add_encoding_args(command: &mut Command, encoding: &Encoding) {
    match encoding {
        Encoding::Vbr => {
            command.arg("-q:a").arg("2");
        }
        Encoding::Cbr => {
            command.arg("-b:a").arg("192k");
        }
    }
}

fn read_windows_ms(path: &Path) -> Result<Vec<(u64, u64)>> {
    let data = fs::read_to_string(path).with_context(|| "failed to read windows JSON")?;
    let windows: Vec<WindowMs> =
        serde_json::from_str(&data).with_context(|| "failed to parse windows JSON")?;
    Ok(merge_windows(
        windows
            .into_iter()
            .filter_map(|WindowMs(start, end)| (end > start).then_some((start, end)))
            .collect(),
    ))
}

fn merge_windows(mut windows: Vec<(u64, u64)>) -> Vec<(u64, u64)> {
    windows.sort_by_key(|window| window.0);
    let mut merged: Vec<(u64, u64)> = Vec::new();
    for (start, end) in windows {
        match merged.last_mut() {
            Some((_, prev_end)) if start <= *prev_end => {
                *prev_end = (*prev_end).max(end);
            }
            _ => merged.push((start, end)),
        }
    }
    merged
}

fn keep_segments(windows: &[(u64, u64)], duration_ms: u64) -> Vec<(u64, u64)> {
    let mut keep = Vec::new();
    let mut last_end = 0;
    for (start, end) in windows {
        if *start > last_end {
            keep.push((last_end, *start));
        }
        last_end = *end;
    }
    if last_end < duration_ms {
        keep.push((last_end, duration_ms));
    }
    keep
}

fn build_window_condition(windows: &[(u64, u64)]) -> String {
    if windows.is_empty() {
        return "0".to_string();
    }
    windows
        .iter()
        .filter(|(start, end)| end > start)
        .map(|(start, end)| {
            format!(
                "between(t,{:.3},{:.3})",
                *start as f64 / 1000.0,
                *end as f64 / 1000.0
            )
        })
        .collect::<Vec<_>>()
        .join("+")
}

fn normalize_word_timestamps(args: TranscriptNormalizeArgs) -> Result<OkResponse> {
    let data = fs::read_to_string(&args.input)
        .with_context(|| "failed to read transcript word timestamp artifact")?;
    let payload: Value =
        serde_json::from_str(&data).with_context(|| "failed to parse transcript JSON")?;
    let Value::Array(raw_segments) = payload else {
        fs::write(&args.output, b"null")
            .with_context(|| "failed to write normalized transcript JSON")?;
        return Ok(OkResponse { ok: true });
    };

    let mut normalized_segments = Vec::new();
    for raw_segment in raw_segments {
        let Value::Object(segment_map) = raw_segment else {
            continue;
        };
        let Some(sequence_num) = segment_map.get("sequence_num").and_then(value_to_i64) else {
            continue;
        };
        let Some(Value::Array(words)) = segment_map.get("words") else {
            continue;
        };

        let mut normalized_words = Vec::new();
        for word_payload in words {
            let Value::Object(word_map) = word_payload else {
                continue;
            };
            let Some(raw_word) = word_map.get("word") else {
                continue;
            };
            let Some(word) = value_to_string(raw_word) else {
                continue;
            };
            let Some(start) = word_map.get("start").and_then(value_to_f64) else {
                continue;
            };
            let Some(end) = word_map.get("end").and_then(value_to_f64) else {
                continue;
            };
            if end < start {
                continue;
            }
            let score = word_map.get("score").and_then(value_to_f64);
            normalized_words.push(NormalizedWord {
                word,
                start,
                end,
                score,
            });
        }

        if !normalized_words.is_empty() {
            normalized_segments.push(NormalizedWordSegment {
                sequence_num,
                words: normalized_words,
            });
        }
    }

    let normalized_payload = if normalized_segments.is_empty() {
        Value::Null
    } else {
        serde_json::to_value(normalized_segments)?
    };
    fs::write(&args.output, serde_json::to_vec(&normalized_payload)?)
        .with_context(|| "failed to write normalized transcript JSON")?;
    Ok(OkResponse { ok: true })
}

fn export_word_timestamps(args: TranscriptExportArgs) -> Result<TranscriptExportResponse> {
    let conn = Connection::open_with_flags(
        &args.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
    )
    .with_context(|| "failed to open sqlite database read-only")?;
    conn.busy_timeout(std::time::Duration::from_secs(30))
        .with_context(|| "failed to set sqlite busy timeout")?;
    conn.pragma_update(None, "query_only", true)
        .with_context(|| "failed to enable sqlite query_only mode")?;

    let raw_json: Option<String> = conn
        .query_row(
            "SELECT transcript_word_timestamps FROM post WHERE id = ?1",
            [args.post_id],
            |row| row.get(0),
        )
        .with_context(|| "failed to query transcript_word_timestamps")?;

    let transcript_word_timestamps = match raw_json {
        Some(raw_json) => serde_json::from_str(&raw_json)
            .with_context(|| "stored transcript_word_timestamps was not valid JSON")?,
        None => Value::Null,
    };

    Ok(TranscriptExportResponse {
        transcript_word_timestamps,
    })
}

fn render_feed(args: FeedRenderArgs) -> Result<XmlResponse> {
    let conn = open_readonly_sqlite(&args.db)?;
    let feed = conn
        .query_row(
            "SELECT id, title, description, image_url, last_changed_at FROM feed WHERE id = ?1",
            [args.feed_id],
            |row| {
                Ok(FeedRow {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    description: row.get(2)?,
                    image_url: row.get(3)?,
                    last_changed_at: row.get(4)?,
                })
            },
        )
        .with_context(|| "failed to query feed")?;

    let posts = if args.include_unprocessed {
        query_posts(
            &conn,
            "SELECT NULL, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data \
             FROM post WHERE feed_id = ?1 ORDER BY release_date DESC, id DESC",
            [feed.id],
        )?
    } else {
        query_posts(
            &conn,
            "SELECT NULL, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data \
             FROM post WHERE feed_id = ?1 AND whitelisted = 1 AND processed_audio_path IS NOT NULL \
             ORDER BY release_date DESC, id DESC",
            [feed.id],
        )?
    };

    let link = append_feed_token(
        &format!("{}/feed/{}", args.base_url.trim_end_matches('/'), feed.id),
        args.feed_token.as_deref(),
        args.feed_secret.as_deref(),
    );
    let feed_title = format!("[podly] {}", feed.title);
    let last_build_date = format_rfc2822(feed.last_changed_at.as_deref());
    let xml = build_rss_xml(RssBuildArgs {
        title: &feed_title,
        link: &link,
        description: feed.description.as_deref().unwrap_or(""),
        image_url: feed.image_url.as_deref(),
        image_title: &feed.title,
        last_build_date: &last_build_date,
        base_url: &args.base_url,
        feed_token: args.feed_token.as_deref(),
        feed_secret: args.feed_secret.as_deref(),
        posts: &posts,
        prepend_feed_title: false,
    });
    Ok(XmlResponse { xml })
}

fn write_chapters(args: ChaptersWriteArgs) -> Result<OkResponse> {
    let data =
        fs::read_to_string(&args.chapters_json).with_context(|| "failed to read chapters JSON")?;
    let mut chapters: Vec<ChapterPayload> =
        serde_json::from_str(&data).with_context(|| "failed to parse chapters JSON")?;
    if chapters.is_empty() {
        return Ok(OkResponse { ok: true });
    }
    chapters.sort_by_key(|chapter| chapter.start_time_ms);

    let mut tag = Tag::read_from_path(&args.audio).unwrap_or_else(|_| Tag::new());
    tag.remove("CHAP");
    tag.remove("CTOC");

    let mut chapter_ids = Vec::new();
    for (index, chapter) in chapters.into_iter().enumerate() {
        let element_id = format!("chp{index}");
        chapter_ids.push(element_id.clone());
        tag.add_frame(Id3Chapter {
            element_id,
            start_time: chapter.start_time_ms,
            end_time: chapter.end_time_ms,
            start_offset: 0xFFFF_FFFF,
            end_offset: 0xFFFF_FFFF,
            frames: vec![Frame::with_content("TIT2", Content::Text(chapter.title))],
        });
    }

    tag.add_frame(TableOfContents {
        element_id: "toc".to_string(),
        top_level: true,
        ordered: true,
        elements: chapter_ids,
        frames: vec![],
    });
    tag.write_to_path(&args.audio, Version::Id3v24)
        .with_context(|| "failed to write chapter ID3 tags")?;

    Ok(OkResponse { ok: true })
}

fn render_aggregate_feed(args: FeedRenderAggregateArgs) -> Result<XmlResponse> {
    let conn = open_readonly_sqlite(&args.db)?;
    let feed_ids: Vec<i64> = if args.require_auth {
        let mut stmt = conn.prepare("SELECT feed_id FROM user_feed WHERE user_id = ?1")?;
        let rows = stmt.query_map([args.user_id], |row| row.get(0))?;
        rows.collect::<std::result::Result<Vec<i64>, _>>()?
    } else {
        let mut stmt = conn.prepare("SELECT id FROM feed")?;
        let rows = stmt.query_map([], |row| row.get(0))?;
        rows.collect::<std::result::Result<Vec<i64>, _>>()?
    };

    let mut posts = Vec::new();
    for feed_id in feed_ids {
        let mut feed_posts = query_posts_with_limit(
            &conn,
            "SELECT feed.title, post.title, post.guid, post.processed_audio_path, post.description, post.release_date, post.duration, post.image_url, post.chapter_data \
             FROM post JOIN feed ON feed.id = post.feed_id \
             WHERE post.feed_id = ?1 AND post.whitelisted = 1 AND post.processed_audio_path IS NOT NULL \
             ORDER BY post.release_date DESC, post.id DESC LIMIT ?2",
            feed_id,
            args.limit_per_feed as i64,
        )?;
        posts.append(&mut feed_posts);
    }
    posts.sort_by(|a, b| b.release_date.cmp(&a.release_date));

    let last_changed_at: Option<String> = if args.require_auth {
        conn.query_row(
            "SELECT max(feed.last_changed_at) FROM feed JOIN user_feed ON user_feed.feed_id = feed.id WHERE user_feed.user_id = ?1",
            [args.user_id],
            |row| row.get(0),
        )?
    } else {
        conn.query_row("SELECT max(last_changed_at) FROM feed", [], |row| {
            row.get(0)
        })?
    };

    let link = append_feed_token(
        &format!(
            "{}/feed/user/{}",
            args.base_url.trim_end_matches('/'),
            args.user_id
        ),
        args.feed_token.as_deref(),
        args.feed_secret.as_deref(),
    );
    let title = "Podly Podcasts";
    let image_url = format!(
        "{}/static/images/logos/manifest-icon-512.maskable.png",
        args.base_url.trim_end_matches('/')
    );
    let last_build_date = format_rfc2822(last_changed_at.as_deref());
    let xml = build_rss_xml(RssBuildArgs {
        title,
        link: &link,
        description: "Aggregate feed - Last 3 processed episodes from each subscribed feed.",
        image_url: Some(&image_url),
        image_title: title,
        last_build_date: &last_build_date,
        base_url: &args.base_url,
        feed_token: args.feed_token.as_deref(),
        feed_secret: args.feed_secret.as_deref(),
        posts: &posts,
        prepend_feed_title: true,
    });
    Ok(XmlResponse { xml })
}

fn open_readonly_sqlite(path: &Path) -> Result<Connection> {
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .with_context(|| "failed to open sqlite database read-only")?;
    conn.busy_timeout(std::time::Duration::from_secs(30))?;
    conn.pragma_update(None, "query_only", true)?;
    Ok(conn)
}

fn query_posts(conn: &Connection, sql: &str, feed_id: [i64; 1]) -> Result<Vec<PostRow>> {
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt.query_map(feed_id, post_from_row)?;
    Ok(rows.collect::<std::result::Result<Vec<PostRow>, _>>()?)
}

fn query_posts_with_limit(
    conn: &Connection,
    sql: &str,
    feed_id: i64,
    limit: i64,
) -> Result<Vec<PostRow>> {
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt.query_map((feed_id, limit), post_from_row)?;
    Ok(rows.collect::<std::result::Result<Vec<PostRow>, _>>()?)
}

fn post_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<PostRow> {
    Ok(PostRow {
        feed_title: row.get(0)?,
        title: row.get(1)?,
        guid: row.get(2)?,
        processed_audio_path: row.get(3)?,
        description: row.get(4)?,
        release_date: row.get(5)?,
        duration: row.get(6)?,
        image_url: row.get(7)?,
        chapter_data: row.get(8)?,
    })
}

fn build_rss_xml(args: RssBuildArgs<'_>) -> String {
    let mut xml = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n");
    xml.push_str("<rss version=\"2.0\" xmlns:itunes=\"http://www.itunes.com/dtds/podcast-1.0.dtd\" xmlns:content=\"http://purl.org/rss/1.0/modules/content/\">\n<channel>\n");
    push_text_element(&mut xml, "title", args.title);
    push_text_element(&mut xml, "link", args.link);
    push_text_element(
        &mut xml,
        "description",
        &normalize_feed_text(args.description),
    );
    push_text_element(&mut xml, "lastBuildDate", args.last_build_date);
    if let Some(image_url) = args.image_url {
        xml.push_str("<image>");
        push_text_element(&mut xml, "url", image_url);
        push_text_element(&mut xml, "title", args.image_title);
        push_text_element(&mut xml, "link", args.link);
        xml.push_str("</image>\n");
    }
    for post in args.posts {
        push_item(
            &mut xml,
            post,
            args.base_url,
            args.feed_token,
            args.feed_secret,
            args.prepend_feed_title,
        );
    }
    xml.push_str("</channel>\n</rss>\n");
    xml
}

fn push_item(
    xml: &mut String,
    post: &PostRow,
    base_url: &str,
    feed_token: Option<&str>,
    feed_secret: Option<&str>,
    prepend_feed_title: bool,
) {
    xml.push_str("<item>");
    let title = if prepend_feed_title {
        match &post.feed_title {
            Some(feed_title) => format!("[{feed_title}] {}", post.title),
            None => post.title.clone(),
        }
    } else {
        post.title.clone()
    };
    push_text_element(xml, "title", &title);
    let audio_url = append_feed_token(
        &format!("{}/post/{}.mp3", base_url.trim_end_matches('/'), post.guid),
        feed_token,
        feed_secret,
    );
    let description = build_description(post);
    push_cdata_element(xml, "content:encoded", &description);
    push_cdata_element(xml, "description", &description);
    xml.push_str(&format!(
        "<enclosure url=\"{}\" type=\"audio/mpeg\" length=\"{}\"></enclosure>",
        xml_escape(&audio_url),
        enclosure_len(post)
    ));
    push_text_element(xml, "guid", &post.guid);
    if let Some(release_date) = post.release_date.as_deref() {
        push_text_element(xml, "pubDate", &format_rfc2822(Some(release_date)));
    }
    if let Some(image_url) = post.image_url.as_deref() {
        xml.push_str(&format!(
            "<itunes:image href=\"{}\"></itunes:image>",
            xml_escape(image_url)
        ));
    }
    if let Some(duration) = post.duration {
        if duration >= 0 {
            push_text_element(xml, "itunes:duration", &format_duration(duration));
        }
    }
    xml.push_str("</item>\n");
}

fn enclosure_len(post: &PostRow) -> u64 {
    post.processed_audio_path
        .as_deref()
        .and_then(|path| fs::metadata(path).ok())
        .map(|metadata| metadata.len())
        .unwrap_or(0)
}

fn build_description(post: &PostRow) -> String {
    let mut parts = Vec::new();
    if let Some(description) = post.description.as_deref() {
        if !description.is_empty() {
            parts.push(normalize_feed_text(description));
        }
    }
    let chapters = render_chapters(post.chapter_data.as_deref());
    if !chapters.is_empty() {
        parts.push(chapters);
    }
    parts.join("\n")
}

fn render_chapters(raw: Option<&str>) -> String {
    let Some(raw) = raw else {
        return String::new();
    };
    let Ok(Value::Object(data)) = serde_json::from_str::<Value>(raw) else {
        return String::new();
    };
    let chapters = data
        .get("chapters_for_output")
        .or_else(|| data.get("chapters_kept"));
    let Some(Value::Array(chapters)) = chapters else {
        return String::new();
    };
    let mut parsed = Vec::new();
    for chapter in chapters {
        let Value::Object(chapter) = chapter else {
            continue;
        };
        let title = chapter
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if title.is_empty() {
            continue;
        }
        let start = chapter
            .get("start_time")
            .and_then(value_to_f64)
            .unwrap_or(0.0)
            .max(0.0);
        parsed.push((start, title.to_string()));
    }
    parsed.sort_by(|a, b| a.0.total_cmp(&b.0));
    if parsed.is_empty() {
        return String::new();
    }
    let items = parsed
        .into_iter()
        .map(|(start, title)| {
            format!(
                "<li>{} {}</li>",
                format_chapter_timestamp(start),
                html_escape(&title)
            )
        })
        .collect::<String>();
    format!("<p><strong>Podly Chapters</strong></p><ul>{items}</ul>")
}

fn append_feed_token(url: &str, token: Option<&str>, secret: Option<&str>) -> String {
    match (token, secret) {
        (Some(token), Some(secret)) if !token.is_empty() && !secret.is_empty() => {
            let separator = if url.contains('?') { '&' } else { '?' };
            format!(
                "{url}{separator}feed_token={}&feed_secret={}",
                urlencoding_simple(token),
                urlencoding_simple(secret)
            )
        }
        _ => url.to_string(),
    }
}

fn format_rfc2822(raw: Option<&str>) -> String {
    if let Some(raw) = raw {
        if let Ok(dt) = DateTime::parse_from_rfc3339(raw) {
            return dt.with_timezone(&Utc).to_rfc2822();
        }
        if let Ok(naive) = NaiveDateTime::parse_from_str(raw, "%Y-%m-%d %H:%M:%S%.f") {
            return DateTime::<Utc>::from_naive_utc_and_offset(naive, Utc).to_rfc2822();
        }
    }
    Utc::now().to_rfc2822()
}

fn format_duration(duration_seconds: i64) -> String {
    let total = duration_seconds.max(0);
    let hours = total / 3600;
    let minutes = (total % 3600) / 60;
    let seconds = total % 60;
    if hours > 0 {
        format!("{hours}:{minutes:02}:{seconds:02}")
    } else {
        format!("{minutes:02}:{seconds:02}")
    }
}

fn format_chapter_timestamp(seconds: f64) -> String {
    format_duration(seconds.max(0.0) as i64)
}

fn push_text_element(xml: &mut String, name: &str, value: &str) {
    xml.push_str(&format!("<{name}>{}</{name}>\n", xml_escape(value)));
}

fn push_cdata_element(xml: &mut String, name: &str, value: &str) {
    xml.push_str(&format!(
        "<{name}><![CDATA[{}]]></{name}>",
        value.replace("]]>", "]]]]><![CDATA[>")
    ));
}

fn normalize_feed_text(value: &str) -> String {
    value.replace('\u{00a0}', " ").replace(
        ['\u{200b}', '\u{200c}', '\u{200d}', '\u{2060}', '\u{feff}'],
        "",
    )
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn html_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn urlencoding_simple(value: &str) -> String {
    value
        .bytes()
        .flat_map(|byte| match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                vec![byte as char]
            }
            _ => format!("%{byte:02X}").chars().collect(),
        })
        .collect()
}

fn value_to_i64(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_u64().and_then(|value| i64::try_from(value).ok())),
        Value::String(text) => text.parse::<i64>().ok(),
        _ => None,
    }
}

fn value_to_f64(value: &Value) -> Option<f64> {
    match value {
        Value::Number(number) => number.as_f64(),
        Value::String(text) => text.parse::<f64>().ok(),
        _ => None,
    }
}

fn value_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(value) => Some(value.to_string()),
        _ => None,
    }
}

fn print_json<T: Serialize>(value: &T) -> Result<()> {
    println!("{}", serde_json::to_string(value)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::params;

    #[test]
    fn merge_windows_sorts_and_coalesces_overlaps() {
        assert_eq!(
            merge_windows(vec![(300, 400), (100, 200), (180, 250), (500, 550)]),
            vec![(100, 250), (300, 400), (500, 550)]
        );
    }

    #[test]
    fn keep_segments_inverts_removed_windows() {
        assert_eq!(
            keep_segments(&[(100, 200), (300, 350)], 500),
            vec![(0, 100), (200, 300), (350, 500)]
        );
    }

    #[test]
    fn duration_and_chapter_timestamp_format_match_python_shape() {
        assert_eq!(format_duration(65), "01:05");
        assert_eq!(format_duration(3_665), "1:01:05");
        assert_eq!(format_chapter_timestamp(125.9), "02:05");
    }

    #[test]
    fn feed_token_url_appending_encodes_values() {
        assert_eq!(
            append_feed_token("https://podly.test/feed/1", Some("tok en"), Some("s&c")),
            "https://podly.test/feed/1?feed_token=tok%20en&feed_secret=s%26c"
        );
        assert_eq!(
            append_feed_token("https://podly.test/feed/1?x=1", Some("tok"), Some("sec")),
            "https://podly.test/feed/1?x=1&feed_token=tok&feed_secret=sec"
        );
    }

    #[test]
    fn render_chapters_prefers_output_chapters_and_escapes_titles() {
        let raw = r#"{
            "chapters_kept": [{"title": "ignored", "start_time": 0}],
            "chapters_for_output": [
                {"title": "B < C", "start_time": 65},
                {"title": "Intro", "start_time": 0}
            ]
        }"#;

        assert_eq!(
            render_chapters(Some(raw)),
            "<p><strong>Podly Chapters</strong></p><ul><li>00:00 Intro</li><li>01:05 B &lt; C</li></ul>"
        );
    }

    #[test]
    fn normalize_word_timestamps_stream_contract_matches_python_filtering() {
        let dir = tempfile::tempdir().unwrap();
        let input = dir.path().join("input.json");
        let output = dir.path().join("output.json");
        fs::write(
            &input,
            r#"[
                {"sequence_num": "2", "words": [
                    {"word": "hello", "start": "1.0", "end": "1.5", "score": "0.9"},
                    {"word": "drop", "start": 2.0, "end": 1.0}
                ]},
                {"sequence_num": 3, "words": []}
            ]"#,
        )
        .unwrap();

        normalize_word_timestamps(TranscriptNormalizeArgs {
            input,
            output: output.clone(),
        })
        .unwrap();

        let value: Value = serde_json::from_str(&fs::read_to_string(output).unwrap()).unwrap();
        assert_eq!(
            value,
            serde_json::json!([
                {"sequence_num": 2, "words": [
                    {"word": "hello", "start": 1.0, "end": 1.5, "score": 0.9}
                ]}
            ])
        );
    }

    #[test]
    fn feed_render_reads_sqlite_and_includes_expected_rss_bits() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("podly.sqlite");
        let audio_path = dir.path().join("episode.mp3");
        fs::write(&audio_path, b"audio-bytes").unwrap();
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            "CREATE TABLE feed (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                image_url TEXT,
                last_changed_at TEXT
            );
            CREATE TABLE post (
                id INTEGER PRIMARY KEY,
                feed_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                guid TEXT NOT NULL,
                processed_audio_path TEXT,
                description TEXT,
                release_date TEXT,
                duration INTEGER,
                image_url TEXT,
                chapter_data TEXT,
                whitelisted BOOLEAN NOT NULL DEFAULT 0
            );",
        )
        .unwrap();
        conn.execute(
            "INSERT INTO feed (id, title, description, image_url, last_changed_at)
             VALUES (1, 'Feed & One', 'Desc', 'https://img.test/feed.png', '2024-01-02 03:04:05')",
            [],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO post (feed_id, title, guid, processed_audio_path, description, release_date, duration, image_url, chapter_data, whitelisted)
             VALUES (1, 'Episode <One>', 'guid-1', ?1, '<p>Hello</p>', '2024-01-03 04:05:06', 65, 'https://img.test/ep.png', ?2, 1)",
            params![
                audio_path.to_string_lossy(),
                r#"{"chapters_for_output":[{"title":"Intro","start_time":0}]}"#
            ],
        )
        .unwrap();
        drop(conn);

        let xml = render_feed(FeedRenderArgs {
            db: db_path,
            feed_id: 1,
            base_url: "https://podly.test".to_string(),
            include_unprocessed: false,
            feed_token: Some("tok".to_string()),
            feed_secret: Some("sec".to_string()),
        })
        .unwrap()
        .xml;

        assert!(xml.contains("<title>[podly] Feed &amp; One</title>"));
        assert!(
            xml.contains("https://podly.test/post/guid-1.mp3?feed_token=tok&amp;feed_secret=sec")
        );
        assert!(xml.contains("<itunes:duration>01:05</itunes:duration>"));
        assert!(xml.contains("<p><strong>Podly Chapters</strong></p><ul><li>00:00 Intro</li></ul>"));
        assert!(xml.contains("length=\"11\""));
    }

    #[test]
    fn chapters_write_replaces_chap_and_ctoc_frames() {
        let dir = tempfile::tempdir().unwrap();
        let audio = dir.path().join("audio.mp3");
        let chapters_json = dir.path().join("chapters.json");
        let removed_json = dir.path().join("removed.json");
        fs::write(&audio, b"not-real-audio-but-id3-can-write-tags").unwrap();
        fs::write(
            &chapters_json,
            r#"[
                {"title":"Intro","start_time_ms":0,"end_time_ms":1000},
                {"title":"Next","start_time_ms":1000,"end_time_ms":2000}
            ]"#,
        )
        .unwrap();
        fs::write(&removed_json, "[]").unwrap();

        write_chapters(ChaptersWriteArgs {
            audio: audio.clone(),
            chapters_json,
            removed_windows_json: removed_json,
        })
        .unwrap();

        let tag = Tag::read_from_path(audio).unwrap();
        assert_eq!(tag.chapters().count(), 2);
        assert_eq!(tag.tables_of_contents().count(), 1);
    }
}
