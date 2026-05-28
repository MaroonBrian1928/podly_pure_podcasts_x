#!/usr/bin/env python3
"""Backfill legacy ModelCall prompt/completion token estimates."""

from __future__ import annotations

import argparse
import json

from app import create_app
from app.model_call_token_backfill import backfill_model_call_token_usage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate missing ModelCall token usage from stored text."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist estimates through the writer service. Defaults to dry run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of ModelCall rows to scan.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = create_app()
    with app.app_context():
        result = backfill_model_call_token_usage(apply=args.apply, limit=args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
