"""
Skyscanner flight price scraper — CLI entry point.

IMPORTANT — first run:
  Skyscanner uses PerimeterX bot detection. The first time you run the scraper
  (or whenever the session cookie expires), you'll need to manually solve a
  verification challenge in the browser window. Run the setup command first:

    python run_skyscanner.py setup

  This opens a browser and waits for you to establish a valid session.
  Once done, subsequent runs will reuse the saved cookies automatically.

Usage:
  python run_skyscanner.py setup
      Open browser for manual session setup (solve captcha once).

  python run_skyscanner.py scrape
      Scrape all 110 date pairs; skip any already scraped today.

  python run_skyscanner.py scrape --force
      Re-scrape all pairs regardless of today's state.

  python run_skyscanner.py scrape --outbound 2026-12-16
      Only scrape the 22 return-date combinations for Dec 16 outbound.

  python run_skyscanner.py scrape --outbound 2026-12-16 --return 2027-01-25
      Scrape exactly 1 date pair (useful for testing/debugging).

  python run_skyscanner.py scrape --dry-run
      Print all URLs that would be scraped; touch nothing.

  python run_skyscanner.py scrape --no-interactive
      Non-interactive mode (for cron jobs): skip any URL that returns a
      captcha instead of pausing to wait for manual solving.

  python run_skyscanner.py scrape --save-debug
      Save the last fetched page HTML to data/skyscanner/debug_page.html
      for inspection (helpful when debugging parser issues).

  python run_skyscanner.py stats
      Print a price summary table from the database.

  python run_skyscanner.py stats --outbound 2026-12-16
      Filter the summary to one outbound date.

  python run_skyscanner.py stats --latest
      Show prices only from the most recent scrape run per date pair.
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="Skyscanner flight price scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── setup ──────────────────────────────────────────────────────────────────
    sub.add_parser(
        "setup",
        help="Open browser for manual session setup (solve captcha once)",
    )

    # ── scrape ─────────────────────────────────────────────────────────────────
    scrape_cmd = sub.add_parser("scrape", help="Scrape flight prices")
    scrape_cmd.add_argument(
        "--force",
        action="store_true",
        help="Re-scrape all pairs even if already scraped today",
    )
    scrape_cmd.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print URLs that would be scraped; do nothing",
    )
    scrape_cmd.add_argument(
        "--outbound",
        metavar="YYYY-MM-DD",
        default=None,
        help="Only scrape pairs with this outbound date",
    )
    scrape_cmd.add_argument(
        "--return",
        dest="return_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Only scrape pairs with this return date",
    )
    scrape_cmd.add_argument(
        "--no-interactive",
        action="store_true",
        dest="no_interactive",
        help="Non-interactive mode: skip captcha URLs instead of waiting",
    )
    scrape_cmd.add_argument(
        "--save-debug",
        action="store_true",
        dest="save_debug",
        help="Save the last fetched page HTML to data/skyscanner/debug_page.html",
    )
    scrape_cmd.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )

    # ── stats ──────────────────────────────────────────────────────────────────
    stats_cmd = sub.add_parser("stats", help="Print price summary from database")
    stats_cmd.add_argument(
        "--outbound",
        metavar="YYYY-MM-DD",
        default=None,
        help="Filter summary to this outbound date",
    )
    stats_cmd.add_argument(
        "--return",
        dest="return_date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Filter summary to this return date",
    )
    stats_cmd.add_argument(
        "--latest",
        action="store_true",
        help="Show only prices from the most recent scrape run per date pair",
    )

    args = parser.parse_args()

    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Dispatch ───────────────────────────────────────────────────────────────
    if args.command == "setup":
        from scrapers.skyscanner.scraper import SkyscannerScraper
        SkyscannerScraper().setup()

    elif args.command == "scrape":
        from scrapers.skyscanner.scraper import SkyscannerScraper

        scraper = SkyscannerScraper()
        stats = scraper.run(
            force=args.force,
            dry_run=args.dry_run,
            interactive=not args.no_interactive,
            outbound_filter=args.outbound,
            return_filter=args.return_date,
            save_debug=args.save_debug,
        )
        if not args.dry_run:
            print(
                f"\nDone. scraped={stats['scraped']} skipped={stats['skipped']} "
                f"captcha={stats['captcha_hits']} errors={stats['errors']} "
                f"total_offers={stats['total_offers']}"
            )
            print(f"Data saved to: data/skyscanner/skyscanner.db")
            if stats["captcha_hits"] > 0:
                print(
                    f"\nWARNING: {stats['captcha_hits']} URL(s) were skipped due to captcha.\n"
                    f"Run `python run_skyscanner.py setup` to refresh the browser session."
                )

    elif args.command == "stats":
        from scrapers.skyscanner.scraper import print_stats
        print_stats(
            outbound_filter=args.outbound,
            return_filter=args.return_date,
            latest_only=args.latest,
        )


if __name__ == "__main__":
    main()
