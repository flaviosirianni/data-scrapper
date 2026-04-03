"""
Skyscanner flight price scraper — Playwright orchestrator.

Anti-bot notes:
  - Skyscanner uses PerimeterX. Headed mode (headless=False) is required.
  - A persistent browser profile is used to reuse session cookies between runs.
    On the first run (or when cookies expire), PerimeterX may show a captcha.
    The scraper detects this and either:
      a) In interactive mode: pauses and asks the user to solve it in the
         open browser window, then presses Enter to continue.
      b) In non-interactive mode (cron): logs the captcha hit, skips the URL,
         and continues with the remaining searches.
  - Setup: run `python run_skyscanner.py setup` once to establish a valid session.

Flow:
  1. Load state.json (tracks last_scraped_at per date-pair).
  2. Build all 110 (outbound, return) date combinations.
  3. Launch persistent Chrome context (headed).
  4. Navigate to homepage first to establish referrer / warm up session.
  5. For each date pair: navigate → detect captcha/results → parse → write DB.
  6. Commit after each successful URL, update state immediately.
"""

import json
import logging
import random
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

from .config import (
    ORIGIN, DESTINATION, ADULTS, CABIN_CLASS,
    DATA_DIR, STATE_FILE, DB_FILE, DEBUG_PAGE_FILE,
    DELAY_MIN, DELAY_MAX,
    PAGE_LOAD_TIMEOUT_MS, RESULTS_WAIT_MS, SCROLL_STEPS, SCROLL_PAUSE_MS,
    USER_AGENT,
    build_search_url, all_date_pairs,
)
from .models import FlightOffer, FlightSegment
from .parsers import parse_skyscanner_page, is_captcha_page

logger = logging.getLogger(__name__)

BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ── State management ───────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        with STATE_FILE.open() as f:
            return json.load(f)
    return {"last_scraped": {}}


def _save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with STATE_FILE.open("w") as f:
        json.dump(state, f, indent=2)


def _state_key(out: date, ret: date) -> str:
    return f"{out.strftime('%y%m%d')}_{ret.strftime('%y%m%d')}"


def _already_scraped_today(state: dict, key: str) -> bool:
    ts = state.get("last_scraped", {}).get(key)
    if not ts:
        return False
    try:
        scraped = datetime.fromisoformat(ts).date()
        return scraped == datetime.now(timezone.utc).date()
    except Exception:
        return False


def _update_state(state: dict, key: str):
    state.setdefault("last_scraped", {})[key] = datetime.now(timezone.utc).isoformat()


# ── Database ───────────────────────────────────────────────────────────────────

