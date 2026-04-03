"""
Skyscanner scraper configuration.
All hardcoded parameters for the Buenos Aires → Bogotá price monitor.
Edit this file to change routes, dates, or scraping behaviour.
"""
from datetime import date, timedelta
from pathlib import Path

# ── Route ──────────────────────────────────────────────────────────────────
ORIGIN = "buea"   # Buenos Aires (any airport — Skyscanner cluster code)
DESTINATION = "bog"  # Bogotá El Dorado

# ── Outbound dates (IDA) ────────────────────────────────────────────────────
OUTBOUND_DATES = [
    date(2026, 12, 16),
    date(2026, 12, 17),
    date(2026, 12, 18),
    date(2026, 12, 19),
    date(2026, 12, 20),
]

# ── Return dates (VUELTA): Jan 25 – Feb 15, 2027 ───────────────────────────
_return_start = date(2027, 1, 25)
_return_end = date(2027, 2, 15)
RETURN_DATES = [
    _return_start + timedelta(days=i)
    for i in range((_return_end - _return_start).days + 1)
]
# → 22 dates → 5 × 22 = 110 total combinations

# ── Passengers / cabin ─────────────────────────────────────────────────────
ADULTS = 1
CABIN_CLASS = "economy"  # economy | business | first | premiumeconomy

# ── URL ────────────────────────────────────────────────────────────────────
BASE_URL = "https://espanol.skyscanner.com/transporte/vuelos"
# Date format used in URL: YYMMDD  (e.g. date(2026,12,16) → "261216")


def build_search_url(outbound: date, return_: date) -> str:
    out_str = outbound.strftime("%y%m%d")
    ret_str = return_.strftime("%y%m%d")
    return (
        f"{BASE_URL}/{ORIGIN}/{DESTINATION}/{out_str}/{ret_str}/"
        f"?adultsv2={ADULTS}&cabinclass={CABIN_CLASS}&childrenv2=&ref=home"
    )


def all_date_pairs() -> list[tuple[date, date]]:
    """Return all (outbound_date, return_date) combinations."""
    return [
        (out, ret)
        for out in OUTBOUND_DATES
        for ret in RETURN_DATES
    ]


# ── Browser behaviour ──────────────────────────────────────────────────────
DELAY_MIN = 8.0    # seconds between page requests (lower bound)
DELAY_MAX = 15.0   # seconds between page requests (upper bound)

PAGE_LOAD_TIMEOUT_MS = 60_000   # ms — initial page.goto timeout
RESULTS_WAIT_MS = 45_000        # ms — wait for results to appear
SCROLL_STEPS = 5                # number of scroll steps to load more results
SCROLL_PAUSE_MS = 1_500         # ms pause between scroll steps

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Paths ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "skyscanner"
STATE_FILE = DATA_DIR / "state.json"
DB_FILE = DATA_DIR / "skyscanner.db"
DEBUG_PAGE_FILE = DATA_DIR / "debug_page.html"
