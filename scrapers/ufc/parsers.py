"""
HTML parsers for ufcstats.com pages.

Three parsers:
  - parse_events_page: /statistics/events/completed  →  list of event dicts
  - parse_event_page:  /event-details/{id}           →  list of fight stub dicts
  - parse_fight_page:  /fight-details/{id}           →  FightRecord

HTML conventions observed on ufcstats.com:
  - BEM class names: b-<section>__<element>
  - Stats cells hold TWO <p class="b-fight-details__table-text"> tags per fighter
  - Summary tables: plain <table> (no class), one <tbody> with one <tr>
  - Per-round tables: class="b-fight-details__table js-fight-table",
    with <thead>Round N</thead><tbody>...</tbody> pairs for each round
"""
import re
import logging
from bs4 import BeautifulSoup, Tag

from .models import FightRecord, FighterStats, RoundStats, StrikeStat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BONUS_MAP = {"perf": "PERF", "fight": "FIGHT", "sub": "SUB", "ko": "KO"}

def _bonus_from_img(img_tag: Tag) -> str | None:
    """Extract bonus type from image src filename (alt text is always empty)."""
    src = img_tag.get("src", "").lower()
    fname = src.rstrip("/").split("/")[-1].replace(".png", "")
    return _BONUS_MAP.get(fname)


