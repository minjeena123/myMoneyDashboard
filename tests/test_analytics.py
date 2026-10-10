import numpy as np
import pandas as pd
from datetime import date, timedelta
from analytics import compute_asset_metrics, market_regime, cash_plan, historical_backtest, stock_overall_opinion

def test_metrics_trending_series():
    s = pd.Series(np.linspace(100, 200, 300))
    m = compute_asset_metrics(s)
    assert m["close"] == 200
    assert m["ma200"] > 100
    assert m["mom_1m_pct"] > 0
    assert m["drawdown_52w_pct"] == 0

def test_cash_plan_respects_confirmed_inflows():
    p = cash_plan(100, 20, 30, 10, 5, date.today() + timedelta(days=10))
    assert p["required_liquidation"] == 65
    assert p["days_remaining"] >= 9

def test_backtest_has_lagged_signal_and_metrics():
    idx = pd.bdate_range("2020-01-01", periods=600)
    s = pd.Series(np.linspace(100, 300, 600), index=idx)
    bt = historical_backtest(s)
    assert "CAGR %" in bt
    assert "Buy & Hold CAGR %" in bt

def test_regime_returns_explainability():
    idx = pd.bdate_range("2020-01-01", periods=520)
    s = pd.Series(np.linspace(100, 200, 520), index=idx)
    result = market_regime({"^GSPC":s,"^NDX":s,"^VIX":pd.Series(15.0,index=idx),"^TNX":pd.Series(4.0,index=idx)})
    assert 0 <= result["risk_score"] <= 100
    assert "components" in result


def test_stock_opinion_is_explainable():
    metrics = {"close": 100, "dist_200_pct": 8, "slope_50_pct": 2, "mom_3m_pct": 6,
               "mom_6m_pct": 12, "rsi14": 62, "vol20_ann_pct": 25, "drawdown_52w_pct": -4}
    opinion = stock_overall_opinion(metrics, "Mega-cap", 20, 10, 90, False)
    assert opinion["view"] == "상승 추세 우세"
    assert "200일선 대비" in opinion["reason"]
    assert opinion["action"]
