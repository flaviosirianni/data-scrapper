"""
UFC upcoming events scraper.

Fetches /statistics/events/upcoming and each event's fight card (names only —
no stats since fights haven't happened).  Results saved to data/ufc/upcoming.json.

Run with:
  python run_ufc.py scrape-upcoming
"""
import json
import logging
import time
import random
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page

from .parsers import parse_events_page, parse_event_page

logger = logging.getLogger(__name__)

BASE_URL         = "http://www.ufcstats.com"
UPCOMING_URL     = f"{BASE_URL}/statistics/events/upcoming"
DATA_DIR         = Path(__file__).parent.parent.parent / "data" / "ufc"
UPCOMING_FILE    = DATA_DIR / "upcoming.json"

DELAY_MIN = 1.5
DELAY_MAX = 3.0


def _polite_delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def _get_html(page: Page, url: str) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=15_000)
    return page.content()


class UfcUpcomingScraper:
    def run(self) -> int:
        """
        Scrapes upcoming events + fight cards.

        Returns number of upcoming fights found.
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        upcoming_fights = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            try:
                logger.info("Fetching upcoming events from %s", UPCOMING_URL)
                html = _get_html(page, UPCOMING_URL)
                events = parse_events_page(html)
                logger.info("Found %d upcoming event(s)", len(events))

                for event in events:
                    event_id   = event["event_id"]
                    event_name = event["event_name"]
                    event_date = event["event_date"]
                    event_loc  = event["event_location"]

                    event_url = f"{BASE_URL}/event-details/{event_id}"
                    logger.info("Fetching fight card: %s → %s", event_name, event_url)

                    try:
                        _polite_delay()
                        html = _get_html(page, event_url)
                        stubs = parse_event_page(html)
                        logger.info("  %d fight(s) on card", len(stubs))

                        for order, stub in enumerate(stubs, start=1):
                            upcoming_fights.append({
                                "fight_id":        stub["fight_id"],
                                "event_id":        event_id,
                                "event_name":      event_name,
                                "event_date":      event_date,
                                "event_location":  event_loc,
                                "card_order":      order,
                                "fighter_1_name":  stub["fighter_1_name"],
                                "fighter_2_name":  stub["fighter_2_name"],
                                "weight_class":    stub.get("weight_class", ""),
                            })
                    except Exception as e:
                        logger.error(
                            "Failed to scrape event card %s: %s", event_id, e, exc_info=True
                        )

            finally:
                context.close()
                browser.close()

        with UPCOMING_FILE.open("w") as f:
            json.dump(upcoming_fights, f, indent=2, ensure_ascii=False)

        logger.info("Saved %d upcoming fight(s) to %s", len(upcoming_fights), UPCOMING_FILE)
        return len(upcoming_fights)
