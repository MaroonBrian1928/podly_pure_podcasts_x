#!/usr/bin/env python3
"""Export a synthetic, migration-current service-migration benchmark fixture."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from tests.writer_parity_fixtures import export_writer_parity_instance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=("standard", "benchmark"),
        default="standard",
        help="benchmark seeds 200 posts for concurrent feed/RSS workloads",
    )
    args = parser.parse_args()
    post_count = 200 if args.profile == "benchmark" else 2
    manifest = export_writer_parity_instance(
        args.output, benchmark_post_count=post_count
    )
    print(
        json.dumps(
            {
                "instance_dir": str(args.output.resolve()),
                "post_count": post_count,
                "manifest": asdict(manifest),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
