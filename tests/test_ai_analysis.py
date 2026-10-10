import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ai_analysis import (
    build_analysis_payload,
    build_analysis_prompt,
    normalize_json,
    run_openai_analysis,
    safe_openai_error_summary,
    should_auto_request_analysis,
)


def sample_payload():
    return build_analysis_payload(
        as_of_date=date(2026, 10, 10),
        data_mode="Live market data",
        data_source="Yahoo Finance",
        market={"risk_score": 42, "regime": "Range/Choppy", "confidence": "Medium",
                "reasons": [], "warnings": [], "components": []},
        macro={"VIX": {"latest": np.nan, "status": "Unavailable"}},
        holdings=[{"ticker": "ABC", "category": "Growth", "shares": 999,
                   "value_krw_estimate": np.float64(1000), "weight_pct": 10,
                   "metrics": {"close": 12, "unlisted_private_value": 42}}],
        cash_plan={"required_liquidation": 500},
        cash_inputs={"target_date": date(2026, 12, 18)},
    )


def test_payload_is_json_safe_and_minimizes_holding_details():
    payload = sample_payload()
    encoded = json.dumps(payload, allow_nan=False)

    assert '"latest": null' in encoded
    assert payload["metadata"]["as_of_date"] == "2026-10-10"
    assert payload["holdings"][0]["value_krw_estimate"] == 1000
    assert "shares" not in payload["holdings"][0]
    assert "unlisted_private_value" not in payload["holdings"][0]["metrics"]


def test_mock_mode_is_explicit_in_metadata_and_prompt():
    payload = build_analysis_payload(
        date.today(), "Mock demo data", "MOCK", {}, {}, [], {}, {}
    )
    prompt = build_analysis_prompt(payload)

    assert payload["metadata"]["mock_data_warning"] is True
    assert "Mock" in prompt
    assert "실제 투자 판단" in prompt


def test_normalize_non_finite_and_pandas_values():
    assert normalize_json({"missing": pd.NA, "infinite": np.inf}) == {
        "missing": None, "infinite": None
    }


def test_auto_request_only_runs_for_a_new_ai_view_activation():
    assert should_auto_request_analysis("AI", "AI", 2, 1)
    assert not should_auto_request_analysis("Overview", "AI", 2, 1)
    assert not should_auto_request_analysis("AI", "AI", 2, 2)


def test_openai_error_summary_maps_status_without_exposing_exception_text():
    class FakeAPIError(Exception):
        status_code = 401

    message = safe_openai_error_summary(FakeAPIError("secret-key-should-not-appear"))
    assert "401" in message
    assert "secret-key-should-not-appear" not in message

    class QuotaError(Exception):
        status_code = 429
        code = "insufficient_quota"

    assert "크레딧 부족" in safe_openai_error_summary(QuotaError())


def test_openai_call_uses_responses_api_without_persisting_response():
    class Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"output_text": "  분석 결과  "})()

    class FakeClient:
        def __init__(self):
            self.responses = Responses()

    client = FakeClient()
    result = run_openai_analysis(sample_payload(), "test-key", client=client)

    assert result == "분석 결과"
    assert client.responses.kwargs["store"] is False
    assert client.responses.kwargs["model"] == "gpt-4.1-mini"
    assert "분석 데이터" in client.responses.kwargs["input"]


def test_openai_call_rejects_missing_key_and_empty_response():
    with pytest.raises(ValueError, match="API 키"):
        run_openai_analysis({}, "")

    class Responses:
        def create(self, **kwargs):
            return type("Response", (), {"output_text": "  "})()

    class FakeClient:
        responses = Responses()

    with pytest.raises(ValueError, match="텍스트"):
        run_openai_analysis({}, "test-key", client=FakeClient())
