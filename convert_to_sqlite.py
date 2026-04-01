"""
Convert fights.json (and optionally upcoming.json) to a SQLite database.

Schema:
  fights        — one row per fight, flat stats for totals
  fight_rounds  — one row per fighter per round
  upcoming_fights — upcoming fight cards (names/dates, no stats)

Usage:
  python convert_to_sqlite.py
  python convert_to_sqlite.py --input data/ufc/fights.json --output data/ufc/ufc.db
"""
import json
import sqlite3
import argparse
from pathlib import Path
from typing import Optional


FIGHTS_JSON   = Path("data/ufc/fights.json")
UPCOMING_JSON = Path("data/ufc/upcoming.json")
SQLITE_DB     = Path("data/ufc/ufc.db")


CREATE_FIGHTS = """
CREATE TABLE IF NOT EXISTS fights (
    fight_id            TEXT PRIMARY KEY,
    event_id            TEXT,
    event_name          TEXT,
    event_date          TEXT,
    event_location      TEXT,
    fighter_1_name      TEXT,
    fighter_1_result    TEXT,
    fighter_2_name      TEXT,
    fighter_2_result    TEXT,
    weight_class        TEXT,
    method              TEXT,
    method_detail       TEXT,
    round               INTEGER,
    time                TEXT,
    time_format         TEXT,
    referee             TEXT,
    details             TEXT,
    bonuses             TEXT,       -- JSON array, e.g. ["PERF","KO"]
    -- Fighter 1 totals
    f1_kd               INTEGER,
    f1_sig_str_landed   INTEGER,
    f1_sig_str_att      INTEGER,
    f1_sig_str_pct      REAL,
    f1_total_str_landed INTEGER,
    f1_total_str_att    INTEGER,
    f1_td_landed        INTEGER,
    f1_td_att           INTEGER,
    f1_td_pct           REAL,
    f1_sub_att          INTEGER,
    f1_rev              INTEGER,
    f1_ctrl             TEXT,
    f1_head_landed      INTEGER,
    f1_head_att         INTEGER,
    f1_body_landed      INTEGER,
    f1_body_att         INTEGER,
    f1_leg_landed       INTEGER,
    f1_leg_att          INTEGER,
    f1_distance_landed  INTEGER,
    f1_distance_att     INTEGER,
    f1_clinch_landed    INTEGER,
    f1_clinch_att       INTEGER,
    f1_ground_landed    INTEGER,
    f1_ground_att       INTEGER,
    -- Fighter 2 totals
    f2_kd               INTEGER,
    f2_sig_str_landed   INTEGER,
    f2_sig_str_att      INTEGER,
    f2_sig_str_pct      REAL,
    f2_total_str_landed INTEGER,
    f2_total_str_att    INTEGER,
    f2_td_landed        INTEGER,
    f2_td_att           INTEGER,
    f2_td_pct           REAL,
    f2_sub_att          INTEGER,
    f2_rev              INTEGER,
    f2_ctrl             TEXT,
    f2_head_landed      INTEGER,
    f2_head_att         INTEGER,
    f2_body_landed      INTEGER,
    f2_body_att         INTEGER,
    f2_leg_landed       INTEGER,
    f2_leg_att          INTEGER,
    f2_distance_landed  INTEGER,
    f2_distance_att     INTEGER,
    f2_clinch_landed    INTEGER,
    f2_clinch_att       INTEGER,
    f2_ground_landed    INTEGER,
    f2_ground_att       INTEGER
)
"""

CREATE_ROUNDS = """
CREATE TABLE IF NOT EXISTS fight_rounds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id            TEXT REFERENCES fights(fight_id),
    round               INTEGER,
    fighter             INTEGER,    -- 1 or 2
    fighter_name        TEXT,
    kd                  INTEGER,
    sig_str_landed      INTEGER,
    sig_str_att         INTEGER,
    sig_str_pct         REAL,
    total_str_landed    INTEGER,
    total_str_att       INTEGER,
    td_landed           INTEGER,
    td_att              INTEGER,
    td_pct              REAL,
    sub_att             INTEGER,
    rev                 INTEGER,
    ctrl                TEXT,
    head_landed         INTEGER,
    head_att            INTEGER,
    body_landed         INTEGER,
    body_att            INTEGER,
    leg_landed          INTEGER,
    leg_att             INTEGER,
    distance_landed     INTEGER,
    distance_att        INTEGER,
    clinch_landed       INTEGER,
    clinch_att          INTEGER,
    ground_landed       INTEGER,
    ground_att          INTEGER
)
"""

