#!/usr/bin/env python3
"""Remove leftover word-timestamp hand-off files that the database already has.

Transcription writes data/transcript_artifacts/post_N/model_call_M/word_timestamps.json
so the writer can load it. Releases before the cleanup never deleted those files,
so they duplicate post.transcript_word_timestamps. This script finds the ones
that are safe to drop:

  identical   the post's column holds the same words (to the writer's rounding)
  superseded  the post was transcribed again since; the column holds the newer run

Everything else is left alone and listed: files whose post is gone, posts whose
column is empty, and files that differ from the column in the same run.

Dry run by default. With --apply, files are moved to transcript_artifacts_pruned/
next to the original folder; add --delete to remove them instead.

    uv run python scripts/prune_transcript_artifacts.py [--instance-dir DIR] [--apply] [--delete]
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# The writer rounds times to the millisecond, so allow that much difference.
TOLERANCE = 0.0006
WHISPER_PROMPT = "Whisper transcription job"


def stored_words(raw: Any) -> Any:
    """Decode post.transcript_word_timestamps: gzip BLOB, JSON text, or empty."""
    if isinstance(raw, bytes):
        raw = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
        raw = raw.decode()
    return None if raw in (None, "null") else json.loads(raw)


def words_match(artifact: Any, column: Any) -> bool:
    if not isinstance(artifact, list) or not isinstance(column, list):
        return False
    if len(artifact) != len(column):
        return False
    for seg_a, seg_b in zip(artifact, column, strict=True):
        words_a = seg_a.get("words") or []
        words_b = seg_b.get("words") or []
        if len(words_a) != len(words_b):
            return False
        for word_a, word_b in zip(words_a, words_b, strict=True):
            if word_a.get("word") != word_b.get("word"):
                return False
            for key in ("start", "end", "score"):
                a, b = word_a.get(key), word_b.get(key)
                if (a is None) != (b is None):
                    return False
                if a is not None and abs(a - b) > TOLERANCE:
                    return False
    return True


def classify(
    artifact: Any, column: Any, *, model_call_id: int, latest_run_id: int | None
) -> str:
    """Return identical, superseded, or the reason the file must be kept."""
    if column is None:
        return "keep: column empty"
    if words_match(artifact, column):
        return "identical"
    if latest_run_id is not None and model_call_id < latest_run_id:
        return "superseded"
    return "keep: differs from column"


def run(instance_dir: Path, *, apply: bool, delete: bool) -> Counter[str]:
    artifact_root = instance_dir / "data" / "transcript_artifacts"
    pruned_root = instance_dir / "data" / "transcript_artifacts_pruned"
    db = sqlite3.connect(f"file:{instance_dir / 'sqlite3.db'}?mode=ro", uri=True)
    counts: Counter[str] = Counter()
    kept: list[str] = []

    for path in sorted(artifact_root.glob("post_*/model_call_*/word_timestamps.json")):
        post_id = int(path.parent.parent.name.removeprefix("post_"))
        model_call_id = int(path.parent.name.removeprefix("model_call_"))
        row = db.execute(
            "SELECT transcript_word_timestamps FROM post WHERE id = ?", (post_id,)
        ).fetchone()
        if row is None:
            counts["keep: post missing"] += 1
            kept.append(f"{path} (post missing)")
            continue
        column = stored_words(row[0])
        latest = db.execute(
            "SELECT MAX(id) FROM model_call WHERE post_id = ? AND prompt = ?",
            (post_id, WHISPER_PROMPT),
        ).fetchone()[0]
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            counts["keep: unreadable"] += 1
            kept.append(f"{path} (unreadable)")
            continue

        verdict = classify(
            artifact, column, model_call_id=model_call_id, latest_run_id=latest
        )
        counts[verdict] += 1
        if verdict.startswith("keep"):
            kept.append(f"{path} ({verdict[6:]})")
            continue
        if not apply:
            continue
        if delete:
            path.unlink()
        else:
            target = pruned_root / path.relative_to(artifact_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), target)
        for directory in (path.parent, path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break

    mode = "applied" if apply else "dry run"
    print(f"{mode}: {dict(counts)}")
    for line in kept:
        print(f"  kept {line}")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instance-dir", type=Path, default=ROOT / "src" / "instance")
    parser.add_argument("--apply", action="store_true", help="move matching files")
    parser.add_argument(
        "--delete", action="store_true", help="with --apply, delete instead of move"
    )
    args = parser.parse_args()
    if args.delete and not args.apply:
        parser.error("--delete needs --apply")
    run(args.instance_dir, apply=args.apply, delete=args.delete)
    return 0


if __name__ == "__main__":
    sys.exit(main())
