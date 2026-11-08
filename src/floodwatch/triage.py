"""
Misinformation Triage Engine (triage.py)
========================================
Owner: Person 1 (Qamran)
Deterministic verification of citizen flood reports against model status and official advisories.
Strictly rules-based (no LLM, no external network calls).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

from floodwatch.verify import normalize_numerals


class Verdict(str, Enum):
    SUPPORTED = "supported_by_advisory"
    CONSISTENT = "consistent_with_conditions"
    NO_SIGNAL = "no_signal_found"
    CANNOT_ASSESS = "cannot_assess"


@dataclass(frozen=True)
class Advisory:
    source: str
    title: str
    url: str
    areas: frozenset[str]
    issued_at: datetime | None = None


@dataclass(frozen=True)
class TriageResult:
    verdict: Verdict
    evidence: list[str]
    matched_basins: list[str]
    extracted_date: date | None = None
    level: str | None = None
    truncated: bool = False


# Banned words across all evidence strings (Issue 8 invariant)
BANNED_WORDS = [
    "fake", "false", "hoax", "untrue", "debunked",
    "not real", "did not happen", "never happened"
]

FLOOD_KEYWORDS = [
    "flood", "flash flood", "deluge", "water level", "river", "inundation",
    "سیلاب", "پانی", "طغیانی", "سیلابی ریلہ"
]


def load_aliases(path: Path | str = "data/static/basin_aliases.json") -> dict[str, str]:
    """Loads alias to basin_id dictionary."""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("aliases", {})


def load_advisories(path: Path | str = "data/advisories.json") -> list[Advisory]:
    """Loads active official advisories."""
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    advisories = []
    for raw in data.get("advisories", []):
        dt = None
        if raw.get("issued_at"):
            try:
                dt = datetime.fromisoformat(raw["issued_at"].replace("Z", "+00:00"))
            except ValueError:
                pass
        advisories.append(Advisory(
            source=raw.get("source", ""),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            areas=frozenset(raw.get("areas", [])),
            issued_at=dt
        ))
    return advisories


def extract_dates(text: str, now: datetime | None = None) -> list[date]:
    """
    Extracts dates handling Pakistan convention (dd/mm/yyyy), English text,
    Urdu digits, and bare historical years.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    current_year = now.year

    norm_text = normalize_numerals(text)
    dates_found: list[date] = []

    # 1. Numeric dates: dd/mm/yyyy (D-02 convention)
    numeric_pattern = r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"
    for match in re.finditer(numeric_pattern, norm_text):
        p1, p2, yr = int(match.group(1)), int(match.group(2)), int(match.group(3))
        # Pakistan convention: try dd/mm/yyyy first
        try:
            d = date(yr, p2, p1)
            if d <= now.date():
                dates_found.append(d)
                continue
        except ValueError:
            pass

        # Try mm/dd/yyyy if dd/mm was future or invalid
        try:
            d = date(yr, p1, p2)
            if d <= now.date():
                dates_found.append(d)
        except ValueError:
            pass

    # 2. Text dates (e.g., August 2022, اگست ۲۰۲۲)
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "جنوری": 1, "فروری": 2, "مارچ": 3, "اپریل": 4, "مئی": 5, "جون": 6,
        "جولائی": 7, "اگست": 8, "ستمبر": 9, "اکتوبر": 10, "نومبر": 11, "دسمبر": 12
    }
    month_regex = "|".join(months.keys())
    text_date_pattern = rf"\b({month_regex})\s+(\d{{4}})\b"
    for match in re.finditer(text_date_pattern, norm_text, re.IGNORECASE):
        m_name = match.group(1).lower()
        yr = int(match.group(2))
        m_num = months.get(m_name, 1)
        try:
            d = date(yr, m_num, 1)
            if d <= now.date():
                dates_found.append(d)
        except ValueError:
            pass

    # 3. Bare historical years in proximity to flood keywords (§6.5)
    bare_year_pattern = r"\b(20[0-2][0-9])\b"
    for match in re.finditer(bare_year_pattern, norm_text):
        yr = int(match.group(1))
        # Ignore current year as a downgrade signal
        if yr >= current_year:
            continue
        # Ignore phrases like "since 2010"
        start_pos = max(0, match.start() - 20)
        prefix = norm_text[start_pos:match.start()].lower()
        if any(w in prefix for w in ["since", "from", "in the season of"]):
            continue

        # Must be within 40 characters of a flood word
        window_start = max(0, match.start() - 40)
        window_end = min(len(norm_text), match.end() + 40)
        surrounding = norm_text[window_start:window_end].lower()
        if any(kw in surrounding for kw in FLOOD_KEYWORDS):
            dates_found.append(date(yr, 8, 1))

    return sorted(dates_found, reverse=True)