def _parse_of(text: str) -> StrikeStat:
    """Parse 'X of Y' format into StrikeStat. Also handles plain integers."""
    text = text.strip()
    m = re.match(r"(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
    if m:
        return StrikeStat(landed=int(m.group(1)), attempted=int(m.group(2)))
    try:
        return StrikeStat(landed=int(text), attempted=None)
    except ValueError:
        return StrikeStat()


def _parse_pct(text: str) -> float | None:
    text = text.strip().rstrip("%").strip()
    if text in ("---", "", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        return None


def _cell_values(cell: Tag) -> tuple[str, str]:
    """
    Extract the two per-fighter values from a stats <td>.
    Each cell holds two <p class="b-fight-details__table-text"> elements,
    one per fighter.
    """
    ps = cell.find_all("p", class_="b-fight-details__table-text")
    v1 = ps[0].get_text(strip=True) if len(ps) > 0 else ""
    v2 = ps[1].get_text(strip=True) if len(ps) > 1 else ""
    return v1, v2


def _parse_row_into_stats(row: Tag) -> tuple[FighterStats, FighterStats]:
    """
    Parse one <tr> from a stats table into (fighter_1_stats, fighter_2_stats).
    Column layout for totals rows:
      0: Fighter name  1: KD  2: Sig.str  3: Sig.str%  4: Total str
      5: TD            6: TD%  7: Sub.att  8: Rev.      9: Ctrl
    Column layout for sig strikes rows:
      0: Fighter name  1: Sig.str  2: Sig.str%  3: Head  4: Body
      5: Leg           6: Distance  7: Clinch    8: Ground
    This function returns stats with only the fields that map to known positions.
    The caller (parse_fight_page) decides which layout applies.
    """
    cells = row.find_all("td")
    vals: list[tuple[str, str]] = [_cell_values(c) for c in cells]
    return vals


# ---------------------------------------------------------------------------
# Events page parser
# ---------------------------------------------------------------------------

def parse_events_page(html: str) -> list[dict]:
    """
    Parse /statistics/events/completed.
    Returns list of: {event_id, event_name, event_date, event_location}
    """
    soup = BeautifulSoup(html, "lxml")
    events = []
    seen = set()

    for a in soup.find_all("a", href=re.compile(r"/event-details/", re.I)):
        href = a.get("href", "")
        event_id = href.rstrip("/").split("/")[-1]
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)

        event_name = a.get_text(strip=True)
        row = a.find_parent("tr")
        event_date = ""
        event_location = ""

        if row:
            cells = row.find_all("td")
            if cells:
                # Date is in a <span> inside the first cell, after the link
                spans = cells[0].find_all("span")
                if spans:
                    event_date = spans[0].get_text(strip=True)
                else:
                    raw = cells[0].get_text(separator="\n", strip=True)
                    lines = [l for l in raw.split("\n") if l and l != event_name]
                    if lines:
                        event_date = lines[0]
            if len(cells) >= 2:
                event_location = cells[1].get_text(strip=True)

        events.append({
            "event_id": event_id,
            "event_name": event_name,
            "event_date": event_date,
            "event_location": event_location,
        })

    logger.info("Parsed %d events from events page", len(events))
    return events


# ---------------------------------------------------------------------------
# Event detail page parser
# ---------------------------------------------------------------------------

def parse_event_page(html: str) -> list[dict]:
    """
    Parse /event-details/{id}.
    Returns list of fight stubs: {fight_id, fighter_1_name, fighter_1_result,
    fighter_2_name, fighter_2_result, weight_class, method, method_detail,
    round, time, bonuses}
    """
    soup = BeautifulSoup(html, "lxml")
    fights = []
    seen = set()

    tbody = soup.find("tbody")
    if not tbody:
        logger.warning("No <tbody> found in event page")
        return fights

    for row in tbody.find_all("tr", recursive=False):
        # Fight ID from data-link attribute
        data_link = row.get("data-link", "")
        fight_id = data_link.rstrip("/").split("/")[-1] if "/fight-details/" in data_link else None
        if not fight_id or fight_id in seen:
            continue
        seen.add(fight_id)

        cells = row.find_all("td")
        if len(cells) < 8:
            continue

        # Cell 0: result badge (b-flag_style_green = win)
        flag = cells[0].find("a", class_=re.compile(r"b-flag"))
        flag_classes = " ".join(flag.get("class", [])) if flag else ""
        flag_text = flag.get_text(strip=True).lower() if flag else ""
        if "green" in flag_classes or flag_text == "win":
            f1_result, f2_result = "W", "L"
        elif "gray" in flag_classes or flag_text == "loss":
            f1_result, f2_result = "L", "W"
        elif "draw" in flag_classes or flag_text == "draw":
            f1_result, f2_result = "D", "D"
        else:
            f1_result, f2_result = flag_text.upper(), ""

        # Cell 1: fighter names (two <p> tags)
        name_ps = cells[1].find_all("p", class_="b-fight-details__table-text")
        fighter_1 = name_ps[0].get_text(strip=True) if len(name_ps) > 0 else ""
        fighter_2 = name_ps[1].get_text(strip=True) if len(name_ps) > 1 else ""

        # Cell 6: weight class + bonus imgs
        weight_class = ""
        bonuses = []
        if len(cells) > 6:
            wc_cell = cells[6]
            for img in wc_cell.find_all("img"):
                bonus = _bonus_from_img(img)
                if bonus:
                    bonuses.append(bonus)
                img.decompose()
            weight_class = wc_cell.get_text(separator=" ", strip=True)

        # Cell 7: method (two <p> tags: method + detail)
        method, method_detail = "", ""
        if len(cells) > 7:
            method_ps = cells[7].find_all("p", class_="b-fight-details__table-text")
            method = method_ps[0].get_text(strip=True) if len(method_ps) > 0 else ""
            method_detail = method_ps[1].get_text(strip=True) if len(method_ps) > 1 else ""

        # Cell 8: round, Cell 9: time
        round_val = _parse_int(cells[8].get_text(strip=True)) if len(cells) > 8 else None
        time_val = cells[9].get_text(strip=True) if len(cells) > 9 else ""

        fights.append({
            "fight_id": fight_id,
            "fighter_1_name": fighter_1,
            "fighter_1_result": f1_result,
            "fighter_2_name": fighter_2,
            "fighter_2_result": f2_result,
            "weight_class": weight_class,
            "method": method,
            "method_detail": method_detail,
            "round": round_val,
            "time": time_val,
            "bonuses": bonuses,
        })

    logger.info("Parsed %d fights from event page", len(fights))
    return fights


# ---------------------------------------------------------------------------
# Fight detail page parser
# ---------------------------------------------------------------------------

def _extract_summary_stats(table: Tag) -> list[tuple[str, str]]:
    """
    Extract per-column (f1_val, f2_val) pairs from a summary table.
    Summary tables have one <tbody> with one <tr>; each <td> contains
    two <p class="b-fight-details__table-text"> elements.
    """
    tbody = table.find("tbody")
    if not tbody:
        return []
    row = tbody.find("tr")
    if not row:
        return []
    return [_cell_values(td) for td in row.find_all("td")]


def _extract_round_stats(table: Tag) -> dict[int, list[tuple[str, str]]]:
    """
    Extract per-round stats from a per-round table (class js-fight-table).
    Returns {round_number: [(f1_val, f2_val), ...per column...]}
    """
    result: dict[int, list[tuple[str, str]]] = {}
    # The table alternates: <thead>Round N</thead> <tbody><tr>data</tr></tbody>
    # We scan direct children of the table in order
    current_round = None
    for child in table.children:
        if not isinstance(child, Tag):
            continue
        if child.name == "thead":
            text = child.get_text(strip=True)
            m = re.search(r"Round\s+(\d+)", text, re.IGNORECASE)
            if m:
                current_round = int(m.group(1))
        elif child.name == "tbody" and current_round is not None:
            row = child.find("tr")
            if row:
                result[current_round] = [_cell_values(td) for td in row.find_all("td")]
            current_round = None  # reset after consuming
    return result


def _build_fighter_stats_totals(cols: list[tuple[str, str]]) -> tuple[FighterStats, FighterStats]:
    """
    Build FighterStats from totals column values.
    Col layout: 0=name, 1=KD, 2=Sig.str, 3=Sig.str%, 4=Total str,
                5=TD, 6=TD%, 7=Sub.att, 8=Rev, 9=Ctrl
    """
    f1, f2 = FighterStats(), FighterStats()
    if len(cols) > 1:
        f1.kd = _parse_int(cols[1][0]);      f2.kd = _parse_int(cols[1][1])
    if len(cols) > 2:
        f1.sig_str = _parse_of(cols[2][0]);  f2.sig_str = _parse_of(cols[2][1])
    if len(cols) > 3:
        f1.sig_str_pct = _parse_pct(cols[3][0]); f2.sig_str_pct = _parse_pct(cols[3][1])
    if len(cols) > 4:
        f1.total_str = _parse_of(cols[4][0]); f2.total_str = _parse_of(cols[4][1])
    if len(cols) > 5:
        f1.td = _parse_of(cols[5][0]);       f2.td = _parse_of(cols[5][1])
    if len(cols) > 6:
        f1.td_pct = _parse_pct(cols[6][0]);  f2.td_pct = _parse_pct(cols[6][1])
    if len(cols) > 7:
        f1.sub_att = _parse_int(cols[7][0]); f2.sub_att = _parse_int(cols[7][1])
    if len(cols) > 8:
        f1.rev = _parse_int(cols[8][0]);     f2.rev = _parse_int(cols[8][1])
    if len(cols) > 9:
        f1.ctrl = cols[9][0];                f2.ctrl = cols[9][1]
    return f1, f2


def _apply_sig_strikes(f1: FighterStats, f2: FighterStats, cols: list[tuple[str, str]]):
    """
    Overlay significant-strike breakdown onto existing FighterStats objects.
    Col layout: 0=name, 1=Sig.str, 2=Sig.str%, 3=Head, 4=Body,
                5=Leg, 6=Distance, 7=Clinch, 8=Ground
    """
    if len(cols) > 1:
        f1.sig_str = _parse_of(cols[1][0]);       f2.sig_str = _parse_of(cols[1][1])
    if len(cols) > 2:
        f1.sig_str_pct = _parse_pct(cols[2][0]);  f2.sig_str_pct = _parse_pct(cols[2][1])
    if len(cols) > 3:
        f1.head = _parse_of(cols[3][0]);           f2.head = _parse_of(cols[3][1])
    if len(cols) > 4:
        f1.body = _parse_of(cols[4][0]);           f2.body = _parse_of(cols[4][1])
    if len(cols) > 5:
        f1.leg = _parse_of(cols[5][0]);            f2.leg = _parse_of(cols[5][1])
    if len(cols) > 6:
        f1.distance = _parse_of(cols[6][0]);       f2.distance = _parse_of(cols[6][1])
    if len(cols) > 7:
        f1.clinch = _parse_of(cols[7][0]);         f2.clinch = _parse_of(cols[7][1])
    if len(cols) > 8:
        f1.ground = _parse_of(cols[8][0]);         f2.ground = _parse_of(cols[8][1])


def parse_fight_page(html: str) -> FightRecord:
    """
    Parse /fight-details/{id}.
    Returns a FightRecord with all stats populated (event context added by scraper).
    """
    soup = BeautifulSoup(html, "lxml")
    record = FightRecord()

    # --- Fighter names and results ---
    # <div class="b-fight-details__person"> appears exactly twice, one per fighter
    person_divs = [
        t for t in soup.find_all("div")
        if t.get("class") and "b-fight-details__person" in t.get("class", [])
    ]
    for div in person_divs[:2]:
        status_tag = div.find("i", class_=re.compile(r"b-fight-details__person-status"))
        name_tag = div.find("h3", class_="b-fight-details__person-name")
        if not name_tag:
            name_tag = div.find(class_="b-fight-details__person-name")

        result_raw = status_tag.get_text(strip=True).upper() if status_tag else ""
        if result_raw in ("W", "WIN"):
            result = "W"
        elif result_raw in ("L", "LOSS"):
            result = "L"
        elif result_raw in ("D", "DRAW"):
            result = "D"
        elif result_raw in ("NC", "NO CONTEST"):
            result = "NC"
        else:
            result = result_raw

        name = ""
        if name_tag:
            a = name_tag.find("a")
            name = (a or name_tag).get_text(strip=True)

        if not record.fighter_1_name:
            record.fighter_1_name = name
            record.fighter_1_result = result
        else:
            record.fighter_2_name = name
            record.fighter_2_result = result

    # --- Weight class and bonuses ---
    fight_title = soup.find("i", class_="b-fight-details__fight-title")
    if fight_title:
        for img in fight_title.find_all("img"):
            bonus = _bonus_from_img(img)
            if bonus and bonus not in record.bonuses:
                record.bonuses.append(bonus)
            img.decompose()
        title_text = fight_title.get_text(strip=True)
        # "Middleweight Bout" → weight class = "Middleweight"
        record.weight_class = re.sub(r"\s+bout\s*$", "", title_text, flags=re.IGNORECASE).strip()

    # --- Fight metadata (Method, Round, Time, Referee, Details) ---
    content = soup.find(class_="b-fight-details__content")
    if content:
        # First <p>: method, round, time, time format, referee
        for item in content.find_all("i", class_=re.compile(r"b-fight-details__text-item")):
            label_tag = item.find("i", class_="b-fight-details__label")
            label = label_tag.get_text(strip=True).rstrip(":").upper() if label_tag else ""
            # Value: remove the label <i> then get remaining text
            if label_tag:
                label_tag.decompose()
            value = item.get_text(strip=True)

            if label == "METHOD":
                record.method = value
            elif label == "ROUND":
                record.round = _parse_int(value)
            elif label == "TIME":
                record.time = value
            elif label == "TIME FORMAT":
                record.time_format = value
            elif label == "REFEREE":
                record.referee = value

        # Second <p>: details — text after the label <i>
        ps = content.find_all("p", class_="b-fight-details__text")
        if len(ps) >= 2:
            detail_p = ps[1]
            # Remove any nested <i> labels
            for i_tag in detail_p.find_all("i"):
                i_tag.decompose()
            record.details = detail_p.get_text(strip=True)

    # --- Stats tables ---
    # Page has exactly 4 tables:
    #   [0] Summary totals (plain <table>, no class)
    #   [1] Per-round totals (class js-fight-table)
    #   [2] Summary sig strikes (plain <table>, no class)
    #   [3] Per-round sig strikes (class js-fight-table)
    all_tables = soup.find_all("table")
    summary_tables = [t for t in all_tables if "js-fight-table" not in " ".join(t.get("class", []))]
    round_tables = [t for t in all_tables if "js-fight-table" in " ".join(t.get("class", []))]

    # Totals summary
    if len(summary_tables) >= 1:
        cols = _extract_summary_stats(summary_tables[0])
        record.fighter_1_totals, record.fighter_2_totals = _build_fighter_stats_totals(cols)

    # Sig strikes summary (overlays onto totals)
    if len(summary_tables) >= 2:
        sig_cols = _extract_summary_stats(summary_tables[1])
        _apply_sig_strikes(record.fighter_1_totals, record.fighter_2_totals, sig_cols)

    # Per-round data
    totals_by_round: dict[int, list] = {}
    sig_by_round: dict[int, list] = {}

    if len(round_tables) >= 1:
        totals_by_round = _extract_round_stats(round_tables[0])
    if len(round_tables) >= 2:
        sig_by_round = _extract_round_stats(round_tables[1])

    all_rounds = sorted(set(totals_by_round) | set(sig_by_round))
    for rnum in all_rounds:
        f1, f2 = _build_fighter_stats_totals(totals_by_round.get(rnum, []))
        if rnum in sig_by_round:
            _apply_sig_strikes(f1, f2, sig_by_round[rnum])
        record.rounds.append(RoundStats(round_number=rnum, fighter_1=f1, fighter_2=f2))

    logger.info(
        "Parsed fight: %s (%s) vs %s (%s) | %d rounds",
        record.fighter_1_name, record.fighter_1_result,
        record.fighter_2_name, record.fighter_2_result,
        len(record.rounds),
    )
    return record
