import pytest
from payflow import Tier, best_tier, categorize, estimate_fee


def test_fee_is_percentage_plus_fixed():
    assert estimate_fee(100.0) == round(100.0 * 0.0349 + 0.49, 2)


def test_fee_on_zero_amount_is_fixed_cut():
    assert estimate_fee(0.0) == 0.49


def test_fee_rejects_negative_amount():
    with pytest.raises(ValueError):
        estimate_fee(-1.0)


def test_fee_rounds_to_cents():
    assert estimate_fee(10.0) == round(10.0 * 0.0349 + 0.49, 2)
    assert len(str(estimate_fee(10.0)).split(".")[1]) <= 2


def test_best_tier_prefers_lower_rate_for_large_sale():
    standard = Tier("standard", 0.0349)
    micro = Tier("micro", 0.0499)
    assert best_tier(1000.0, [standard, micro]) is standard


def test_best_tier_empty_list_rejected():
    with pytest.raises(ValueError):
        best_tier(10.0, [])


def test_categorize_services_note():
    category, confidence = categorize("consulting design sprint")
    assert category == "services"
    assert confidence == 1.0


def test_categorize_digital_note():
    category, confidence = categorize("ebook license")
    assert category == "digital"
    assert confidence == 1.0


def test_categorize_unknown_note_has_zero_confidence():
    category, confidence = categorize("mystery box of parts")
    assert confidence == 0.0
    assert category in {"services", "goods", "donation", "digital"}