def _open_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _create_tables(conn)
    return conn


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at      TEXT NOT NULL,
            origin          TEXT NOT NULL,
            destination     TEXT NOT NULL,
            outbound_date   TEXT NOT NULL,
            return_date     TEXT NOT NULL,
            adults          INTEGER NOT NULL DEFAULT 1,
            cabin_class     TEXT NOT NULL DEFAULT 'economy',
            url             TEXT NOT NULL,
            offers_found    INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'ok',
            error_message   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_runs_dates
            ON scrape_runs (outbound_date, return_date);
        CREATE INDEX IF NOT EXISTS idx_runs_scraped_at
            ON scrape_runs (scraped_at);

        CREATE TABLE IF NOT EXISTS flight_offers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              INTEGER NOT NULL REFERENCES scrape_runs(id),
            scraped_at          TEXT NOT NULL,
            outbound_date       TEXT NOT NULL,
            return_date         TEXT NOT NULL,
            price_total         REAL,
            price_currency      TEXT,
            price_raw           TEXT,
            out_airline         TEXT,
            out_airlines_all    TEXT,
            out_origin          TEXT,
            out_destination     TEXT,
            out_depart_time     TEXT,
            out_arrive_time     TEXT,
            out_duration        TEXT,
            out_stops           INTEGER,
            out_stopover_codes  TEXT,
            ret_airline         TEXT,
            ret_airlines_all    TEXT,
            ret_origin          TEXT,
            ret_destination     TEXT,
            ret_depart_time     TEXT,
            ret_arrive_time     TEXT,
            ret_duration        TEXT,
            ret_stops           INTEGER,
            ret_stopover_codes  TEXT,
            provider            TEXT,
            is_recommended      INTEGER DEFAULT 0,
            is_cheapest         INTEGER DEFAULT 0,
            is_fastest          INTEGER DEFAULT 0,
            co2_grams           INTEGER,
            co2_note            TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_offers_run_id
            ON flight_offers (run_id);
        CREATE INDEX IF NOT EXISTS idx_offers_dates
            ON flight_offers (outbound_date, return_date);
        CREATE INDEX IF NOT EXISTS idx_offers_scraped_at
            ON flight_offers (scraped_at);
        CREATE INDEX IF NOT EXISTS idx_offers_price
            ON flight_offers (price_total);

        CREATE TABLE IF NOT EXISTS flight_segments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id        INTEGER NOT NULL REFERENCES flight_offers(id),
            direction       TEXT NOT NULL,
            segment_order   INTEGER NOT NULL,
            airline         TEXT,
            flight_number   TEXT,
            origin          TEXT,
            destination     TEXT,
            depart_time     TEXT,
            arrive_time     TEXT,
            depart_date     TEXT,
            arrive_date     TEXT,
            duration        TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_segments_offer_id
            ON flight_segments (offer_id);
    """)
    conn.commit()


def _insert_run(conn: sqlite3.Connection, scraped_at: str, url: str,
                outbound_date: str, return_date: str,
                status: str = "ok", offers_found: int = 0,
                error_message: Optional[str] = None) -> int:
    cur = conn.execute(
        """INSERT INTO scrape_runs
           (scraped_at, origin, destination, outbound_date, return_date,
            adults, cabin_class, url, offers_found, status, error_message)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (scraped_at, ORIGIN, DESTINATION, outbound_date, return_date,
         ADULTS, CABIN_CLASS, url, offers_found, status, error_message),
    )
    return cur.lastrowid


def _insert_offer(conn: sqlite3.Connection, offer: FlightOffer) -> int:
    cur = conn.execute(
        """INSERT INTO flight_offers
           (run_id, scraped_at, outbound_date, return_date,
            price_total, price_currency, price_raw,
            out_airline, out_airlines_all, out_origin, out_destination,
            out_depart_time, out_arrive_time, out_duration, out_stops, out_stopover_codes,
            ret_airline, ret_airlines_all, ret_origin, ret_destination,
            ret_depart_time, ret_arrive_time, ret_duration, ret_stops, ret_stopover_codes,
            provider, is_recommended, is_cheapest, is_fastest, co2_grams, co2_note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            offer.run_id, offer.scraped_at, offer.outbound_date, offer.return_date,
            offer.price_total, offer.price_currency, offer.price_raw,
            offer.out_airline,
            json.dumps(offer.out_airlines_all, ensure_ascii=False),
            offer.out_origin, offer.out_destination,
            offer.out_depart_time, offer.out_arrive_time, offer.out_duration,
            offer.out_stops,
            json.dumps(offer.out_stopover_codes, ensure_ascii=False),
            offer.ret_airline,
            json.dumps(offer.ret_airlines_all, ensure_ascii=False),
            offer.ret_origin, offer.ret_destination,
            offer.ret_depart_time, offer.ret_arrive_time, offer.ret_duration,
            offer.ret_stops,
            json.dumps(offer.ret_stopover_codes, ensure_ascii=False),
            offer.provider,
            int(offer.is_recommended), int(offer.is_cheapest), int(offer.is_fastest),
            offer.co2_grams, offer.co2_note,
        ),
    )
    return cur.lastrowid


def _insert_segment(conn: sqlite3.Connection, offer_id: int, seg: FlightSegment):
    conn.execute(
        """INSERT INTO flight_segments
           (offer_id, direction, segment_order, airline, flight_number,
            origin, destination, depart_time, arrive_time, depart_date, arrive_date, duration)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (offer_id, seg.direction, seg.segment_order, seg.airline, seg.flight_number,
         seg.origin, seg.destination, seg.depart_time, seg.arrive_time,
         seg.depart_date, seg.arrive_date, seg.duration),
    )


