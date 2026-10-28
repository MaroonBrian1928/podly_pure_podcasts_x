import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "prune_transcript_artifacts.py"
)
spec = importlib.util.spec_from_file_location("prune_transcript_artifacts", SCRIPT)
assert spec is not None and spec.loader is not None
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)

WORDS = [{"sequence_num": 0, "words": [{"word": "hi", "start": 1.0, "end": 1.5}]}]


def _instance(
    tmp_path: Path, posts: dict[int, Any], runs: dict[int, list[int]]
) -> Path:
    (tmp_path / "data" / "transcript_artifacts").mkdir(parents=True)
    db = sqlite3.connect(tmp_path / "sqlite3.db")
    db.execute("CREATE TABLE post (id INTEGER PRIMARY KEY, transcript_word_timestamps)")
    db.execute(
        "CREATE TABLE model_call (id INTEGER PRIMARY KEY, post_id INTEGER, prompt TEXT)"
    )
    for post_id, column in posts.items():
        value = None if column is None else json.dumps(column)
        db.execute("INSERT INTO post VALUES (?, ?)", (post_id, value))
    for post_id, ids in runs.items():
        for model_call_id in ids:
            db.execute(
                "INSERT INTO model_call VALUES (?, ?, ?)",
                (model_call_id, post_id, prune.WHISPER_PROMPT),
            )
    db.commit()
    db.close()
    return tmp_path


def _artifact(root: Path, post_id: int, model_call_id: int, payload: Any) -> Path:
    path = (
        root
        / "data"
        / "transcript_artifacts"
        / f"post_{post_id}"
        / f"model_call_{model_call_id}"
        / "word_timestamps.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    return path


def test_rounding_noise_counts_as_identical_but_a_changed_word_does_not() -> None:
    noisy = [
        {
            "sequence_num": 0,
            "words": [{"word": "hi", "start": 1.0000000000000002, "end": 1.5}],
        }
    ]
    other = [{"sequence_num": 0, "words": [{"word": "yo", "start": 1.0, "end": 1.5}]}]

    assert prune.words_match(noisy, WORDS)
    assert not prune.words_match(other, WORDS)


def test_dry_run_moves_nothing(tmp_path: Path) -> None:
    root = _instance(tmp_path, {1: WORDS}, {1: [10]})
    path = _artifact(root, 1, 10, WORDS)

    counts = prune.run(root, apply=False, delete=False)

    assert counts["identical"] == 1
    assert path.is_file()


def test_apply_moves_safe_files_and_keeps_the_rest(tmp_path: Path) -> None:
    changed = [{"sequence_num": 0, "words": [{"word": "no", "start": 9.0, "end": 9.5}]}]
    root = _instance(
        tmp_path,
        {1: WORDS, 2: WORDS, 3: WORDS, 4: None},
        {1: [10], 2: [20, 21], 3: [30], 4: [40]},
    )
    same = _artifact(root, 1, 10, WORDS)
    older_run = _artifact(root, 2, 20, changed)
    same_run_differs = _artifact(root, 3, 30, changed)
    column_empty = _artifact(root, 4, 40, WORDS)
    post_gone = _artifact(root, 99, 90, WORDS)

    counts = prune.run(root, apply=True, delete=False)

    assert counts["identical"] == 1
    assert counts["superseded"] == 1
    assert not same.exists() and not older_run.exists()
    assert same_run_differs.is_file()
    assert column_empty.is_file()
    assert post_gone.is_file()
    pruned = root / "data" / "transcript_artifacts_pruned"
    assert (pruned / "post_1" / "model_call_10" / "word_timestamps.json").is_file()


def test_delete_flag_removes_instead_of_moving(tmp_path: Path) -> None:
    root = _instance(tmp_path, {1: WORDS}, {1: [10]})
    _artifact(root, 1, 10, WORDS)

    prune.run(root, apply=True, delete=True)

    assert not (root / "data" / "transcript_artifacts_pruned").exists()
    assert not (root / "data" / "transcript_artifacts" / "post_1").exists()
