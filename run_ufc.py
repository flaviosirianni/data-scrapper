"""
UFC Stats scraper — CLI entry point.

Usage:
  python run_ufc.py scrape                              # Incremental: new events only
  python run_ufc.py scrape --all                        # Re-scrape everything from scratch
  python run_ufc.py scrape --event-id 5c38639f860a5542 # Single event
  python run_ufc.py scrape --event-id ID1 --event-id ID2  # Multiple specific events
  python run_ufc.py scrape-upcoming                     # Scrape upcoming events fight cards
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
        description="Scrape fight statistics from ufcstats.com"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -------------------------------------------------------------------------
    # scrape — completed fights
    # -------------------------------------------------------------------------
    scrape_cmd = sub.add_parser("scrape", help="Scrape completed fight stats")
    scrape_cmd.add_argument(
        "--all",
        dest="scrape_all",
        action="store_true",
        help="Ignore state and re-scrape all events from scratch",
    )
    scrape_cmd.add_argument(
        "--event-id",
        dest="event_ids",
        action="append",
        metavar="ID",
        help="Scrape a specific event by ID (can be repeated)",
    )
    scrape_cmd.add_argument(
        "--since-year",
        dest="since_year",
        type=int,
        default=None,
        metavar="YEAR",
        help="Only scrape events from this year onwards (e.g. 2016)",
    )
    scrape_cmd.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )

    # -------------------------------------------------------------------------
    # scrape-upcoming — upcoming events fight cards (names only, no stats)
    # -------------------------------------------------------------------------
    upcoming_cmd = sub.add_parser(
        "scrape-upcoming", help="Scrape upcoming events fight cards (names, dates)"
    )
    upcoming_cmd.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging",
    )

    args = parser.parse_args()

    if getattr(args, "debug", False):
        logging.getLogger().setLevel(logging.DEBUG)

    if args.command == "scrape":
        from scrapers.ufc.scraper import UfcScraper

        scraper = UfcScraper()
        count = scraper.run(
            event_ids=args.event_ids,
            scrape_all=args.scrape_all,
            min_year=args.since_year,
        )
        print(f"\nDone. {count} new fight(s) scraped.")
        print(f"Data saved to: data/ufc/fights.json")

    elif args.command == "scrape-upcoming":
        from scrapers.ufc.upcoming import UfcUpcomingScraper

        scraper = UfcUpcomingScraper()
        count = scraper.run()
        print(f"\nDone. {count} upcoming fight(s) found.")
        print(f"Data saved to: data/ufc/upcoming.json")


if __name__ == "__main__":
    main()
