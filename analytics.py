from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd

def _mock_series(ticker, n=520, seed=0):
    rng = np.random.default_rng(abs(hash(ticker)) % (2**32) + seed)
    drift = 0.00025 if ticker not in ["^VIX"] else 0
    vol = 0.012 if ticker not in ["^VIX", "^TNX", "^IRX", "DX-Y.NYB", "KRW=X"] else 0.008
    returns = rng.normal(drift, vol, n)
    base = {"^GSPC": 5700, "^NDX": 20000, "^VIX": 18, "^TNX": 4.4, "^IRX": 4.1, "DX-Y.NYB": 103,
            "KRW=X": 1370, "BTC-USD": 80000, "SPY": 570, "RSP": 175, "QQQM": 200, "NVDA": 130,
            "AMD": 150, "TSLA": 300, "GOOGL": 170, "PLTR": 100, "MSFT": 420, "IEF": 95, "HYG": 80}.get(ticker, 100)
    values = base * np.cumprod(1 + returns)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.Series(values, index=idx, name=ticker)

def fetch_prices(tickers, period="2y", mock=False):
    if mock:
        return {t: _mock_series(t) for t in tickers}, "MOCK DATA (데모)"
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        return out, "Yahoo Finance unavailable (install requirements.txt)"
    for ticker in tickers:
        try:
            df = yf.download(ticker, period=period, interval="1d", auto_adjust=True, progress=False, threads=False)
            if df is None or df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                if ticker in close.columns:
                    close = close[ticker]
                else:
                    close = close.iloc[:, 0]
            close = pd.to_numeric(close, errors="coerce").dropna()
            # Yahoo ^TNX/^IRX are commonly quoted as yield x10 (e.g. 43.5 means 4.35%).
            if ticker in ["^TNX", "^IRX"]:
                close = close / 10.0
            if not close.empty:
                out[ticker] = close.rename(ticker)
        except Exception:
            continue
    return out, "Yahoo Finance (지연/가용성 제한 가능)"

