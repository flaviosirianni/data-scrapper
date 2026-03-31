"""
HTML parsers for ufcstats.com pages.

Three parsers:
  - parse_events_page: /statistics/events/completed  →  list of event dicts
  - parse_event_page:  /event-details/{id}           →  list of fight link dicts
  - parse_fight_page:  /fight-details/{id}           →  FightRecord (partial — no event context)

ufcstats.com uses server-rendered HTML with class names following the
`b-<section>__<element>` BEM convention.
"""
import re
import logging
from bs4 import BeautifulSoup, Tag

from .models import FightRecord, FighterStats, RoundStats, StrikeStat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(tag) -> str:
    if tag is None:
        return ""
    return tag.get_text(separator=" ", strip=True)


def _parse_of(text: str) -> StrikeStat:
    """Parse 'X of Y' into StrikeStat. Also handles plain integers."""
    text = text.strip()
    m = re.match(r"(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
    if m:
        return StrikeStat(landed=int(m.group(1)), attempted=int(m.group(2)))
    try:
        return StrikeStat(landed=int(text), attempted=None)
    except ValueError:
        return StrikeStat()


def _parse_pct(text: str) -> float | None:
    text = text.strip().rstrip("%")
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


def _cells_text(row: Tag) -> list[str]:
    """Return stripped text of all <td> or <th> cells in a row."""
    return [c.get_text(separator=" ", strip=True) for c in row.find_all(["td", "th"])]


def _two_line_cell(cell: Tag) -> tuple[str, str]:
    """
    Many ufcstats cells contain two values (one per fighter) separated by <br>
    or wrapped in <p> tags. Returns (line1, line2).
    """
    # Try <p> tags first
    ps = cell.find_all("p")
    if len(ps) >= 2:
        return ps[0].get_text(strip=True), ps[1].get_text(strip=True)
    # Fall back to <br> split
    raw = cell.decode_contents()
    parts = re.split(r"<br\s*/?>", raw, flags=re.IGNORECASE)
    if len(parts) >= 2:
        return (
            BeautifulSoup(parts[0], "lxml").get_text(strip=True),
            BeautifulSoup(parts[1], "lxml").get_text(strip=True),
        )
    # Single value — return same for both
    t = cell.get_text(strip=True)
    return t, t


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
                # Date is typically in a <span> inside the first cell
                date_span = cells[0].find("span")
                if date_span:
                    event_date = date_span.get_text(strip=True)
                else:
                    # Try second non-link text node
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
        logger.debug("Found event: %s (%s)", event_name, event_id)

    logger.info("Parsed %d events from events page", len(events))
    return events


# ---------------------------------------------------------------------------
# Event detail page parser
# ---------------------------------------------------------------------------

def parse_event_page(html: str) -> list[dict]:
    """
    Parse /event-details/{id}.
    Returns list of: {fight_id, fighter_1_name, fighter_1_result,
                       fighter_2_name, fighter_2_result,
                       weight_class, method, round, time, bonuses}
    """
    soup = BeautifulSoup(html, "lxml")
    fights = []
    seen = set()

    # ufcstats event pages: table rows have data-link="/fight-details/ID"
    # OR the first fighter name is wrapped in <a href="/fight-details/ID">
    tbody = soup.find("tbody")
    if not tbody:
        logger.warning("No <tbody> found in event page")
        return fights

    rows = tbody.find_all("tr", recursive=False)

    for row in rows:
        fight_id = None

        # Strategy 1: data-link attribute on <tr>
        data_link = row.get("data-link", "")
        if data_link and "/fight-details/" in data_link:
            fight_id = data_link.rstrip("/").split("/")[-1]

        # Strategy 2: <a> tag inside row pointing to fight details
        if not fight_id:
            for a in row.find_all("a", href=re.compile(r"/fight-details/", re.I)):
                fight_id = a.get("href", "").rstrip("/").split("/")[-1]
                break

        if not fight_id or fight_id in seen:
            continue
        seen.add(fight_id)

        cells = row.find_all("td")
        if len(cells) < 8:
            logger.debug("Skipping row with only %d cells", len(cells))
            continue

        # Cell layout (typical ufcstats event table):
        # 0: W/L badges  1: Fighter names  2: KD  3: STR  4: TD  5: SUB
        # 6: Weight Class  7: Method  8: Round  9: Time
        wl_cell = cells[0]
        fighter_cell = cells[1]

        # W/L: two lines
        wl_1, wl_2 = _two_line_cell(wl_cell)
        fighter_1, fighter_2 = _two_line_cell(fighter_cell)

        # Normalize result text (e.g. "win" → "W")
        def norm_result(t: str) -> str:
            t = t.upper().strip()
            if t in ("WIN", "W"):
                return "W"
            if t in ("LOSS", "L"):
                return "L"
            if t in ("DRAW", "D"):
                return "D"
            if t in ("NC", "NO CONTEST"):
                return "NC"
            return t

        # Bonuses: look for <img> alt attributes or spans with bonus class
        bonuses = []
        for img in row.find_all("img"):
            alt = img.get("alt", "").strip()
            if alt:
                bonuses.append(alt)
        for span in row.find_all("span", class_=re.compile(r"bonus|perf|fight|sub|ko", re.I)):
            txt = span.get_text(strip=True)
            if txt:
                bonuses.append(txt)

        weight_class = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        method_raw = cells[7].get_text(separator=" ", strip=True) if len(cells) > 7 else ""
        round_raw = cells[8].get_text(strip=True) if len(cells) > 8 else ""
        time_raw = cells[9].get_text(strip=True) if len(cells) > 9 else ""

        fights.append({
            "fight_id": fight_id,
            "fighter_1_name": fighter_1,
            "fighter_1_result": norm_result(wl_1),
            "fighter_2_name": fighter_2,
            "fighter_2_result": norm_result(wl_2),
            "weight_class": weight_class,
            "method": method_raw,
            "round": _parse_int(round_raw),
            "time": time_raw,
            "bonuses": list(set(bonuses)),
        })
        logger.debug("Found fight: %s vs %s (%s)", fighter_1, fighter_2, fight_id)

    logger.info("Parsed %d fights from event page", len(fights))
    return fights


# ---------------------------------------------------------------------------
# Fight detail page parser
# ---------------------------------------------------------------------------

def _parse_fighter_stats_from_rows(
    totals_rows: list[list[str]],
    sig_rows: list[list[str]],
) -> tuple[FighterStats, FighterStats]:
    """
    Build FighterStats for both fighters from the totals and sig strike row data.

    totals_rows: [[f1_val, f2_val], ...] for each column
    sig_rows:    [[f1_val, f2_val], ...] for each column

    Expected totals columns (after fighter name):
      KD | SIG.STR | SIG.STR% | TOTAL STR | TD | TD% | SUB ATT | REV | CTRL

    Expected sig columns (after fighter name):
      SIG STR | SIG STR% | HEAD | BODY | LEG | DISTANCE | CLINCH | GROUND
    """
    f1 = FighterStats()
    f2 = FighterStats()

    # --- Totals ---
    # totals_rows is indexed by column position
    # Column 0 = fighter name (skip), then per column above
    col = totals_rows  # list of [f1_text, f2_text]
    if len(col) > 1:
        f1.kd = _parse_int(col[1][0]); f2.kd = _parse_int(col[1][1])
    if len(col) > 2:
        f1.sig_str = _parse_of(col[2][0]); f2.sig_str = _parse_of(col[2][1])
    if len(col) > 3:
        f1.sig_str_pct = _parse_pct(col[3][0]); f2.sig_str_pct = _parse_pct(col[3][1])
    if len(col) > 4:
        f1.total_str = _parse_of(col[4][0]); f2.total_str = _parse_of(col[4][1])
    if len(col) > 5:
        f1.td = _parse_of(col[5][0]); f2.td = _parse_of(col[5][1])
    if len(col) > 6:
        f1.td_pct = _parse_pct(col[6][0]); f2.td_pct = _parse_pct(col[6][1])
    if len(col) > 7:
        f1.sub_att = _parse_int(col[7][0]); f2.sub_att = _parse_int(col[7][1])
    if len(col) > 8:
        f1.rev = _parse_int(col[8][0]); f2.rev = _parse_int(col[8][1])
    if len(col) > 9:
        f1.ctrl = col[9][0]; f2.ctrl = col[9][1]

    # --- Significant strikes ---
    scol = sig_rows
    if len(scol) > 1:
        f1.sig_str = _parse_of(scol[1][0]); f2.sig_str = _parse_of(scol[1][1])
    if len(scol) > 2:
        f1.sig_str_pct = _parse_pct(scol[2][0]); f2.sig_str_pct = _parse_pct(scol[2][1])
    if len(scol) > 3:
        f1.head = _parse_of(scol[3][0]); f2.head = _parse_of(scol[3][1])
    if len(scol) > 4:
        f1.body = _parse_of(scol[4][0]); f2.body = _parse_of(scol[4][1])
    if len(scol) > 5:
        f1.leg = _parse_of(scol[5][0]); f2.leg = _parse_of(scol[5][1])
    if len(scol) > 6:
        f1.distance = _parse_of(scol[6][0]); f2.distance = _parse_of(scol[6][1])
    if len(scol) > 7:
        f1.clinch = _parse_of(scol[7][0]); f2.clinch = _parse_of(scol[7][1])
    if len(scol) > 8:
        f1.ground = _parse_of(scol[8][0]); f2.ground = _parse_of(scol[8][1])

    return f1, f2


def _extract_table_columns(table: Tag) -> list[list[str]]:
    """
    Given a two-row data table (one row per fighter), return a list of
    [f1_text, f2_text] per column.

    Handles the ufcstats pattern where each cell may contain two <p> tags
    (one per fighter in a single row) OR there are two separate rows.
    """
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr", recursive=False)

    # Filter out header rows
    data_rows = [r for r in rows if r.find("td")]
    if not data_rows:
        return []

    if len(data_rows) == 1:
        # Single row with two-line cells (one value per fighter per cell)
        cells = data_rows[0].find_all("td")
        result = []
        for cell in cells:
            v1, v2 = _two_line_cell(cell)
            result.append([v1, v2])
        return result
    else:
        # Two rows: first row = fighter 1, second = fighter 2
        cells_1 = data_rows[0].find_all("td")
        cells_2 = data_rows[1].find_all("td")
        result = []
        max_cols = max(len(cells_1), len(cells_2))
        for i in range(max_cols):
            v1 = cells_1[i].get_text(strip=True) if i < len(cells_1) else ""
            v2 = cells_2[i].get_text(strip=True) if i < len(cells_2) else ""
            result.append([v1, v2])
        return result


def _extract_per_round_tables(section: Tag) -> list[tuple[int, list[list[str]]]]:
    """
    Find all per-round sub-tables within a section.
    Returns list of (round_number, columns) tuples.
    """
    rounds = []
    # Round labels are typically in <p> or heading elements saying "Round N"
    # Tables for each round follow
    round_tables = section.find_all("table")
    # The first table is the totals table; subsequent tables are per-round
    # OR they may be siblings outside the table

    # Alternative: look for headings with "Round"
    for heading in section.find_all(re.compile(r"^(p|h[2-6]|th)$"), string=re.compile(r"round\s+\d+", re.I)):
        rnum_match = re.search(r"(\d+)", heading.get_text())
        if not rnum_match:
            continue
        rnum = int(rnum_match.group(1))
        # Find the next table sibling
        nxt = heading.find_next_sibling("table") or heading.find_parent("tr")
        if nxt and nxt.name == "table":
            cols = _extract_table_columns(nxt)
            rounds.append((rnum, cols))

    return rounds


def parse_fight_page(html: str) -> FightRecord:
    """
    Parse /fight-details/{id}.
    Returns a FightRecord with all stats populated (no event context).
    """
    soup = BeautifulSoup(html, "lxml")
    record = FightRecord()

    # --- Fight header ---
    # Fighter names and results
    fighter_sections = soup.find_all(class_=re.compile(r"b-fight-details__person", re.I))
    fighters_parsed = []
    for fs in fighter_sections:
        name_tag = fs.find(class_=re.compile(r"b-fight-details__person-name|b-link", re.I))
        result_tag = fs.find(class_=re.compile(r"b-fight-details__person-status", re.I))
        if not name_tag:
            name_tag = fs.find("a") or fs.find("h3") or fs.find("span")
        name = name_tag.get_text(strip=True) if name_tag else ""
        result_raw = result_tag.get_text(strip=True).upper() if result_tag else ""
        # Normalize
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
        fighters_parsed.append((name, result))

    if len(fighters_parsed) >= 2:
        record.fighter_1_name, record.fighter_1_result = fighters_parsed[0]
        record.fighter_2_name, record.fighter_2_result = fighters_parsed[1]
    elif len(fighters_parsed) == 1:
        record.fighter_1_name, record.fighter_1_result = fighters_parsed[0]

    # --- Fight metadata box ---
    # ufcstats: dl/dt/dd pairs or a table with method, round, time, etc.
    meta_section = (
        soup.find(class_=re.compile(r"b-fight-details__fight", re.I))
        or soup.find(class_=re.compile(r"b-fight-details__content", re.I))
    )
    if meta_section:
        # Try <i> or <span> pairs for label:value
        text_block = meta_section.get_text(separator="\n")
        for line in text_block.split("\n"):
            line = line.strip()
            if line.upper().startswith("METHOD:"):
                record.method = line.split(":", 1)[1].strip()
            elif line.upper().startswith("ROUND:"):
                record.round = _parse_int(line.split(":", 1)[1].strip())
            elif line.upper().startswith("TIME:"):
                record.time = line.split(":", 1)[1].strip()
            elif line.upper().startswith("TIME FORMAT:"):
                record.time_format = line.split(":", 1)[1].strip()
            elif line.upper().startswith("REFEREE:"):
                record.referee = line.split(":", 1)[1].strip()
            elif line.upper().startswith("DETAILS:"):
                record.details = line.split(":", 1)[1].strip()

        # Weight class & bonuses
        wc_tag = meta_section.find(class_=re.compile(r"weight|class|division", re.I))
        if wc_tag:
            record.weight_class = wc_tag.get_text(strip=True)

    # Method detail (e.g. "Punches to Head From Mount")
    detail_tag = soup.find(class_=re.compile(r"b-fight-details__text-item_type_", re.I))
    if not detail_tag:
        # Try to find DETAILS: label
        for i_tag in soup.find_all("i", class_=re.compile(r"b-fight-details", re.I)):
            if "details" in i_tag.get_text(separator=" ", strip=True).lower():
                sibling = i_tag.find_next_sibling() or i_tag.parent
                record.details = (sibling or i_tag).get_text(strip=True)
                break

    # Bonuses from img alt texts or colored labels in page header
    for img in soup.find_all("img"):
        alt = img.get("alt", "").strip()
        if alt and alt not in record.bonuses:
            record.bonuses.append(alt)

    # --- Stats tables ---
    # ufcstats fight detail page has two main sections:
    #   1. TOTALS
    #   2. SIGNIFICANT STRIKES
    # Each has a summary table + per-round tables (expanded in Playwright before fetching HTML)

    sections = soup.find_all("section", class_=re.compile(r"b-fight-details__section", re.I))
    if not sections:
        # Fallback: find all tables
        sections = soup.find_all("table")

    totals_section = None
    sig_section = None

    for sec in sections:
        heading_text = ""
        for hdr in sec.find_all(["h2", "h3", "p", "span"]):
            t = hdr.get_text(strip=True).upper()
            if t:
                heading_text = t
                break
        if "TOTAL" in heading_text:
            totals_section = sec
        elif "SIGNIFICANT" in heading_text or "SIG" in heading_text:
            sig_section = sec

    # If section detection failed, try by table order
    all_tables = soup.find_all("table")
    if not totals_section and len(all_tables) >= 1:
        totals_section = all_tables[0].find_parent("section") or all_tables[0]
    if not sig_section and len(all_tables) >= 2:
        sig_section = all_tables[1].find_parent("section") or all_tables[1]

    # Extract totals
    totals_cols: list[list[str]] = []
    sig_cols: list[list[str]] = []

    if totals_section:
        first_table = totals_section.find("table") if totals_section.name != "table" else totals_section
        if first_table:
            totals_cols = _extract_table_columns(first_table)

    if sig_section:
        first_table = sig_section.find("table") if sig_section.name != "table" else sig_section
        if first_table:
            sig_cols = _extract_table_columns(first_table)

    if totals_cols or sig_cols:
        record.fighter_1_totals, record.fighter_2_totals = _parse_fighter_stats_from_rows(
            totals_cols, sig_cols
        )

    # --- Per-round breakdown ---
    # After Playwright clicks "PER ROUND", the page adds round sub-tables.
    # We find them by looking for round heading elements.
    round_data: dict[int, dict] = {}

    def _get_or_create_round(n: int) -> dict:
        if n not in round_data:
            round_data[n] = {"totals_cols": [], "sig_cols": []}
        return round_data[n]

    # Strategy: find all elements containing "Round N" text, then grab the next table
    for elem in soup.find_all(string=re.compile(r"Round\s+\d+", re.I)):
        parent = elem.find_parent(["p", "th", "h2", "h3", "h4", "span", "div"])
        if not parent:
            continue
        m = re.search(r"Round\s+(\d+)", str(elem), re.I)
        if not m:
            continue
        rnum = int(m.group(1))

        # Find the next table relative to this heading
        nxt_table = parent.find_next("table")
        if not nxt_table:
            continue

        # Determine if this is a totals or sig-strikes round table based on its section
        in_sig = False
        anc = parent
        while anc:
            cls = " ".join(anc.get("class", []))
            txt = anc.get_text(separator=" ", strip=True).upper()
            if "SIGNIFICANT" in txt or "SIG" in cls:
                in_sig = True
                break
            anc = anc.parent

        cols = _extract_table_columns(nxt_table)
        rd = _get_or_create_round(rnum)
        if in_sig:
            rd["sig_cols"] = cols
        else:
            rd["totals_cols"] = cols

    for rnum in sorted(round_data.keys()):
        rd = round_data[rnum]
        f1, f2 = _parse_fighter_stats_from_rows(rd["totals_cols"], rd["sig_cols"])
        record.rounds.append(RoundStats(round_number=rnum, fighter_1=f1, fighter_2=f2))

    logger.info(
        "Parsed fight: %s vs %s | %d rounds of detail",
        record.fighter_1_name,
        record.fighter_2_name,
        len(record.rounds),
    )
    return record
