"""Unit tests for verify.py alert verification engine."""

from types import SimpleNamespace

from floodwatch.verify import allowed_numbers_for, check_alert


def test_clean_template_passes():
    res = SimpleNamespace(
        area_id="swat_kalam",
        score=0.72,
        prob_a=0.72,
        prob_b=0.30,
        tier="high",
        reasons=["Rainfall rate: 25.0 mm/h"],
        computed_at="2026-11-08T06:00:00Z"
    )
    allowed = allowed_numbers_for(res)
    text = "WARNING: FloodWatch KP has detected High risk (score 0.72) in swat_kalam. Rainfall rate: 25.0 mm/h. Contact Rescue 1122."
    problems = check_alert(text, basin_id="swat_kalam", tier="high", allowed_numbers=allowed)
    assert problems == [], f"Expected clean pass, got: {problems}"


def test_mixed_vocabulary_blocked():
    # Attempting to combine Warning (high) with RED (severe)
    allowed = {"1122"}
    text = "Warning: Emergency RED alert for swat_kalam. Call 1122."
    problems = check_alert(text, basin_id="swat_kalam", tier="high", allowed_numbers=allowed)
    assert any("Conflicting tier vocabulary" in p for p in problems)


def test_hallucinated_number_blocked():
    allowed = {"1122", "0.75"}
    # Contains unverified 95% statistic
    text = "Warning for swat_kalam: 95% probability of destruction! Call 1122."
    problems = check_alert(text, basin_id="swat_kalam", tier="high", allowed_numbers=allowed)
    assert any("Unauthorized or hallucinated numbers" in p for p in problems)


def test_arabic_indic_numerals_normalization():
    # ۰.۷۲ is 0.72 in Urdu numerals
    allowed = {"1122", "0.72"}
    text = "Warning for swat_kalam with probability ۰.۷۲. Call ۱۱۲۲."
    problems = check_alert(text, basin_id="swat_kalam", tier="high", allowed_numbers=allowed)
    assert problems == [], f"Expected normalization to pass, got: {problems}"
