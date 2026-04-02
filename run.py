#!/usr/bin/env python3
"""CLI entry point for the Literature Monitor."""

import argparse
import logging
import sys

from lit_monitor.main import run


def main():
    parser = argparse.ArgumentParser(
        description="Literature Monitor — automated academic paper digest",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and build digest without sending email. Saves preview HTML.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Save digest HTML to this file path",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        total = run(
            config_path=args.config,
            dry_run=args.dry_run,
            output_html=args.output,
        )
        print(f"\nDone — {total} new papers processed.")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logging.exception("Unexpected error")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
