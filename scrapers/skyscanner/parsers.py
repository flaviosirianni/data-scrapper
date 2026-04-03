"""
Skyscanner results page parser.

Strategy (in priority order):
  1. JSON blob extraction — find embedded JSON in <script> tags (most reliable,
     independent of CSS class changes).
  2. BeautifulSoup DOM parsing — use data-testid attributes and structural patterns
     as fallback.

Both strategies return a list of FlightOffer objects.
"""
import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from .models import FlightOffer, FlightSegment

logger = logging.getLogger(__name__)

# ── Price parsing ──────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> Optional[float]:
    """
    Normalize CLP price strings to float.
    Examples:
      "$ 580.590"  → 580590.0
      "$1,311,785" → 1311785.0
      "580590"     → 580590.0
    """
    if not raw:
        return None
    # Remove currency symbols, letters, spaces
    cleaned = re.sub(r"[^\d.,]", "", raw.strip())
    if not cleaned:
        return None
    # CLP uses dot as thousands separator, no decimal fraction
    # USD/EUR uses comma as thousands separator, dot as decimal
    # Heuristic: if there's a dot and the part after it has 3 digits → thousands sep
    if "." in cleaned and not "," in cleaned:
        parts = cleaned.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            # All decimals are 3 digits → thousands separators
            cleaned = cleaned.replace(".", "")
    elif "," in cleaned and "." in cleaned:
        # e.g. "1,311,785.50" → USD style
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Could be thousands or decimal; if last group has 3 digits → thousands
        parts = cleaned.split(",")
        if len(parts[-1]) == 3:
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        logger.debug("Could not parse price: %r", raw)
        return None


def _parse_stops(text: str) -> Optional[int]:
    """'Directo' → 0, '1 escala' → 1, '2 escalas' → 2."""
    if not text:
        return None
    text = text.strip().lower()
    if "directo" in text or "nonstop" in text or "direct" in text:
        return 0
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


# ── Strategy 1: JSON blob extraction ──────────────────────────────────────────

def _extract_json_blob(html: str) -> Optional[dict]:
    """
    Skyscanner embeds search results in JavaScript variables.
    Try several known patterns.
    Returns a parsed dict/list if found, else None.
    """
    patterns = [
        # Next.js server-side data (most common for Skyscanner's node backend)
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
        # Skyscanner-specific client config
        r'window\.__SKYSCANNER_CLIENT_CONFIG__\s*=\s*({.+?})(?:;|\s*</script)',
        # Generic window state blob
        r'window\.__initialState__\s*=\s*({.+?})(?:;|\s*</script)',
        r'window\.__data__\s*=\s*({.+?})(?:;|\s*</script)',
        # Conductor / results state
        r'"itineraries"\s*:\s*(\[.{100,}?\])',
    ]
    for pattern in patterns:
        try:
            m = re.search(pattern, html, re.DOTALL)
            if m:
                blob = json.loads(m.group(1))
                logger.debug("JSON blob found via pattern: %s", pattern[:40])
                return blob
        except (json.JSONDecodeError, Exception):
            continue
    return None


def _offers_from_json(blob: dict, outbound_date: str, return_date: str) -> list[FlightOffer]:
    """
    Navigate the JSON blob to extract FlightOffer objects.
    The exact key path depends on Skyscanner's internal structure; we try
    multiple known paths and fall back gracefully.
    """
    offers = []

    def _find_itineraries(node, depth=0):
        """Recursively search for itinerary-like arrays in the blob."""
        if depth > 10:
            return []
        if isinstance(node, list) and node:
            # Check if items look like itineraries
            sample = node[0] if isinstance(node[0], dict) else {}
            if any(k in sample for k in ["price", "pricing", "legs", "itineraryId", "cheapestPrice"]):
                return node
        if isinstance(node, dict):
            for key in ["itineraries", "results", "flights", "items", "flightItineraries"]:
                if key in node:
                    result = _find_itineraries(node[key], depth + 1)
                    if result:
                        return result
            for value in node.values():
                if isinstance(value, (dict, list)):
                    result = _find_itineraries(value, depth + 1)
                    if result:
                        return result
        return []

    itineraries = _find_itineraries(blob)
    if not itineraries:
        logger.debug("No itineraries found in JSON blob")
        return []

    logger.info("JSON blob: found %d itinerary-like items", len(itineraries))

    for item in itineraries:
        if not isinstance(item, dict):
            continue
        try:
            offer = _parse_json_itinerary(item, outbound_date, return_date)
            if offer:
                offers.append(offer)
        except Exception as e:
            logger.debug("Error parsing JSON itinerary: %s", e)
            continue

    return offers


