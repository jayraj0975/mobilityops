"""Command-line entry point: ``python -m mobilityops.cli <command>``.

Commands are added phase by phase; each does one obvious thing and prints what it did.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from mobilityops.config import Settings
from mobilityops.log import configure_logging, get_logger
from mobilityops.sample import SYNTHETIC_LABEL, SampleSpec, generate_sample

log = get_logger("cli")


def cmd_sample(settings: Settings, args: argparse.Namespace) -> int:
    """Generate the synthetic sample into data/raw/sample (never into the real-data folder)."""
    if settings.mode != "sample":
        print("refusing to write synthetic data while MOBILITYOPS_MODE=real", file=sys.stderr)
        return 2
    settings.ensure_dirs()
    files = generate_sample(settings.raw_dir, SampleSpec(seed=args.seed, n_days=args.days))
    truth = json.loads(files.ground_truth.read_text())
    print(f"{SYNTHETIC_LABEL}: wrote {truth['rows_total']:,} trips to {files.directory}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mobilityops", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample", help="generate deterministic SYNTHETIC sample data")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--days", type=int, default=56)
    s.set_defaults(func=cmd_sample)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    return int(args.func(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
