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

    args = parser.parse_args()
    if args.cmd in (None, "run"):
        run(
            window_hours=getattr(args, "window_hours", 24),
            skip_headless=getattr(args, "skip_headless", False),
        )
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