# ── Browser helpers ────────────────────────────────────────────────────────────

def _polite_delay():
    t = random.uniform(DELAY_MIN, DELAY_MAX)
    logger.debug("Waiting %.1fs", t)
    time.sleep(t)


def _launch_context(pw) -> BrowserContext:
    """Launch a persistent Chrome context (headed, real Chrome binary)."""
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    import os
    chrome_exists = os.path.exists(CHROME_PATH)
    kwargs = dict(
        user_data_dir=str(BROWSER_PROFILE_DIR),
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
    )
    if chrome_exists:
        kwargs["channel"] = "chrome"
        logger.info("Using real Chrome binary")
    else:
        logger.info("Chrome not found, using Playwright's Chromium")
    return pw.chromium.launch_persistent_context(**kwargs)


def _dismiss_consent(page: Page):
    """Try to dismiss cookie/GDPR consent popup (only needed once per session)."""
    for sel in [
        "button:has-text('Aceptar')",
        "button:has-text('Acepto')",
        "[data-testid='accept-cookies-button']",
        "button:has-text('Accept')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                logger.info("Dismissed consent popup via: %s", sel)
                page.wait_for_timeout(1_200)
                return
        except Exception:
            pass


def _wait_for_results(page: Page) -> bool:
    """
    Wait for flight result cards to appear.
    Returns True if results found, False if still on captcha/error page.
    """
    result_selectors = [
        "[data-testid='itinerary-card-wrapper']",
        "[data-testid='HitItem']",
        "[data-testid='flight-card']",
        "[class*='ItineraryCard']",
        "[class*='FlightCard']",
        "[class*='HitItem']",
    ]
    for sel in result_selectors:
        try:
            page.wait_for_selector(sel, state="visible", timeout=RESULTS_WAIT_MS)
            logger.debug("Results found via selector: %s", sel)
            return True
        except Exception:
            pass

    # Check if page loaded but no cards (might be "no results" state)
    html = page.content()
    if len(html) > 50_000:
        logger.debug("Page is large (%d chars) — may have results despite no card selector match", len(html))
        return True  # Let parser handle it

    return False


def _scroll_page(page: Page):
    """Scroll down to trigger lazy-loading of more results."""
    for _ in range(SCROLL_STEPS):
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(SCROLL_PAUSE_MS)


def _handle_captcha_interactive(page: Page, url: str) -> bool:
    """
    Called when a captcha is detected in interactive mode.
    Opens the browser, prints instructions, waits for user to solve it.
    Returns True if user solved it, False if user aborted.
    """
    print("\n" + "=" * 70)
    print("CAPTCHA DETECTED")
    print(f"URL: {url}")
    print()
    print("The browser window is open. Please:")
    print("  1. Look at the browser window")
    print("  2. Complete the 'Are you a person or a robot?' challenge")
    print("  3. Wait for the flight results to appear")
    print("  4. Come back here and press Enter to continue scraping")
    print("  (or type 'skip' + Enter to skip this URL)")
    print("=" * 70)

    try:
        user_input = input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if user_input == "skip":
        return False

    # Check if results are now visible
    html = page.content()
    if is_captcha_page(html):
        print("Page still showing captcha — skipping this URL.")
        return False
    return True


# ── Main scraper class ─────────────────────────────────────────────────────────

class SkyscannerScraper:

    def setup(self):
        """
        Interactive setup: opens the browser and loads Skyscanner so the user
        can manually establish a valid session (solve any captcha once).
        The session cookies are saved to the persistent profile for future runs.
        """
        print("Opening browser for Skyscanner session setup...")
        print("Please navigate to espanol.skyscanner.com and complete any verification.")
        print("Once you see search results, come back here and press Enter.")

        with sync_playwright() as pw:
            ctx = _launch_context(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            page.goto("https://espanol.skyscanner.com/vuelos",
                      wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            _dismiss_consent(page)

            input("\nPress Enter when done → ")
            ctx.close()
        print("Session saved. You can now run the scraper.")

    def run(
        self,
        force: bool = False,
        dry_run: bool = False,
        interactive: bool = True,
        outbound_filter: Optional[str] = None,   # YYYY-MM-DD
        return_filter: Optional[str] = None,      # YYYY-MM-DD
        save_debug: bool = False,
    ) -> dict:
        """
        Scrape all configured date pairs and write results to SQLite.

        Returns a summary dict: {scraped, skipped, captcha_hits, errors, total_offers}.
        """
        state = _load_state()
        conn = _open_db()
        pairs = all_date_pairs()

        # Apply date filters
        if outbound_filter:
            pairs = [(o, r) for o, r in pairs if o.isoformat() == outbound_filter]
        if return_filter:
            pairs = [(o, r) for o, r in pairs if r.isoformat() == return_filter]

        if not pairs:
            logger.warning("No date pairs match the given filters.")
            return {"scraped": 0, "skipped": 0, "captcha_hits": 0, "errors": 0, "total_offers": 0}

        logger.info("Total date pairs to process: %d", len(pairs))

        stats = {"scraped": 0, "skipped": 0, "captcha_hits": 0, "errors": 0, "total_offers": 0}

        if dry_run:
            for out, ret in pairs:
                url = build_search_url(out, ret)
                key = _state_key(out, ret)
                already = _already_scraped_today(state, key) and not force
                status = "SKIP (already today)" if already else "WOULD SCRAPE"
                print(f"[{status}] {url}")
            return stats

        with sync_playwright() as pw:
            ctx = _launch_context(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Warm up: visit homepage
            logger.info("Warming up: loading Skyscanner homepage...")
            try:
                page.goto("https://espanol.skyscanner.com/vuelos",
                          wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
                page.wait_for_timeout(2_000)
                _dismiss_consent(page)
                logger.info("Homepage loaded (%d chars)", len(page.content()))
            except Exception as e:
                logger.warning("Homepage load failed: %s", e)

            consent_dismissed = True  # Attempted above

            for out, ret in pairs:
                url = build_search_url(out, ret)
                key = _state_key(out, ret)
                out_str = out.isoformat()
                ret_str = ret.isoformat()
                scraped_at = datetime.now(timezone.utc).isoformat()

                if not force and _already_scraped_today(state, key):
                    logger.debug("Skip %s→%s: already scraped today", out_str, ret_str)
                    stats["skipped"] += 1
                    continue

                logger.info("Scraping %s → %s", out_str, ret_str)
                _polite_delay()

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
                    page.wait_for_timeout(2_000)

                    if not consent_dismissed:
                        _dismiss_consent(page)
                        consent_dismissed = True

                    html = page.content()

                    if is_captcha_page(html):
                        logger.warning("Captcha detected for %s → %s", out_str, ret_str)
                        stats["captcha_hits"] += 1

                        if interactive:
                            solved = _handle_captcha_interactive(page, url)
                            if solved:
                                html = page.content()
                            else:
                                _insert_run(conn, scraped_at, url, out_str, ret_str,
                                            status="captcha")
                                conn.commit()
                                continue
                        else:
                            _insert_run(conn, scraped_at, url, out_str, ret_str,
                                        status="captcha")
                            conn.commit()
                            continue

                    # Wait for results to render
                    found = _wait_for_results(page)
                    if found:
                        _scroll_page(page)
                        html = page.content()

                    if save_debug:
                        DEBUG_PAGE_FILE.write_text(html, encoding="utf-8")
                        logger.info("Debug page saved to %s", DEBUG_PAGE_FILE)

                    # Parse
                    offers = parse_skyscanner_page(html, out_str, ret_str)

                    if not offers and len(html) > 30_000:
                        status = "empty"
                    elif not offers:
                        status = "error"
                    else:
                        status = "ok"

                    # Write run
                    run_id = _insert_run(conn, scraped_at, url, out_str, ret_str,
                                         status=status, offers_found=len(offers))

                    # Write offers + segments
                    for offer in offers:
                        offer.run_id = run_id
                        offer.scraped_at = scraped_at
                        offer_id = _insert_offer(conn, offer)
                        for seg in offer.segments:
                            _insert_segment(conn, offer_id, seg)

                    conn.commit()
                    _update_state(state, key)
                    _save_state(state)

                    stats["scraped"] += 1
                    stats["total_offers"] += len(offers)
                    logger.info("  → %d offers (status=%s)", len(offers), status)

                except Exception as e:
                    logger.error("Error scraping %s → %s: %s", out_str, ret_str, e, exc_info=True)
                    stats["errors"] += 1
                    try:
                        _insert_run(conn, scraped_at, url, out_str, ret_str,
                                    status="error", error_message=str(e)[:500])
                        conn.commit()
                    except Exception:
                        pass

            ctx.close()

        conn.close()
        return stats


# ── Stats query ────────────────────────────────────────────────────────────────

def print_stats(outbound_filter: Optional[str] = None, return_filter: Optional[str] = None,
                latest_only: bool = False):
    """Print a price summary table from the database."""
    if not DB_FILE.exists():
        print("No database found. Run scrape first.")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    conditions = []
    params = []
    if outbound_filter:
        conditions.append("f.outbound_date = ?")
        params.append(outbound_filter)
    if return_filter:
        conditions.append("f.return_date = ?")
        params.append(return_filter)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    if latest_only:
        # Cheapest offer from the most recent run per date pair
        query = f"""
            SELECT
                f.outbound_date, f.return_date,
                MIN(f.price_total) AS cheapest,
                MAX(f.price_total) AS priciest,
                COUNT(*) AS num_offers,
                MAX(r.scraped_at) AS last_scraped
            FROM flight_offers f
            JOIN scrape_runs r ON f.run_id = r.id
            {where}
            GROUP BY f.outbound_date, f.return_date
            ORDER BY f.outbound_date, f.return_date
        """
    else:
        # Cheapest ever seen across all scrape runs
        query = f"""
            SELECT
                f.outbound_date, f.return_date,
                MIN(f.price_total) AS cheapest,
                MAX(f.price_total) AS priciest,
                COUNT(*) AS num_offers,
                MAX(r.scraped_at) AS last_scraped
            FROM flight_offers f
            JOIN scrape_runs r ON f.run_id = r.id
            {where}
            GROUP BY f.outbound_date, f.return_date
            ORDER BY cheapest
        """

    rows = conn.execute(query, params).fetchall()

    if not rows:
        print("No data found.")
        conn.close()
        return

    # Header
    print(f"\n{'Ida':<12} {'Vuelta':<12} {'Mínimo':>12} {'Máximo':>12} {'#Ofertas':>9}  Última scrapeada")
    print("-" * 75)
    for row in rows:
        cheapest = f"${row['cheapest']:,.0f}" if row['cheapest'] else "N/A"
        priciest = f"${row['priciest']:,.0f}" if row['priciest'] else "N/A"
        last = row['last_scraped'][:19].replace("T", " ") if row['last_scraped'] else "?"
        print(f"{row['outbound_date']:<12} {row['return_date']:<12} {cheapest:>12} {priciest:>12} {row['num_offers']:>9}  {last}")

    total_runs = conn.execute("SELECT COUNT(*) FROM scrape_runs WHERE status='ok'").fetchone()[0]
    total_captchas = conn.execute("SELECT COUNT(*) FROM scrape_runs WHERE status='captcha'").fetchone()[0]
    print(f"\nTotal scrape runs: {total_runs} ok, {total_captchas} captcha")
    conn.close()
