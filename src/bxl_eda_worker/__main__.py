from __future__ import annotations

import argparse

from bxl_eda_worker.worker import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="bxl-eda-worker")
    sub = parser.add_subparsers(dest="cmd")

    run_p = sub.add_parser("run", help="Fetch sources and write today's digest.")
    run_p.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="Digest window size in hours (default: 24).",
    )
    run_p.add_argument(
        "--skip-headless",
        action="store_true",
        help="Skip Playwright sources (Council, Swiss admin). Useful when "
             "Chromium isn't installed or you want a fast dry run.",
    )

    seed_p = sub.add_parser(
        "seed-archive",
        help="Generate a fictitious weekly archive for 2026-W01..current-1. "
             "Idempotent — skips weeks already on disk. Requires ANTHROPIC_API_KEY.",
    )
    seed_p.add_argument(
        "--force",
        action="store_true",
        help="Regenerate weeks even if the file already exists.",
    )

    args = parser.parse_args()
    if args.cmd in (None, "run"):
        run(
            window_hours=getattr(args, "window_hours", 24),
            skip_headless=getattr(args, "skip_headless", False),
        )
    elif args.cmd == "seed-archive":
        from bxl_eda_worker.seed import seed_archive
        n = seed_archive(force=args.force)
        print(f"Seeded {n} weeks.")
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