def triage(
    text: str,
    *,
    aliases: dict[str, str] | None = None,
    levels: dict[str, str] | None = None,
    advisories: list[Advisory] | tuple[()] = (),
    now: datetime | None = None,
    max_advisory_age_h: float = 48.0,
    stale_days: float = 30.0
) -> TriageResult:
    """
    Pure deterministic misinformation triage logic.
    Decides verdict based on monitored basins, official advisories, and current model levels.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if aliases is None:
        aliases = load_aliases()
    if levels is None:
        levels = {}

    evidence: list[str] = []
    text_clean = text.strip() if text else ""
    if not text_clean:
        return TriageResult(
            verdict=Verdict.CANNOT_ASSESS,
            evidence=["Empty or whitespace input cannot be assessed."],
            matched_basins=[]
        )

    # 1. Adversarial input truncation guard (max 50,000 chars)
    truncated = False
    if len(text_clean) > 50000:
        text_clean = text_clean[:50000]
        truncated = True

    # 2. Extract matched basins via aliases
    norm_text = normalize_numerals(text_clean).lower()
    matched_set = set()
    for alias_name, b_id in aliases.items():
        if re.search(rf"\b{re.escape(alias_name.lower())}\b", norm_text):
            matched_set.add(b_id)

    matched_basins = sorted(matched_set)

    # Case: No monitored basin identified
    if not matched_basins:
        evidence.append("No monitored Khyber Pakhtunkhwa river basins identified in text.")
        evidence.append("Check PDMA / PMD / Rescue 1122. Do not forward unverified.")
        return TriageResult(
            verdict=Verdict.CANNOT_ASSESS,
            evidence=evidence,
            matched_basins=[],
            truncated=truncated
        )

    # 3. Check for fresh official advisory covering matched basins
    active_advisory = None
    for adv in advisories:
        if matched_set.intersection(adv.areas):
            if adv.issued_at:
                age_h = max(0.0, (now - adv.issued_at).total_seconds() / 3600.0)
                if age_h <= max_advisory_age_h:
                    active_advisory = adv
                    break
            else:
                active_advisory = adv
                break

    # 4. Check current model risk levels
    highest_level = "GREEN"
    rank = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
    for b in matched_basins:
        lvl = levels.get(b, "GREEN")
        if rank.get(lvl, 0) > rank.get(highest_level, 0):
            highest_level = lvl

    # 5. Extract historical dates & check staleness
    extracted = extract_dates(text_clean, now=now)
    latest_extracted_date = extracted[0] if extracted else None
    is_old = False
    if latest_extracted_date:
        days_old = (now.date() - latest_extracted_date).days
        if days_old > stale_days:
            is_old = True

    # 6. Verdict Decision Matrix
    if active_advisory and not is_old:
        verdict = Verdict.SUPPORTED
        evidence.append(f"Official active advisory found: '{active_advisory.title}' ({active_advisory.source}).")
    elif rank.get(highest_level, 0) >= rank["ORANGE"] and not is_old:
        verdict = Verdict.CONSISTENT
        evidence.append(f"Current model risk is elevated ({highest_level}) for {matched_basins}, consistent with conditions.")
    elif is_old:
        # Old-footage downgrade table (§6.5)
        if active_advisory:
            verdict = Verdict.CANNOT_ASSESS
            evidence.append(f"Text references historical date ({latest_extracted_date}); verify whether report is current.")
        elif rank.get(highest_level, 0) >= rank["ORANGE"]:
            verdict = Verdict.NO_SIGNAL
            evidence.append(f"Text references historical date ({latest_extracted_date}), not current live conditions.")
        else:
            verdict = Verdict.NO_SIGNAL
            evidence.append(f"Text references historical date ({latest_extracted_date}).")
    else:
        verdict = Verdict.NO_SIGNAL
        # Wording Rule for NO_SIGNAL (Issue 8)
        evidence.append(
            f"No model signal and no official advisory found for {', '.join(matched_basins)} (current level: {highest_level}). "
            "Absence of a signal is not proof that nothing happened. It may also describe another place or an earlier date."
        )

    evidence.append("Check PDMA / PMD / Rescue 1122. Do not forward unverified.")

    # Invariant safety assertion: Banned words must NEVER appear in evidence
    for ev in evidence:
        for bw in BANNED_WORDS:
            assert bw not in ev.lower(), f"Banned word '{bw}' found in triage evidence: {ev}"

    return TriageResult(
        verdict=verdict,
        evidence=evidence,
        matched_basins=matched_basins,
        extracted_date=latest_extracted_date,
        level=highest_level,
        truncated=truncated
    )
