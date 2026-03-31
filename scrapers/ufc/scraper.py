"""
UFC Stats scraper — Playwright orchestrator.

Flow:
  1. Fetch all completed events from /statistics/events/completed
  2. Diff against state.json to find new events
  3. For each new event: fetch event page → collect fight IDs
  4. For each fight: fetch fight detail page → parse full stats
  5. Append results to data/ufc/fights.json and update state.json
"""
import json
import logging
import time
import random
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

from .parsers import parse_events_page, parse_event_page, parse_fight_page
from .models import FightRecord

logger = logging.getLogger(__name__)

BASE_URL = "http://www.ufcstats.com"
EVENTS_URL = f"{BASE_URL}/statistics/events/completed?page=all"
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "ufc"
STATE_FILE = DATA_DIR / "state.json"
FIGHTS_FILE = DATA_DIR / "fights.json"

# Polite delay range (seconds) between requests
DELAY_MIN = 1.5
DELAY_MAX = 3.0


def _event_year(event: dict) -> int:
    """Extract year from event_date string (e.g. 'March 28, 2026' → 2026)."""
    import re as _re
    m = _re.search(r"\b(19|20)\d{2}\b", event.get("event_date", ""))
    return int(m.group()) if m else 0


def _polite_delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def _load_state() -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return json.load(f)
    return {"scraped_event_ids": []}


def _save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2)


def _load_fights() -> list[dict]:
    if FIGHTS_FILE.exists():
        with FIGHTS_FILE.open() as f:
            return json.load(f)
    return []


def _save_fights(fights: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with FIGHTS_FILE.open("w") as f:
        json.dump(fights, f, indent=2, ensure_ascii=False)


def _get_html(page: Page, url: str, expand_rounds: bool = False) -> str:
    """Navigate to URL, optionally expand per-round sections, return page HTML."""
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=15_000)

    if expand_rounds:
        # Click all "PER ROUND" toggle buttons to expand per-round tables
        # ufcstats uses clickable <a> or <p> elements with arrow text
        for selector in [
            "a:has-text('Per Round')",
            "a:has-text('PER ROUND')",
            "p.b-fight-details__collapse-link_open",
            "[class*='collapse-link']",
        ]:
            try:
                toggles = page.locator(selector).all()
                for toggle in toggles:
                    try:
                        toggle.click(timeout=3_000)
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
            except Exception:
                pass

    return page.content()


