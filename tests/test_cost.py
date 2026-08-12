from app.services.classifier import estimate_cost


def test_flash_lite_cost_is_below_assessment_ceiling_for_one_minute():
    # Gemini audio is approximately 1,920 input tokens/minute; reserve 100 output tokens.
    cost = estimate_cost("gemini-3.5-flash-lite", 1_920, 100, 0)
    assert cost < 0.003
    assert round(cost, 6) == 0.000826


def test_preview_model_still_fits_ceiling_with_bounded_output():
    assert estimate_cost("gemini-3-flash-preview", 1_920, 100, 0) < 0.003


def test_selected_ga_model_has_large_cost_margin():
    assert estimate_cost("gemini-3.1-flash-lite", 1_920, 30, 0) < 0.0011
