"""
Pre-Transmission Alert Verification Engine (verify.py)
======================================================
Owner: Person 1 (Qamran)
Published, stable signatures (§6.3).
Automated gatekeeper blocking hallucinated numbers, incorrect basins,
and mixed risk vocabularies before dispatch.
"""

from __future__ import annotations

import re
from typing import Any

# Maximum character constraint for SMS / WhatsApp broadcast
MAX_ALERT_LENGTH = 1600

# Digit normalization mapping for Urdu and Arabic-Indic numerals
INDIC_DIGITS_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789"
)

# Standard Tier-to-Vocabulary Table (§3.3)
TIER_VOCABULARY = {
    "none": {"GREEN", "none"},
    "low": {"GREEN", "low"},
    "moderate": {"YELLOW", "Watch", "watch"},
    "high": {"ORANGE", "Warning", "warning"},
    "severe": {"RED", "Emergency", "emergency"}
}

ALL_TIER_WORDS = {w.lower() for words in TIER_VOCABULARY.values() for w in words}


def normalize_numerals(text: str) -> str:
    """Translates Urdu/Arabic-Indic digits to standard ASCII numerals."""
    return text.translate(INDIC_DIGITS_MAP)


def extract_numbers(text: str) -> set[str]:
    """Extracts all continuous integer and floating point numbers from text."""
    normalized = normalize_numerals(text)
    # Match numbers like 1122, 0.62, 25, etc.
    raw_matches = re.findall(r"\b\d+(?:\.\d+)?\b", normalized)
    # Return canonical float/int strings
    canonical = set()
    for m in raw_matches:
        try:
            val = float(m)
            if val.is_integer():
                canonical.add(str(int(val)))
            canonical.add(str(val))
            canonical.add(m)
        except ValueError:
            canonical.add(m)
    return canonical


def allowed_numbers_for(result: Any) -> set[str]:
    """
    Duck-typed extractor collecting legitimate numbers associated with a risk result.
    Collects score, probabilities, reasons, timestamps, and emergency 1122.
    """
    allowed = {"1122"}  # Rescue 1122 hotline is always allowed

    # Add score / probabilities
    for attr in ["score", "prob_a", "prob_b"]:
        val = getattr(result, attr, None)
        if val is not None and isinstance(val, (int, float)):
            allowed.add(str(round(val, 2)))
            allowed.add(str(round(val, 3)))
            allowed.add(str(round(val, 1)))
            allowed.add(str(round(val * 100)))  # percentages like 62%

    # Add numbers from reasons
    reasons = getattr(result, "reasons", [])
    if isinstance(reasons, (list, tuple)):
        for r in reasons:
            allowed.update(extract_numbers(str(r)))

    # Add date/time numbers from computed_at if present
    computed_at = getattr(result, "computed_at", "")
    if computed_at:
        allowed.update(extract_numbers(str(computed_at)))

    return allowed


def check_alert(
    text: str,
    *,
    basin_id: str,
    tier: str,
    allowed_numbers: set[str]
) -> list[str]:
    """
    Core verification checks:
      1. Non-empty, length <= 1600
      2. basin_id explicitly mentioned
      3. Valid word for the assigned tier present
      4. Zero forbidden words belonging to any other tier
      5. Every number exists in allowed_numbers
    Returns empty list on clean pass.
    """
    problems: list[str] = []

    if not text or not text.strip():
        return ["Message text is empty."]

    if len(text) > MAX_ALERT_LENGTH:
        problems.append(f"Message length ({len(text)}) exceeds maximum {MAX_ALERT_LENGTH} characters.")

    # Basin ID check
    if basin_id.lower() not in text.lower():
        problems.append(f"Required basin_id '{basin_id}' not found in message text.")

    # Tier vocabulary check
    norm_text_lower = text.lower()
    valid_words = {w.lower() for w in TIER_VOCABULARY.get(tier.lower(), set())}
    forbidden_words = ALL_TIER_WORDS - valid_words

    # Check that at least one valid word is present
    has_valid_word = any(re.search(rf"\b{re.escape(w)}\b", norm_text_lower) for w in valid_words)
    if not has_valid_word:
        problems.append(f"Message lacks valid vocabulary for tier '{tier}' ({valid_words}).")

    # Check that NO forbidden word from a different tier is present
    for fw in forbidden_words:
        if re.search(rf"\b{re.escape(fw)}\b", norm_text_lower):
            problems.append(f"Conflicting tier vocabulary detected: found forbidden word '{fw}'.")
            break

    # Number verification
    found_numbers = extract_numbers(text)
    # Normalize allowed numbers set
    allowed_canonical = set()
    for n in allowed_numbers:
        try:
            val = float(n)
            if val.is_integer():
                allowed_canonical.add(str(int(val)))
            allowed_canonical.add(str(val))
            allowed_canonical.add(n)
        except ValueError:
            allowed_canonical.add(n)

    unauthorized = found_numbers - allowed_canonical
    if unauthorized:
        problems.append(f"Unauthorized or hallucinated numbers found in message: {unauthorized}")

    return problems


def check_risk_alert(
    text: str,
    result: Any,
    *,
    extra_numbers: tuple[str, ...] = (),
    extra_texts: tuple[str, ...] = ()
) -> list[str]:
    """
    Convenience verification entry point taking duck-typed RiskResult.
    """
    basin_id = getattr(result, "area_id", "")
    tier = getattr(result, "tier", "none")
    allowed = allowed_numbers_for(result)
    allowed.update(extra_numbers)

    return check_alert(
        text,
        basin_id=basin_id,
        tier=tier,
        allowed_numbers=allowed
    )