def _get(d: dict, *keys, default=None):
    """Safely navigate nested dict."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return default
    return cur


def _parse_json_itinerary(item: dict, outbound_date: str, return_date: str) -> Optional[FlightOffer]:
    """Parse a single itinerary dict from Skyscanner's JSON blob."""
    offer = FlightOffer(outbound_date=outbound_date, return_date=return_date)

    # Price — try several paths
    for price_path in [
        ["cheapestPrice", "amount"],
        ["price", "amount"],
        ["pricing", "price"],
        ["totalPrice"],
        ["price"],
    ]:
        val = _get(item, *price_path)
        if val is not None:
            raw = str(val)
            offer.price_raw = raw
            offer.price_total = _parse_price(raw)
            currency_path = price_path[:-1] + ["currency"]
            offer.price_currency = _get(item, *currency_path) or "CLP"
            break

    # Legs
    legs = item.get("legs", []) or item.get("outboundLeg", [])
    if isinstance(legs, dict):
        legs = [legs]

    for i, leg in enumerate(legs[:2]):  # at most outbound + return
        direction = "outbound" if i == 0 else "return"
        segments_data = leg.get("segments", leg.get("stopCount", []))

        airline = leg.get("carrier", {})
        if isinstance(airline, dict):
            airline_name = airline.get("name", "") or airline.get("displayCode", "")
        else:
            airline_name = str(airline)

        stops = leg.get("stopCount", leg.get("stops"))
        duration = leg.get("duration")
        if isinstance(duration, (int, float)):
            h, m = divmod(int(duration), 60)
            duration = f"{h}h {m}m"
        elif duration is None:
            duration = ""

        origin = leg.get("origin", {}) if isinstance(leg.get("origin"), dict) else {}
        dest = leg.get("destination", {}) if isinstance(leg.get("destination"), dict) else {}

        if direction == "outbound":
            offer.out_airline = airline_name
            offer.out_stops = _parse_stops(str(stops)) if stops is not None else None
            offer.out_duration = str(duration)
            offer.out_origin = origin.get("displayCode", origin.get("iata", "")) if isinstance(origin, dict) else str(origin)
            offer.out_destination = dest.get("displayCode", dest.get("iata", "")) if isinstance(dest, dict) else str(dest)
            offer.out_depart_time = leg.get("departure", "")[:5] if leg.get("departure") else ""
            offer.out_arrive_time = leg.get("arrival", "")[:5] if leg.get("arrival") else ""
        else:
            offer.ret_airline = airline_name
            offer.ret_stops = _parse_stops(str(stops)) if stops is not None else None
            offer.ret_duration = str(duration)
            offer.ret_origin = origin.get("displayCode", origin.get("iata", "")) if isinstance(origin, dict) else str(origin)
            offer.ret_destination = dest.get("displayCode", dest.get("iata", "")) if isinstance(dest, dict) else str(dest)
            offer.ret_depart_time = leg.get("departure", "")[:5] if leg.get("departure") else ""
            offer.ret_arrive_time = leg.get("arrival", "")[:5] if leg.get("arrival") else ""

    # Tags
    tags = item.get("tags", item.get("badges", []))
    if isinstance(tags, list):
        offer.is_recommended = any("recomend" in str(t).lower() for t in tags)
        offer.is_cheapest = any("barat" in str(t).lower() or "cheap" in str(t).lower() for t in tags)
        offer.is_fastest = any("rapid" in str(t).lower() or "fast" in str(t).lower() for t in tags)

    if offer.price_total is None and not offer.out_airline:
        return None
    return offer


# ── Strategy 2: BeautifulSoup DOM parsing ──────────────────────────────────────

# Known stable data-testid patterns on Skyscanner (verified or likely)
# These may need adjustment after first successful page capture.
_CARD_SELECTORS = [
    {"data-testid": "itinerary-card-wrapper"},
    {"data-testid": "HitItem"},
    {"data-testid": "flight-card"},
    {"data-testid": "FlightCard"},
]

# CSS class patterns that appear in Backpack components (hash suffix varies)
_CARD_CLASS_PATTERNS = [
    re.compile(r"FlightCard"),
    re.compile(r"ItineraryCard"),
    re.compile(r"HitItem"),
    re.compile(r"ResultItem"),
]