class UfcScraper:
    def __init__(self):
        self.state = _load_state()
        self.fights = _load_fights()

    def _scraped_event_ids(self) -> set[str]:
        return set(self.state.get("scraped_event_ids", []))

    def _mark_event_scraped(self, event_id: str):
        ids = self._scraped_event_ids()
        ids.add(event_id)
        self.state["scraped_event_ids"] = sorted(ids)

    def run(
        self,
        event_ids: Optional[list[str]] = None,
        scrape_all: bool = False,
        min_year: Optional[int] = None,
    ) -> int:
        """
        Main entry point.

        Args:
            event_ids: If provided, scrape only these specific event IDs.
            scrape_all: If True, ignore state and re-scrape everything.
            min_year: If provided, skip events before this year.

        Returns:
            Number of new fights scraped.
        """
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        new_fight_count = 0

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
                if event_ids:
                    # Scrape specific events — fetch their metadata from the events page
                    events_to_scrape = self._resolve_event_ids(page, event_ids)
                else:
                    events_to_scrape = self._fetch_all_events(page, scrape_all, min_year=min_year)

                logger.info("%d event(s) to scrape", len(events_to_scrape))

                for event in events_to_scrape:
                    try:
                        count = self._scrape_event(page, event)
                        new_fight_count += count
                        self._mark_event_scraped(event["event_id"])
                        _save_state(self.state)
                        _save_fights(self.fights)
                        logger.info(
                            "Event '%s' done: %d fights scraped", event["event_name"], count
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to scrape event %s: %s", event["event_id"], e, exc_info=True
                        )

            finally:
                context.close()
                browser.close()

        logger.info("Total new fights scraped: %d", new_fight_count)
        return new_fight_count

    def _fetch_all_events(
        self, page: Page, scrape_all: bool, min_year: Optional[int] = None
    ) -> list[dict]:
        """Fetch events listing and return events not yet scraped."""
        logger.info("Fetching events list from %s", EVENTS_URL)
        html = _get_html(page, EVENTS_URL)
        all_events = parse_events_page(html)
        logger.info("Found %d total events", len(all_events))

        if min_year:
            before = len(all_events)
            all_events = [e for e in all_events if _event_year(e) >= min_year]
            logger.info("Filtered to %d events from %d+ (dropped %d older events)",
                        len(all_events), min_year, before - len(all_events))

        if scrape_all:
            return all_events

        scraped = self._scraped_event_ids()
        new_events = [e for e in all_events if e["event_id"] not in scraped]
        logger.info("%d new events to scrape", len(new_events))
        return new_events

    def _resolve_event_ids(self, page: Page, event_ids: list[str]) -> list[dict]:
        """
        For a list of explicit event IDs, fetch the events page to get metadata,
        then return matching events. Falls back to minimal metadata if not found.
        """
        html = _get_html(page, EVENTS_URL)
        all_events = parse_events_page(html)
        event_map = {e["event_id"]: e for e in all_events}

        result = []
        for eid in event_ids:
            if eid in event_map:
                result.append(event_map[eid])
            else:
                # Minimal fallback — we only have the ID
                result.append({"event_id": eid, "event_name": eid, "event_date": "", "event_location": ""})
        return result

    def _scrape_event(self, page: Page, event_meta: dict) -> int:
        """Scrape all fights for a single event. Returns number of fights added."""
        event_id = event_meta["event_id"]
        event_url = f"{BASE_URL}/event-details/{event_id}"
        logger.info("Scraping event: %s → %s", event_meta["event_name"], event_url)

        _polite_delay()
        html = _get_html(page, event_url)
        fight_stubs = parse_event_page(html)
        logger.info("  %d fights found in event", len(fight_stubs))

        existing_fight_ids = {f["fight_id"] for f in self.fights}
        new_count = 0

        for stub in fight_stubs:
            fight_id = stub["fight_id"]
            if fight_id in existing_fight_ids:
                logger.debug("  Fight %s already scraped, skipping", fight_id)
                continue

            try:
                fight_record = self._scrape_fight(page, fight_id, stub, event_meta)
                self.fights.append(fight_record.to_dict())
                existing_fight_ids.add(fight_id)
                new_count += 1
            except Exception as e:
                logger.error("  Failed to scrape fight %s: %s", fight_id, e, exc_info=True)

        return new_count

    def _scrape_fight(
        self, page: Page, fight_id: str, stub: dict, event_meta: dict
    ) -> FightRecord:
        """Fetch and parse a single fight detail page."""
        fight_url = f"{BASE_URL}/fight-details/{fight_id}"
        logger.info("  Scraping fight: %s vs %s → %s", stub["fighter_1_name"], stub["fighter_2_name"], fight_url)

        _polite_delay()
        html = _get_html(page, fight_url, expand_rounds=True)
        record = parse_fight_page(html)

        # Inject event context and stub data
        record.fight_id = fight_id
        record.event_id = event_meta["event_id"]
        record.event_name = event_meta["event_name"]
        record.event_date = event_meta["event_date"]
        record.event_location = event_meta["event_location"]

        # Fill in fighter names/results from stub if parsers missed them
        if not record.fighter_1_name:
            record.fighter_1_name = stub["fighter_1_name"]
            record.fighter_1_result = stub["fighter_1_result"]
            record.fighter_2_name = stub["fighter_2_name"]
            record.fighter_2_result = stub["fighter_2_result"]

        # Fill weight class, method, round, time from stub if missing
        if not record.weight_class:
            record.weight_class = stub.get("weight_class", "")
        if not record.method:
            record.method = stub.get("method", "")
        if record.round is None:
            record.round = stub.get("round")
        if not record.time:
            record.time = stub.get("time", "")
        if not record.bonuses:
            record.bonuses = stub.get("bonuses", [])

        return record
