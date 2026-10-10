from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd


ANALYSIS_INSTRUCTIONS = """너는 개인 투자 대시보드의 데이터 해석 보조자다. 한국어로 답하고 관측값, 해석, 가정을 구분한다.
입력에 없는 가격, 뉴스, 펀더멘털, 세금, 시장 폭을 지어내지 말고 결측은 데이터 없음으로 처리한다.
데이터가 Mock이면 실제 투자 판단에 사용하지 말라고 분명히 경고한다. 프록시 지표를 실제 breadth로 부르지 않는다.
RSI 하나로 매수·매도를 판단하지 말고, 수익률이 높다는 이유만으로 매도 검토 순위를 높이지 않는다.
현금 확보 마감일은 시장 전망보다 우선한다. 필요 현금이 충족되면 위험 점수만으로 추가 매도를 권하지 않는다.
시장 점수와 매도 순위는 규칙 기반 참고치이지 확률이나 최적화 결과가 아니다. 목표주가, 확률, 세후 금액을 임의로 만들지 않는다.
다음 순서로 분석한다: A 한눈에 보는 결론과 신뢰도, B 시장 근거/신호 충돌, C 종목별 긍정·부정 근거와 다음 확인 조건, D 집중도·환율·스트레스 위험, E 현금 확보 시나리오와 우선순위, F 실행 전 체크리스트, G 한계와 고지.
최종 매매 결정은 사용자에게 있으며 투자 조언이나 수익 보장이 아니다. 보유 정보나 계획을 변경하거나 주문을 실행하지 않는다."""


_METRIC_KEYS = (
    "close", "ma20", "ma50", "ma100", "ma200", "slope_50_pct",
    "dist_200_pct", "rsi14", "macd", "macd_signal", "mom_1m_pct",
    "mom_3m_pct", "mom_6m_pct", "mom_12m_pct", "high_52w",
    "low_52w", "drawdown_52w_pct", "days_from_high", "vol20_ann_pct",
    "vol60_ann_pct", "structure", "signal",
)


def normalize_json(value: Any) -> Any:
    """Convert pandas/numpy/date values and non-finite numbers to JSON-safe values."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_analysis_payload(
    as_of_date: Any,
    data_mode: str,
    data_source: str,
    market: Mapping[str, Any],
    macro: Mapping[str, Any],
    holdings: list[Mapping[str, Any]],
    cash_plan: Mapping[str, Any],
    cash_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a minimal, JSON-safe summary; no price history or API secrets are included."""
    market_summary = {
        key: market.get(key)
        for key in ("risk_score", "regime", "confidence", "reasons", "warnings", "components")
        if key in market
    }
    holding_summaries = []
    for holding in holdings[:50]:
        metrics = holding.get("metrics", {})
        holding_summaries.append({
            "ticker": holding.get("ticker"),
            "category": holding.get("category"),
            "value_krw_estimate": holding.get("value_krw_estimate"),
            "weight_pct": holding.get("weight_pct"),
            "unrealized_pnl_pct_estimate": holding.get("unrealized_pnl_pct_estimate"),
            "metrics": {key: metrics.get(key) for key in _METRIC_KEYS if key in metrics},
        })

    return normalize_json({
        "metadata": {
            "as_of_date": as_of_date,
            "data_mode": data_mode,
            "data_source": data_source,
            "mock_data_warning": data_mode.lower().startswith("mock"),
        },
        "market": {"regime": market_summary, "macro": macro},
        "holdings": holding_summaries,
        "cash_plan": {"calculation": cash_plan, "inputs": cash_inputs},
        "limitations": [
            "일별 종가 기준이며 실시간 체결 데이터가 아닙니다.",
            "평가액은 환율 적용 추정치이며 세금·수수료·환전 스프레드를 반영하지 않을 수 있습니다.",
            "SPY/RSP 상대 성과는 실제 시장 breadth가 아닌 프록시입니다.",
            "AI 분석은 참고용이며 매매 주문을 실행하거나 계획을 변경하지 않습니다.",
        ],
    })


def build_analysis_prompt(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(normalize_json(payload), ensure_ascii=False, indent=2, allow_nan=False)
    return "{}\n\n[분석 데이터]\n{}".format(ANALYSIS_INSTRUCTIONS, serialized)


def should_auto_request_analysis(
    selected_view: str,
    ai_view: str,
    activation_id: int,
    processed_activation_id: int,
) -> bool:
    return selected_view == ai_view and activation_id > processed_activation_id


def safe_openai_error_summary(error: Exception) -> str:
    status_code = getattr(error, "status_code", None)
    error_code = getattr(error, "code", None)
    error_type = type(error).__name__

    if status_code == 401:
        return "인증 실패 (401): API 키가 유효한지 또는 폐기되지 않았는지 확인하세요."
    if status_code == 403:
        return "권한 거부 (403): 프로젝트 권한과 모델 접근 권한을 확인하세요."
    if status_code == 404:
        return "요청 항목을 찾지 못했습니다 (404): 모델 이름과 접근 가능 여부를 확인하세요."
    if status_code == 429 and error_code == "insufficient_quota":
        return "API 사용 한도/크레딧 부족 (429): 결제 설정과 사용 한도를 확인하세요."
    if status_code == 429:
        return "요청 한도 초과 (429): 잠시 후 다시 시도하거나 사용량 한도를 확인하세요."
    if status_code == 400:
        return "요청 거부 (400): 모델 설정 또는 전송 입력의 크기/형식을 확인하세요."
    if isinstance(status_code, int) and status_code >= 500:
        return "OpenAI 서비스 오류 ({}): 잠시 후 다시 시도하세요.".format(status_code)
    if "Timeout" in error_type:
        return "요청 시간 초과: 네트워크 상태를 확인한 뒤 다시 시도하세요."
    if "Connection" in error_type:
        return "네트워크 연결 실패: 인터넷 연결과 OpenAI API 접근을 확인하세요."
    return "요청 또는 응답 처리 실패 ({}). API 설정을 확인하세요.".format(error_type)


def run_openai_analysis(
    payload: Mapping[str, Any],
    api_key: str,
    model: str = "gpt-4.1-mini",
    client: Optional[Any] = None,
) -> str:
    """Call the OpenAI Responses API. Client injection keeps tests offline."""
    if not api_key:
        raise ValueError("OpenAI API 키가 설정되지 않았습니다.")
    prompt = build_analysis_prompt(payload)
    if len(prompt) > 40000:
        raise ValueError("분석 입력이 너무 큽니다. 보유 종목 수나 전달 데이터를 줄여 주세요.")
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=60.0, max_retries=1)
    response = client.responses.create(
        model=model,
        instructions=ANALYSIS_INSTRUCTIONS,
        input="[분석 데이터]\n{}".format(json.dumps(normalize_json(payload), ensure_ascii=False, allow_nan=False)),
        store=False,
        max_output_tokens=1800,
    )
    result = getattr(response, "output_text", "")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("OpenAI API에서 분석 텍스트를 받지 못했습니다.")
    return result.strip()
