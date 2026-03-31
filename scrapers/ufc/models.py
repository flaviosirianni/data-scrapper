"""
Data models for UFC stats scraper.
All models serialize to plain dicts for JSON output.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class StrikeStat:
    landed: Optional[int] = None
    attempted: Optional[int] = None

    def to_dict(self):
        return {"landed": self.landed, "attempted": self.attempted}


@dataclass
class FighterStats:
    """Stats for one fighter in one period (total or single round)."""
    kd: Optional[int] = None
    # Totals section
    sig_str: StrikeStat = field(default_factory=StrikeStat)
    sig_str_pct: Optional[float] = None
    total_str: StrikeStat = field(default_factory=StrikeStat)
    td: StrikeStat = field(default_factory=StrikeStat)
    td_pct: Optional[float] = None
    sub_att: Optional[int] = None
    rev: Optional[int] = None
    ctrl: Optional[str] = None
    # Significant strikes breakdown
    head: StrikeStat = field(default_factory=StrikeStat)
    body: StrikeStat = field(default_factory=StrikeStat)
    leg: StrikeStat = field(default_factory=StrikeStat)
    distance: StrikeStat = field(default_factory=StrikeStat)
    clinch: StrikeStat = field(default_factory=StrikeStat)
    ground: StrikeStat = field(default_factory=StrikeStat)

    def to_dict(self):
        return {
            "kd": self.kd,
            "sig_str": self.sig_str.to_dict(),
            "sig_str_pct": self.sig_str_pct,
            "total_str": self.total_str.to_dict(),
            "td": self.td.to_dict(),
            "td_pct": self.td_pct,
            "sub_att": self.sub_att,
            "rev": self.rev,
            "ctrl": self.ctrl,
            "head": self.head.to_dict(),
            "body": self.body.to_dict(),
            "leg": self.leg.to_dict(),
            "distance": self.distance.to_dict(),
            "clinch": self.clinch.to_dict(),
            "ground": self.ground.to_dict(),
        }


@dataclass
class RoundStats:
    round_number: int = 0
    fighter_1: FighterStats = field(default_factory=FighterStats)
    fighter_2: FighterStats = field(default_factory=FighterStats)

    def to_dict(self):
        return {
            "round": self.round_number,
            "fighter_1": self.fighter_1.to_dict(),
            "fighter_2": self.fighter_2.to_dict(),
        }


@dataclass
class FightRecord:
    """Complete fight record — one entry in fights.json."""
    # Event context
    event_id: str = ""
    event_name: str = ""
    event_date: str = ""
    event_location: str = ""
    # Fight identity
    fight_id: str = ""
    # Fighters
    fighter_1_name: str = ""
    fighter_1_result: str = ""  # W / L / D / NC
    fighter_2_name: str = ""
    fighter_2_result: str = ""
    # Fight metadata
    weight_class: str = ""
    method: str = ""
    method_detail: str = ""
    round: Optional[int] = None
    time: str = ""
    time_format: str = ""
    referee: str = ""
    details: str = ""
    bonuses: list = field(default_factory=list)
    # Totals
    fighter_1_totals: FighterStats = field(default_factory=FighterStats)
    fighter_2_totals: FighterStats = field(default_factory=FighterStats)
    # Per-round breakdown
    rounds: list = field(default_factory=list)

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_name": self.event_name,
            "event_date": self.event_date,
            "event_location": self.event_location,
            "fight_id": self.fight_id,
            "fighter_1_name": self.fighter_1_name,
            "fighter_1_result": self.fighter_1_result,
            "fighter_2_name": self.fighter_2_name,
            "fighter_2_result": self.fighter_2_result,
            "weight_class": self.weight_class,
            "method": self.method,
            "method_detail": self.method_detail,
            "round": self.round,
            "time": self.time,
            "time_format": self.time_format,
            "referee": self.referee,
            "details": self.details,
            "bonuses": self.bonuses,
            "fighter_1_totals": self.fighter_1_totals.to_dict(),
            "fighter_2_totals": self.fighter_2_totals.to_dict(),
            "rounds": [r.to_dict() for r in self.rounds],
        }