def _find_cards(soup: BeautifulSoup) -> list:
    """Try multiple strategies to find flight result cards."""
    # Try data-testid selectors
    for attrs in _CARD_SELECTORS:
        cards = soup.find_all(attrs=attrs)
        if cards:
            logger.debug("Found %d cards via data-testid=%s", len(cards), attrs.get("data-testid"))
            return cards

    # Try class name patterns
    for pattern in _CARD_CLASS_PATTERNS:
        cards = soup.find_all(lambda tag: tag.name in {"div", "article", "li"} and
                              tag.get("class") and
                              any(pattern.search(c) for c in tag["class"]))
        if cards:
            logger.debug("Found %d cards via class pattern %s", len(cards), pattern.pattern)
            return cards

    # Last resort: find any div with a price-looking span inside
    price_containers = []
    for tag in soup.find_all(["div", "article"]):
        text = tag.get_text()
        if re.search(r"\$\s*[\d.]{3,}", text) and len(text) < 2000:
            price_containers.append(tag)

    if price_containers:
        logger.debug("Found %d price-containing containers (last resort)", len(price_containers))

    return price_containers


def _extract_text(element, *selectors) -> str:
    """Try multiple CSS selectors and return first non-empty text."""
    if element is None:
        return ""
    for sel in selectors:
        found = element.select_one(sel)
        if found:
            return found.get_text(strip=True)
    return ""


def _extract_attr(element, attr, *selectors) -> str:
    if element is None:
        return ""
    for sel in selectors:
        found = element.select_one(sel)
        if found and found.get(attr):
            return found[attr]
    return ""


