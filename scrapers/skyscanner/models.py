"""
Data models for the Skyscanner flight price scraper.
All models serialize to plain dicts via .to_dict().
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FlightSegment:
    """One individual flight leg within an itinerary."""
    direction: str = ""        # "outbound" or "return"
    segment_order: int = 0     # 0-based index within direction
    airline: str = ""
    flight_number: str = ""
    origin: str = ""           # IATA airport code
    destination: str = ""
    depart_time: str = ""      # HH:MM
    arrive_time: str = ""      # HH:MM  (may include "+1" for next-day arrivals)
    depart_date: str = ""      # YYYY-MM-DD
    arrive_date: str = ""      # YYYY-MM-DD
    duration: str = ""         # e.g. "2h 45m"

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "segment_order": self.segment_order,
            "airline": self.airline,
            "flight_number": self.flight_number,
            "origin": self.origin,
            "destination": self.destination,
            "depart_time": self.depart_time,
            "arrive_time": self.arrive_time,
            "depart_date": self.depart_date,
            "arrive_date": self.arrive_date,
            "duration": self.duration,
        }


@dataclass
class FlightOffer:
    """
    One flight itinerary (round-trip) returned by a Skyscanner search.
    Outbound + return are summarised at this level; individual legs live
    in the `segments` list for multi-stop itineraries.
    """
    # Injected by scraper after DB insert of scrape_run
    run_id: Optional[int] = None
    scraped_at: str = ""       # ISO-8601 UTC timestamp
    outbound_date: str = ""    # YYYY-MM-DD
    return_date: str = ""      # YYYY-MM-DD

    # ── Price ────────────────────────────────────────────────────────────
    price_total: Optional[float] = None  # numeric, in price_currency units
    price_currency: str = "CLP"
    price_raw: str = ""        # raw string as scraped, e.g. "$ 580.590"

    # ── Outbound leg summary ─────────────────────────────────────────────
    out_airline: str = ""              # primary carrier ("Aerolíneas Argentinas")
    out_airlines_all: list = field(default_factory=list)   # list[str]
    out_origin: str = ""               # IATA
    out_destination: str = ""
    out_depart_time: str = ""          # HH:MM
    out_arrive_time: str = ""
    out_duration: str = ""             # "6h 45m"
    out_stops: Optional[int] = None    # 0 = direct
    out_stopover_codes: list = field(default_factory=list)  # ["LIM", "BOG"]

    # ── Return leg summary ───────────────────────────────────────────────
    ret_airline: str = ""
    ret_airlines_all: list = field(default_factory=list)
    ret_origin: str = ""
    ret_destination: str = ""
    ret_depart_time: str = ""
    ret_arrive_time: str = ""
    ret_duration: str = ""
    ret_stops: Optional[int] = None
    ret_stopover_codes: list = field(default_factory=list)

    # ── Offer metadata ───────────────────────────────────────────────────
    provider: str = ""           # booking provider ("Avianca", "Despegar", ...)
    is_recommended: bool = False
    is_cheapest: bool = False
    is_fastest: bool = False
    co2_grams: Optional[int] = None
    co2_note: str = ""           # e.g. "Este vuelo emite 7% menos CO₂e"

    # ── Individual legs (optional, when page exposes segment detail) ──────
    segments: list = field(default_factory=list)  # list[FlightSegment]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "scraped_at": self.scraped_at,
            "outbound_date": self.outbound_date,
            "return_date": self.return_date,
            "price_total": self.price_total,
            "price_currency": self.price_currency,
            "price_raw": self.price_raw,
            "out_airline": self.out_airline,
            "out_airlines_all": self.out_airlines_all,
            "out_origin": self.out_origin,
            "out_destination": self.out_destination,
            "out_depart_time": self.out_depart_time,
            "out_arrive_time": self.out_arrive_time,
            "out_duration": self.out_duration,
            "out_stops": self.out_stops,
            "out_stopover_codes": self.out_stopover_codes,
            "ret_airline": self.ret_airline,
            "ret_airlines_all": self.ret_airlines_all,
            "ret_origin": self.ret_origin,
            "ret_destination": self.ret_destination,
            "ret_depart_time": self.ret_depart_time,
            "ret_arrive_time": self.ret_arrive_time,
            "ret_duration": self.ret_duration,
            "ret_stops": self.ret_stops,
            "ret_stopover_codes": self.ret_stopover_codes,
            "provider": self.provider,
            "is_recommended": self.is_recommended,
            "is_cheapest": self.is_cheapest,
            "is_fastest": self.is_fastest,
            "co2_grams": self.co2_grams,
            "co2_note": self.co2_note,
            "segments": [s.to_dict() for s in self.segments],
        }