CREATE_UPCOMING = """
CREATE TABLE IF NOT EXISTS upcoming_fights (
    fight_id        TEXT PRIMARY KEY,
    event_id        TEXT,
    event_name      TEXT,
    event_date      TEXT,
    event_location  TEXT,
    card_order      INTEGER,
    fighter_1_name  TEXT,
    fighter_2_name  TEXT,
    weight_class    TEXT
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_fights_event_id      ON fights(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_fights_event_date    ON fights(event_date)",
    "CREATE INDEX IF NOT EXISTS idx_fights_f1_name       ON fights(fighter_1_name)",
    "CREATE INDEX IF NOT EXISTS idx_fights_f2_name       ON fights(fighter_2_name)",
    "CREATE INDEX IF NOT EXISTS idx_fights_weight_class  ON fights(weight_class)",
    "CREATE INDEX IF NOT EXISTS idx_fights_method        ON fights(method)",
    "CREATE INDEX IF NOT EXISTS idx_rounds_fight_id      ON fight_rounds(fight_id)",
    "CREATE INDEX IF NOT EXISTS idx_rounds_fighter_name  ON fight_rounds(fighter_name)",
    "CREATE INDEX IF NOT EXISTS idx_upcoming_event_id    ON upcoming_fights(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_upcoming_event_date  ON upcoming_fights(event_date)",
    "CREATE INDEX IF NOT EXISTS idx_upcoming_f1_name     ON upcoming_fights(fighter_1_name)",
    "CREATE INDEX IF NOT EXISTS idx_upcoming_f2_name     ON upcoming_fights(fighter_2_name)",
]


def _s(stat: dict, key: str):
    """Safe stat extraction from a strike dict."""
    return stat.get(key) if stat else None


def _flatten_fighter(t: dict) -> tuple:
    """Return flat tuple of all fighter totals in column order."""
    return (
        t.get("kd"),
        _s(t.get("sig_str"), "landed"),
        _s(t.get("sig_str"), "attempted"),
        t.get("sig_str_pct"),
        _s(t.get("total_str"), "landed"),
        _s(t.get("total_str"), "attempted"),
        _s(t.get("td"), "landed"),
        _s(t.get("td"), "attempted"),
        t.get("td_pct"),
        t.get("sub_att"),
        t.get("rev"),
        t.get("ctrl"),
        _s(t.get("head"), "landed"),
        _s(t.get("head"), "attempted"),
        _s(t.get("body"), "landed"),
        _s(t.get("body"), "attempted"),
        _s(t.get("leg"), "landed"),
        _s(t.get("leg"), "attempted"),
        _s(t.get("distance"), "landed"),
        _s(t.get("distance"), "attempted"),
        _s(t.get("clinch"), "landed"),
        _s(t.get("clinch"), "attempted"),
        _s(t.get("ground"), "landed"),
        _s(t.get("ground"), "attempted"),
    )


def convert(input_path: Path, output_path: Path, upcoming_path: Optional[Path] = None):
    print(f"Reading {input_path} ...")
    fights = json.loads(input_path.read_text())
    print(f"  {len(fights)} fights loaded")

    output_path.unlink(missing_ok=True)
    con = sqlite3.connect(output_path)
    cur = con.cursor()

    cur.execute(CREATE_FIGHTS)
    cur.execute(CREATE_ROUNDS)
    cur.execute(CREATE_UPCOMING)
    for stmt in CREATE_INDEXES:
        cur.execute(stmt)

    fight_rows = []
    round_rows = []

    for f in fights:
        f1t = f.get("fighter_1_totals", {})
        f2t = f.get("fighter_2_totals", {})

        fight_rows.append((
            f["fight_id"],
            f.get("event_id"),
            f.get("event_name"),
            f.get("event_date"),
            f.get("event_location"),
            f.get("fighter_1_name"),
            f.get("fighter_1_result"),
            f.get("fighter_2_name"),
            f.get("fighter_2_result"),
            f.get("weight_class"),
            f.get("method"),
            f.get("method_detail"),
            f.get("round"),
            f.get("time"),
            f.get("time_format"),
            f.get("referee"),
            f.get("details"),
            json.dumps(f.get("bonuses", [])),
            *_flatten_fighter(f1t),
            *_flatten_fighter(f2t),
        ))

        for rnd in f.get("rounds", []):
            for fighter_num, fighter_key, name_key in [
                (1, "fighter_1", "fighter_1_name"),
                (2, "fighter_2", "fighter_2_name"),
            ]:
                s = rnd.get(fighter_key, {})
                round_rows.append((
                    f["fight_id"],
                    rnd["round"],
                    fighter_num,
                    f.get(name_key),
                    s.get("kd"),
                    _s(s.get("sig_str"), "landed"),
                    _s(s.get("sig_str"), "attempted"),
                    s.get("sig_str_pct"),
                    _s(s.get("total_str"), "landed"),
                    _s(s.get("total_str"), "attempted"),
                    _s(s.get("td"), "landed"),
                    _s(s.get("td"), "attempted"),
                    s.get("td_pct"),
                    s.get("sub_att"),
                    s.get("rev"),
                    s.get("ctrl"),
                    _s(s.get("head"), "landed"),
                    _s(s.get("head"), "attempted"),
                    _s(s.get("body"), "landed"),
                    _s(s.get("body"), "attempted"),
                    _s(s.get("leg"), "landed"),
                    _s(s.get("leg"), "attempted"),
                    _s(s.get("distance"), "landed"),
                    _s(s.get("distance"), "attempted"),
                    _s(s.get("clinch"), "landed"),
                    _s(s.get("clinch"), "attempted"),
                    _s(s.get("ground"), "landed"),
                    _s(s.get("ground"), "attempted"),
                ))

    n_fights = len(fight_rows[0]) if fight_rows else 0
    n_rounds = len(round_rows[0]) if round_rows else 0
    cur.executemany(
        f"INSERT INTO fights VALUES ({','.join(['?']*n_fights)})", fight_rows
    )
    cur.executemany(
        f"INSERT INTO fight_rounds VALUES (NULL,{','.join(['?']*n_rounds)})", round_rows
    )

    # --- upcoming_fights ---
    upcoming_rows = []
    resolved_upcoming = upcoming_path if upcoming_path else UPCOMING_JSON
    if resolved_upcoming.exists():
        upcoming = json.loads(resolved_upcoming.read_text())
        for u in upcoming:
            upcoming_rows.append((
                u["fight_id"],
                u.get("event_id"),
                u.get("event_name"),
                u.get("event_date"),
                u.get("event_location"),
                u.get("card_order"),
                u.get("fighter_1_name"),
                u.get("fighter_2_name"),
                u.get("weight_class"),
            ))
        if upcoming_rows:
            cur.executemany(
                "INSERT OR REPLACE INTO upcoming_fights VALUES (?,?,?,?,?,?,?,?,?)",
                upcoming_rows,
            )
        print(f"  {len(upcoming_rows)} upcoming fight(s) → upcoming_fights table")
    else:
        print(f"  No upcoming.json found — upcoming_fights table empty")

    con.commit()
    con.close()

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"  {len(fight_rows)} fights → fights table")
    print(f"  {len(round_rows)} round-fighter rows → fight_rounds table")
    print(f"  Saved to {output_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",    default=str(FIGHTS_JSON))
    parser.add_argument("--output",   default=str(SQLITE_DB))
    parser.add_argument("--upcoming", default=None, help="Path to upcoming.json (default: data/ufc/upcoming.json)")
    args = parser.parse_args()
    convert(Path(args.input), Path(args.output), Path(args.upcoming) if args.upcoming else None)