def _parse_dom_card(card, outbound_date: str, return_date: str) -> Optional[FlightOffer]:
    """
    Parse a single flight card from the DOM.
    Uses multiple fallback selectors since Skyscanner CSS class names change on deploy.
    """
    offer = FlightOffer(outbound_date=outbound_date, return_date=return_date)
    card_text = card.get_text(separator=" ", strip=True)

    # ── Price ──────────────────────────────────────────────────────────────
    price_raw = ""
    for price_sel in [
        "[data-testid='price-for-whole-trip-label']",
        "[data-testid='price']",
        "[class*='Price'] span",
        "[class*='price'] span",
        "span[class*='Amount']",
    ]:
        found = card.select_one(price_sel)
        if found:
            price_raw = found.get_text(strip=True)
            break
    if not price_raw:
        # Try to extract first $ pattern from card text
        m = re.search(r"\$\s*[\d.,]+", card_text)
        if m:
            price_raw = m.group(0)
    offer.price_raw = price_raw
    offer.price_total = _parse_price(price_raw)

    # ── Airlines ───────────────────────────────────────────────────────────
    airline_els = card.select("[data-testid='airline-name'], [class*='Carrier'] span, [class*='carrier'] span, [class*='airline'] span")
    airline_names = [el.get_text(strip=True) for el in airline_els if el.get_text(strip=True)]
    if airline_names:
        offer.out_airline = airline_names[0]
        offer.ret_airline = airline_names[1] if len(airline_names) > 1 else airline_names[0]
        offer.out_airlines_all = list(dict.fromkeys(airline_names[:len(airline_names)//2 + 1]))
        offer.ret_airlines_all = list(dict.fromkeys(airline_names[len(airline_names)//2:]))

    # ── Times and airports ─────────────────────────────────────────────────
    # Each leg (outbound + return) typically has: depart_time, arrive_time, airport codes
    time_els = card.select(
        "[data-testid='departure-time'], [data-testid='arrival-time'],"
        " [class*='LegTime'], [class*='time'], time"
    )
    times = [el.get_text(strip=True) for el in time_els if re.match(r"\d{1,2}:\d{2}", el.get_text(strip=True))]

    airport_els = card.select(
        "[data-testid='origin'], [data-testid='destination'],"
        " [class*='Airport'], [class*='airport']"
    )
    airports = [el.get_text(strip=True) for el in airport_els if re.match(r"^[A-Z]{3}$", el.get_text(strip=True))]

    if len(times) >= 2:
        offer.out_depart_time = times[0]
        offer.out_arrive_time = times[1]
    if len(times) >= 4:
        offer.ret_depart_time = times[2]
        offer.ret_arrive_time = times[3]

    if len(airports) >= 2:
        offer.out_origin = airports[0]
        offer.out_destination = airports[1]
    if len(airports) >= 4:
        offer.ret_origin = airports[2]
        offer.ret_destination = airports[3]

    # ── Duration ───────────────────────────────────────────────────────────
    duration_els = card.select(
        "[data-testid='travel-time'], [data-testid='duration'],"
        " [class*='Duration'], [class*='duration']"
    )
    durations = [el.get_text(strip=True) for el in duration_els if re.search(r"\d+\s*h", el.get_text(strip=True))]
    if durations:
        offer.out_duration = durations[0]
        offer.ret_duration = durations[1] if len(durations) > 1 else ""
    else:
        # Extract from raw text
        found = re.findall(r"\d+\s*h\s*\d*\s*m(?:in)?", card_text)
        if found:
            offer.out_duration = found[0]
            offer.ret_duration = found[1] if len(found) > 1 else ""

    # ── Stops ──────────────────────────────────────────────────────────────
    stops_els = card.select(
        "[data-testid='stops-label'], [data-testid='stop-count'],"
        " [class*='Stop'], [class*='stop']"
    )
    stops_texts = [el.get_text(strip=True) for el in stops_els if el.get_text(strip=True)]
    if stops_texts:
        offer.out_stops = _parse_stops(stops_texts[0])
        offer.ret_stops = _parse_stops(stops_texts[1]) if len(stops_texts) > 1 else offer.out_stops
    else:
        # Try extracting from text
        m = re.search(r"(directo|\d+\s*esc)", card_text, re.IGNORECASE)
        if m:
            offer.out_stops = _parse_stops(m.group(1))

    # ── Tags (recommended / cheapest / fastest) ────────────────────────────
    card_lower = card_text.lower()
    offer.is_recommended = "recomendad" in card_lower
    offer.is_cheapest = "más barato" in card_lower or "mas barato" in card_lower
    offer.is_fastest = "más rápido" in card_lower or "mas rapido" in card_lower

    # ── CO2 ────────────────────────────────────────────────────────────────
    co2_el = card.select_one("[class*='co2'], [class*='Co2'], [data-testid*='co2']")
    if co2_el:
        offer.co2_note = co2_el.get_text(strip=True)

    # ── Provider ───────────────────────────────────────────────────────────
    provider_el = card.select_one(
        "[data-testid='provider-name'], [class*='Provider'], [class*='provider']"
    )
    if provider_el:
        offer.provider = provider_el.get_text(strip=True)

    if offer.price_total is None:
        return None
    return offer


def _parse_dom(html: str, outbound_date: str, return_date: str) -> list[FlightOffer]:
    soup = BeautifulSoup(html, "lxml")
    cards = _find_cards(soup)
    if not cards:
        logger.warning("DOM parsing: no flight cards found")
        return []

    logger.info("DOM parsing: found %d cards", len(cards))
    offers = []
    for card in cards:
        try:
            offer = _parse_dom_card(card, outbound_date, return_date)
            if offer:
                offers.append(offer)
        except Exception as e:
            logger.debug("Error parsing DOM card: %s", e)
    return offers


# ── Public entry point ─────────────────────────────────────────────────────────

def parse_skyscanner_page(html: str, outbound_date: str, return_date: str) -> list[FlightOffer]:
    """
    Parse Skyscanner search results from raw HTML.
    Returns a list of FlightOffer objects (may be empty if page is a captcha/error).
    """
    if len(html) < 15_000 and ("captcha" in html.lower() or "robot" in html.lower()):
        logger.warning("Page appears to be a captcha challenge — skipping")
        return []

    # Strategy 1: JSON blob
    blob = _extract_json_blob(html)
    if blob:
        offers = _offers_from_json(blob, outbound_date, return_date)
        if offers:
            logger.info("Parsed %d offers via JSON blob", len(offers))
            return offers
        logger.debug("JSON blob found but no offers extracted — falling back to DOM")

    # Strategy 2: DOM
    offers = _parse_dom(html, outbound_date, return_date)
    logger.info("Parsed %d offers via DOM", len(offers))
    return offers


def is_captcha_page(html: str) -> bool:
    """Return True if the page is a PerimeterX/bot challenge."""
    return len(html) < 20_000 and (
        ("captcha" in html.lower() and "robot" in html.lower()) or
        "px-cloud.net" in html or
        "PerimeterX" in html
    )