def compute_asset_metrics(series):
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        return {}
    close = float(s.iloc[-1])
    result = {"close": close}
    for n in [20, 50, 100, 200]:
        result[f"ma{n}"] = float(s.rolling(n).mean().iloc[-1]) if len(s) >= n else np.nan
    ma50 = s.rolling(50).mean()
    result["slope_50_pct"] = float((ma50.iloc[-1] / ma50.iloc[-21] - 1) * 100) if len(s) >= 70 and pd.notna(ma50.iloc[-21]) and ma50.iloc[-21] else np.nan
    result["dist_200_pct"] = float((close / result["ma200"] - 1) * 100) if pd.notna(result["ma200"]) and result["ma200"] else np.nan
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    result["rsi14"] = float((100 - 100/(1+rs)).iloc[-1]) if pd.notna((100 - 100/(1+rs)).iloc[-1]) else np.nan
    ema12, ema26 = s.ewm(span=12, adjust=False).mean(), s.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    result["macd"] = float(macd.iloc[-1])
    result["macd_signal"] = float(macd.ewm(span=9, adjust=False).mean().iloc[-1])
    for label, days in [("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252)]:
        result[f"mom_{label}_pct"] = float((close / s.iloc[-days-1] - 1)*100) if len(s) > days else np.nan
    hi = float(s.tail(min(252, len(s))).max())
    lo = float(s.tail(min(252, len(s))).min())
    result["high_52w"] = hi
    result["low_52w"] = lo
    result["drawdown_52w_pct"] = float((close / hi - 1)*100) if hi else np.nan
    result["days_from_high"] = int(len(s.tail(min(252, len(s)))) - 1 - np.argmax(s.tail(min(252, len(s))).to_numpy()))
    returns = s.pct_change().dropna()
    result["vol20_ann_pct"] = float(returns.tail(20).std(ddof=1)*np.sqrt(252)*100) if len(returns) >= 20 else np.nan
    result["vol60_ann_pct"] = float(returns.tail(60).std(ddof=1)*np.sqrt(252)*100) if len(returns) >= 60 else np.nan
    # Swing structure heuristic: compare recent local extrema, not a full chart-pattern classifier.
    recent = s.tail(100)
    peaks = recent[(recent.shift(1) < recent) & (recent.shift(-1) < recent)]
    troughs = recent[(recent.shift(1) > recent) & (recent.shift(-1) > recent)]
    if len(peaks) >= 2 and len(troughs) >= 2:
        ph, pl = peaks.iloc[-2:].to_numpy(), troughs.iloc[-2:].to_numpy()
        result["structure"] = "HH/HL" if ph[1] > ph[0] and pl[1] > pl[0] else ("LH/LL" if ph[1] < ph[0] and pl[1] < pl[0] else "Mixed")
    else:
        result["structure"] = "Insufficient data"
    # Only close-confirmed trend status, not intraday.
    if pd.notna(result["ma200"]):
        result["signal"] = "Above 200DMA" if close > result["ma200"] else "Below 200DMA"
    else:
        result["signal"] = "Insufficient history"
    return result


def stock_overall_opinion(metrics, category="Other", weight_pct=None, unrealized_pnl_pct=None, days_remaining=None, cash_shortfall=False):
    """Rule-based per-stock view from technicals and portfolio risk; not fundamental valuation advice."""
    if not metrics or metrics.get("close") is None:
        return {"view": "데이터 부족", "action": "가격 데이터 확보 후 판단", "reason": "기술적 지표를 계산할 데이터가 부족합니다."}

    def num(key):
        v = metrics.get(key)
        return float(v) if v is not None and pd.notna(v) else np.nan

    dist200, slope50 = num("dist_200_pct"), num("slope_50_pct")
    mom3, mom6, rsi = num("mom_3m_pct"), num("mom_6m_pct"), num("rsi14")
    vol, dd = num("vol20_ann_pct"), num("drawdown_52w_pct")
    above200 = pd.notna(dist200) and dist200 > 0
    rising50 = pd.notna(slope50) and slope50 > 0
    positive_momentum = (pd.notna(mom3) and mom3 > 0) and (pd.isna(mom6) or mom6 > 0)
    trend_score = sum([above200, rising50, positive_momentum])

    flags=[]
    if pd.notna(dist200): flags.append(f"200일선 대비 {dist200:+.1f}%")
    if pd.notna(mom3): flags.append(f"3개월 수익률 {mom3:+.1f}%")
    if pd.notna(rsi): flags.append(f"RSI {rsi:.0f}")
    if pd.notna(vol): flags.append(f"연환산 변동성 {vol:.0f}%")
    if pd.notna(dd): flags.append(f"52주 고점 대비 {dd:.1f}%")

    if trend_score >= 3:
        view = "상승 추세 우세"
        action = "보유 가능성 우세; 현금화 기한에 맞춰 분할 매도 검토"
    elif trend_score == 2:
        view = "상승 추세 혼재"
        action = "추세 유지 여부 확인; 필요 현금은 계획적으로 분할 확보"
    elif trend_score == 1:
        view = "추세 중립·약화"
        action = "반등만 기대해 매도를 미루지 말고 추세 확인"
    else:
        view = "하락·약세 위험 우세"
        action = "추가 하락 위험을 고려해 현금화 우선순위 검토"

    cautions=[]
    if pd.notna(rsi) and rsi >= 70:
        cautions.append("단기 과열 가능성")
    elif pd.notna(rsi) and rsi <= 30:
        cautions.append("과매도 구간일 수 있으나 반등 보장은 아님")
    if pd.notna(vol) and vol >= 55:
        cautions.append("높은 변동성")
    if pd.notna(dd) and dd <= -20:
        cautions.append("고점 대비 큰 낙폭")
    if category == "High volatility" or (pd.notna(vol) and vol >= 70):
        cautions.append("포지션 크기 관리 필요")
    if weight_pct is not None and pd.notna(weight_pct) and weight_pct >= 30:
        cautions.append("단일 종목 집중도 높음")
    if days_remaining is not None and days_remaining <= 60 and cash_shortfall:
        cautions.append("현금화 기한 임박: 시장 전망보다 자금 확보 우선")
    if unrealized_pnl_pct is not None and pd.notna(unrealized_pnl_pct):
        if unrealized_pnl_pct > 0:
            cautions.append(f"평가이익 {unrealized_pnl_pct:+.1f}% (세금·환율 확인)")
        else:
            cautions.append(f"평가손익 {unrealized_pnl_pct:+.1f}% (손실만으로 매도/보유 결정 금지)")

    reason = " · ".join(flags) if flags else "기술적 지표 일부 부족"
    if cautions:
        reason += " | 유의: " + " · ".join(cautions)
    return {"view": view, "action": action, "reason": reason}

def macro_snapshot(prices):
    output = {}
    for ticker, name in [("^TNX", "US 10Y yield (Yahoo proxy)"), ("^IRX", "US 13W yield (Yahoo proxy)"),
                         ("DX-Y.NYB", "DXY"), ("KRW=X", "USD/KRW"), ("^VIX", "VIX")]:
        s = prices.get(ticker)
        if s is None or s.dropna().empty:
            output[name] = {"latest": None, "change_1m": None, "change_3m": None, "status": "Unavailable", "source": "No reliable series"}
            continue
        s = s.dropna()
        last = float(s.iloc[-1])
        one = float((last / s.iloc[-22] - 1)*100) if len(s) > 22 and ticker not in ["^TNX", "^IRX", "^VIX"] else (last - float(s.iloc[-22]) if len(s)>22 else np.nan)
        three = float((last / s.iloc[-64] - 1)*100) if len(s) > 64 and ticker not in ["^TNX", "^IRX", "^VIX"] else (last - float(s.iloc[-64]) if len(s)>64 else np.nan)
        output[name] = {"latest": round(last, 3), "change_1m": round(one, 3) if pd.notna(one) else None,
                        "change_3m": round(three, 3) if pd.notna(three) else None, "status": "Observed",
                        "source": "Yahoo Finance; change is percentage points for yields/VIX, percent for FX/DXY"}
    output["US real yield"] = {"latest": None, "change_1m": None, "change_3m": None, "status": "Unavailable", "source": "FRED API not configured"}
    output["Credit spread (HY OAS)"] = {"latest": None, "change_1m": None, "change_3m": None, "status": "Unavailable", "source": "FRED API not configured"}
    output["Yield curve (10Y-3M)"] = {"latest": None, "change_1m": None, "change_3m": None, "status": "Approximation unavailable" if "^TNX" not in prices or "^IRX" not in prices else "Proxy",
                                      "source": "Yahoo ^TNX minus ^IRX; indicative only"}
    if "^TNX" in prices and "^IRX" in prices and not prices["^TNX"].empty and not prices["^IRX"].empty:
        output["Yield curve (10Y-3M)"]["latest"] = round(float(prices["^TNX"].dropna().iloc[-1] - prices["^IRX"].dropna().iloc[-1]), 3)
    return output

def market_regime(prices):
    score = 50
    components, reasons, warnings = [], [], []
    available = 0
    for ticker, name in [("^GSPC", "S&P 500 trend"), ("^NDX", "NASDAQ 100 trend")]:
        s = prices.get(ticker)
        if s is not None and len(s.dropna()) >= 200:
            m = compute_asset_metrics(s)
            available += 1
            val = -10 if m["close"] > m["ma200"] else 12
            score += val
            components.append({"Component": name, "Observation": f"close vs 200DMA: {m['signal']}", "Score contribution": val, "Quality": "Daily close"})
            if val > 0: reasons.append(f"{name}: 200DMA 하회")
        else:
            components.append({"Component": name, "Observation": "Unavailable/insufficient history", "Score contribution": 0, "Quality": "Low"})
    vix = prices.get("^VIX")
    if vix is not None and not vix.dropna().empty:
        v = float(vix.dropna().iloc[-1]); available += 1
        val = -10 if v < 15 else (-4 if v < 20 else (8 if v < 25 else (18 if v < 30 else 28)))
        score += val
        components.append({"Component":"VIX","Observation":f"{v:.2f}","Score contribution":val,"Quality":"Daily close"})
        if v >= 20: reasons.append(f"VIX {v:.1f}")
    t = prices.get("^TNX")
    if t is not None and not t.dropna().empty:
        y=float(t.dropna().iloc[-1]); available += 1
        val=0 if y < 4.5 else (4 if y < 5 else (8 if y < 5.2 else (12 if y < 5.5 else 18)))
        score+=val
        components.append({"Component":"US 10Y yield","Observation":f"{y:.2f} (Yahoo proxy)","Score contribution":val,"Quality":"Proxy"})
        if y >= 5.2: reasons.append(f"US10Y {y:.2f}")
    # Cross-sectional breadth isn't sourced here; SPY/RSP is only a proxy.
    spy, rsp = prices.get("SPY"), prices.get("RSP")
    if spy is not None and rsp is not None and len(spy.dropna()) > 65 and len(rsp.dropna()) > 65:
        spread = compute_asset_metrics(spy)["mom_3m_pct"] - compute_asset_metrics(rsp)["mom_3m_pct"]
        val = 5 if spread > 5 else (-3 if spread < 1 else 0)
        score += val; available += 1
        components.append({"Component":"Breadth proxy (SPY vs RSP)","Observation":f"3M return spread {spread:.2f} pp","Score contribution":val,"Quality":"Proxy, not constituent breadth"})
        if spread > 5: reasons.append("SPY가 RSP보다 강함: 대형주 집중 가능성")
    else:
        components.append({"Component":"S&P constituent breadth","Observation":"Unavailable","Score contribution":0,"Quality":"Not fabricated"})
        warnings.append("실제 구성종목 breadth 데이터가 없어 시장 내부 구조 판단의 신뢰도가 제한됩니다.")
    score = int(max(0, min(100, score)))
    if score >= 75: regime = "High Volatility Stress"
    elif score >= 60: regime = "Downtrend / Risk-Off"
    elif score >= 45: regime = "Range/Choppy"
    elif score >= 30: regime = "Uptrend"
    else: regime = "Strong Uptrend"
    confidence = "Medium" if available >= 4 else ("Low" if available < 3 else "Medium-Low")
    if available < 3:
        regime = "Mixed/Low Confidence"
        warnings.append("핵심 데이터가 부족해 시장 레짐 분류를 신뢰하기 어렵습니다.")
    return {"risk_score": score, "regime": regime, "confidence": confidence, "reasons": reasons, "warnings": warnings, "components": components}

def portfolio_risk(portfolio, prices):
    rows=[]
    fx_series=prices.get("KRW=X")
    fx=float(fx_series.dropna().iloc[-1]) if fx_series is not None and not fx_series.dropna().empty else 1400.0
    for _, row in portfolio.iterrows():
        ticker=str(row.get("Ticker","")).strip().upper()
        if not ticker or ticker not in prices or prices[ticker].dropna().empty:
            continue
        s=prices[ticker].dropna()
        m=compute_asset_metrics(s)
        shares=float(row.get("Shares",0) or 0)
        avg=float(row.get("Average Cost KRW",0) or 0)
        value=shares*float(s.iloc[-1])*fx
        cost=shares*avg
        rows.append({"Ticker":ticker,"Shares":shares,"Price USD":float(s.iloc[-1]),"Value KRW":value,
                     "Unrealized P/L %":(value/cost-1)*100 if cost else np.nan,
                     "52W DD %":m.get("drawdown_52w_pct",np.nan),"Vol 20d %":m.get("vol20_ann_pct",np.nan),
                     "RSI":m.get("rsi14",np.nan),"Weight %":np.nan,"Average Cost KRW":avg})
    df=pd.DataFrame(rows)
    if df.empty: return df,0,fx
    total=float(df["Value KRW"].sum())
    df["Weight %"]=df["Value KRW"]/total*100 if total else 0
    return df,total,fx

def stress_test(portfolio, risk_df, growth_shock=-20, other_shock=-10, fx_shock=5):
    total=float(risk_df["Value KRW"].sum()) if not risk_df.empty else 0
    change=0.0
    for _, r in risk_df.iterrows():
        ticker=r["Ticker"]
        category="Growth"
        if "Category" in portfolio.columns:
            match=portfolio[portfolio["Ticker"].astype(str).str.upper()==ticker]
            if not match.empty: category=str(match.iloc[0]["Category"])
        shock=growth_shock if category in ["Growth","High volatility"] else other_shock
        # FX shock approximates the KRW value translation for US assets.
        change += float(r["Value KRW"])*((1+shock/100)*(1+fx_shock/100)-1)
    return {"change_krw":change,"change_pct":change/total*100 if total else 0}

def sell_priority(portfolio, risk_df, asset_metrics, days_remaining, required_liquidation):
    if risk_df.empty: return pd.DataFrame()
    rows=[]
    for _, r in risk_df.iterrows():
        ticker=r["Ticker"]; m=asset_metrics.get(ticker,{})
        category="Other"
        if "Category" in portfolio.columns:
            match=portfolio[portfolio["Ticker"].astype(str).str.upper()==ticker]
            if not match.empty: category=str(match.iloc[0]["Category"])
        vol=float(r["Vol 20d %"]) if pd.notna(r["Vol 20d %"]) else 30
        dd=abs(float(r["52W DD %"])) if pd.notna(r["52W DD %"]) else 0
        weight=float(r["Weight %"])
        # Transparent heuristic, not an optimizer.
        score=min(100, 0.25*min(vol,100)+0.25*min(dd,50)*2+0.25*weight+ (15 if category=="High volatility" else 10 if category=="Growth" else 0))
        if ticker=="QQQM": score=max(0,score-8) # diversification benefit, not low-risk assumption
        if days_remaining <= 30: score += 10
        elif days_remaining <= 60: score += 5
        score=min(100,score)
        rows.append({"Ticker":ticker,"Value KRW":r["Value KRW"],"Weight %":weight,"Risk/urgency score":round(score,1),
                     "Trend":m.get("signal","Unavailable"),"52W DD %":r["52W DD %"],
                     "Reason":f"{category}; vol/drawdown/weight heuristic; deadline {days_remaining}d"})
    out=pd.DataFrame(rows).sort_values("Risk/urgency score",ascending=False)
    out.insert(0,"Priority",range(1,len(out)+1))
    out["Required liquidation remaining KRW"]=max(0,required_liquidation)
    return out

def cash_plan(required_cash, cash_now, confirmed_inflows, emergency_reserve, tax_buffer, target_date):
    required=max(0, float(required_cash)+float(emergency_reserve)+float(tax_buffer)-float(cash_now)-float(confirmed_inflows))
    days=(target_date-date.today()).days
    daily=required/days if days>0 else (required if required>0 else 0)
    # Calendar-month allocation: illustrative pacing, accelerated if deadline is near or risk is high elsewhere.
    weights=[("Current month",0.30),("Next month",0.35),("Deadline month",0.35)]
    monthly=[{"Period":label,"Baseline target KRW":required*w} for label,w in weights]
    return {"required_liquidation":required,"days_remaining":days,"daily_required":daily,"monthly_plan":monthly}

def historical_backtest(series, fee_bps=10, slippage_bps=5):
    s=pd.Series(series).dropna().astype(float)
    if len(s)<250: return {"Status":"Insufficient data"}
    close=s
    ma50=close.rolling(50).mean()
    ma200=close.rolling(200).mean()
    # Lag one day to avoid look-ahead: signal based on yesterday's close is held today.
    signal=(ma50>ma200).shift(1).fillna(False).astype(float)
    returns=close.pct_change().fillna(0)
    turnover=signal.diff().abs().fillna(signal.iloc[0])
    cost=(fee_bps+slippage_bps)/10000
    strat=signal*returns-turnover*cost
    strat=strat.iloc[200:]
    buy=returns.iloc[200:]
    def metrics(r):
        if len(r)==0: return {}
        equity=(1+r).cumprod()
        years=len(r)/252
        dd=equity/equity.cummax()-1
        vol=r.std(ddof=1)*np.sqrt(252)
        sharpe=(r.mean()*252)/(vol if vol else np.nan)
        downside=r[r<0]
        downside_vol=downside.std(ddof=1)*np.sqrt(252) if len(downside)>1 else np.nan
        sortino=(r.mean()*252)/downside_vol if downside_vol and downside_vol>0 else np.nan
        return {"CAGR %":((equity.iloc[-1]**(1/years)-1)*100) if years>0 and equity.iloc[-1]>0 else np.nan,
                "MDD %":float(dd.min()*100),"Volatility %":float(vol*100),"Sharpe":float(sharpe),
                "Sortino":float(sortino),"Turnover (signal changes)":float(turnover.loc[r.index].sum())}
    sm=metrics(strat); bm=metrics(buy)
    return {"Strategy":"50DMA > 200DMA (lagged close signal)","CAGR %":sm.get("CAGR %"),"MDD %":sm.get("MDD %"),
            "Volatility %":sm.get("Volatility %"),"Sharpe":sm.get("Sharpe"),"Sortino":sm.get("Sortino"),
            "Turnover":sm.get("Turnover (signal changes)"),"Buy & Hold CAGR %":bm.get("CAGR %"),
            "Buy & Hold MDD %":bm.get("MDD %"),"Costs (bps per turnover)":fee_bps+slippage_bps,
            "Caveat":"Illustrative; no taxes, no dividend tax detail, Yahoo adjusted close; not a validated strategy"}
