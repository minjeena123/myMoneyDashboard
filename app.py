
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import date

st.set_page_config(
    page_title="My Market Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container {padding: 1rem 1rem 2rem 1rem; max-width: 1200px;}
h1 {font-size: 1.7rem !important;}
[data-testid="stMetricValue"] {font-size: 1.35rem;}
div[data-testid="stMetric"] {padding: .45rem .2rem;}
.small {font-size:.85rem; color:#666;}
.card {padding:1rem; border:1px solid #ddd; border-radius:14px; margin:.4rem 0;}
</style>
""", unsafe_allow_html=True)

st.title("📊 My Market Risk Dashboard")
st.caption("시장 위험도 + 포트폴리오 + 12월 현금화 계획")

DEFAULT = pd.DataFrame([
    ["QQQM", 38.7, 358197],
    ["NVDA", 15.839, 281841],
    ["AMD", 4.44, 495608],
    ["TSLA", 6.6374, 525203],
    ["GOOGL", 6.98, 442589],
    ["PLTR", 10.81, 238839],
    ["MSFT", 2.905, 687581],
], columns=["Ticker","Shares","Avg KRW"])

@st.cache_data(ttl=900)
def get_data(tickers):
    out = {}
    for t in tickers:
        try:
            hist = yf.download(t, period="1y", auto_adjust=True, progress=False)
            if hist.empty: continue
            if isinstance(hist.columns, pd.MultiIndex):
                close = hist["Close"][t]
            else:
                close = hist["Close"]
            close = close.dropna()
            if len(close) < 30: continue
            price = float(close.iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1])
            ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else np.nan
            high = float(close.max())
            rsi_delta = close.diff()
            gain = rsi_delta.clip(lower=0).rolling(14).mean()
            loss = (-rsi_delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = float((100 - 100/(1+rs)).iloc[-1])
            out[t] = dict(price=price, ma50=ma50, ma200=ma200, high=high, rsi=rsi)
        except Exception:
            pass
    return out

# Sidebar
with st.sidebar:
    st.header("⚙️ 현금화 설정")
    target = st.number_input("12월까지 필요한 현금 (원)", min_value=0, value=100_000_000, step=5_000_000)
    cash = st.number_input("현재 현금 (원)", min_value=0, value=0, step=5_000_000)
    loan = st.number_input("확정 대출/유입자금 (원)", min_value=0, value=0, step=5_000_000)
    emergency = st.number_input("남겨둘 비상금 (원)", min_value=0, value=10_000_000, step=1_000_000)
    buffer = st.number_input("세금/거래비용 버퍼 (원)", min_value=0, value=3_000_000, step=500_000)
    st.divider()
    st.caption("※ 실제 투자 판단 전 세금·대출·자금계획은 별도로 확인하세요.")

st.subheader("🌐 Market")

market_tickers = ["^GSPC","^NDX","^VIX","^TNX","DX-Y.NYB","KRW=X","BTC-USD"]
data = get_data(market_tickers)

cols = st.columns(4)
labels = [("^GSPC","S&P 500"),("^NDX","NASDAQ 100"),("^VIX","VIX"),("^TNX","US 10Y")]
for c,(t,l) in zip(cols, labels):
    if t in data:
        c.metric(l, f"{data[t]['price']:,.2f}")
    else:
        c.metric(l, "N/A")

cols = st.columns(3)
for c,(t,l) in zip(cols, [("DX-Y.NYB","DXY"),("KRW=X","USD/KRW"),("BTC-USD","BTC")]):
    if t in data:
        p=data[t]["price"]
        c.metric(l, f"{p:,.2f}" if t!="BTC-USD" else f"${p:,.0f}")
    else:
        c.metric(l,"N/A")

# Risk score
def risk_score(d):
    score=50
    reasons=[]
    if "^VIX" in d:
        v=d["^VIX"]["price"]
        if v<15: score-=10
        elif v<20: score-=3
        elif v<25: score+=8; reasons.append("VIX 20 이상")
        elif v<30: score+=18; reasons.append("VIX 25 이상")
        else: score+=28; reasons.append("VIX 30 이상")
    for t,name in [("^GSPC","S&P 500"),("^NDX","NASDAQ")]:
        if t in d and not np.isnan(d[t]["ma200"]):
            if d[t]["price"] < d[t]["ma200"]:
                score += 12; reasons.append(f"{name} 200DMA 하회")
            else:
                score -= 4
    if "^TNX" in d:
        y=d["^TNX"]["price"]
        if y>5.5: score+=18; reasons.append("US10Y 5.5% 이상")
        elif y>5.2: score+=12; reasons.append("US10Y 5.2% 이상")
        elif y>5.0: score+=6; reasons.append("US10Y 5.0% 이상")
    if "DX-Y.NYB" in d and d["DX-Y.NYB"]["price"]>105:
        score+=5; reasons.append("DXY 상승 부담")
    score=int(max(0,min(100,score)))
    regime="🟢 RISK ON" if score<40 else ("🟡 CAUTION" if score<60 else ("🟠 RISK OFF" if score<75 else "🔴 STRONG RISK OFF"))
    return score,regime,reasons

score,regime,reasons=risk_score(data)
st.subheader("🚦 Market Regime")
c1,c2=st.columns([1,2])
c1.metric("Risk Score", f"{score}/100")
c2.metric("현재 상태", regime)
if reasons:
    st.write("주의 요인: " + " · ".join(reasons))
else:
    st.write("현재 계산된 주요 위험 신호가 크지 않습니다.")

st.subheader("💰 Cash Plan")
need=max(0, target + emergency + buffer - cash - loan)
c1,c2,c3,c4=st.columns(4)
c1.metric("필요 현금", f"₩{target:,.0f}")
c2.metric("현재 확보", f"₩{cash+loan:,.0f}")
c3.metric("추가 매도 필요", f"₩{need:,.0f}")
c4.metric("기준일", "2026-12-18")

# Portfolio editor
st.subheader("📈 My Portfolio")
edited=st.data_editor(
    DEFAULT,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "Shares": st.column_config.NumberColumn(format="%.4f"),
        "Avg KRW": st.column_config.NumberColumn(format="₩%d"),
    }
)

ptickers=[str(x).upper().strip() for x in edited["Ticker"] if str(x).strip()]
pdata=get_data(ptickers)

rows=[]
for _,r in edited.iterrows():
    t=str(r["Ticker"]).upper().strip()
    if not t or t not in pdata: continue
    p=pdata[t]
    # Yahoo is USD for US stocks; this prototype converts using current KRW/USD.
    fx=data.get("KRW=X",{}).get("price",1400)
    value=float(r["Shares"])*p["price"]*fx
    avg=float(r["Avg KRW"])
    cost=float(r["Shares"])*avg
    ret=(value/cost-1)*100 if cost else 0
    dd=(p["price"]/p["high"]-1)*100
    risk=30
    if not np.isnan(p["ma200"]) and p["price"]<p["ma200"]: risk+=20
    if dd<-15: risk+=20
    if p["rsi"]>75: risk+=5
    rows.append([t,value,ret,dd,p["rsi"],risk])

pf=pd.DataFrame(rows,columns=["Ticker","Value","Return %","Drawdown %","RSI","Risk"])
if not pf.empty:
    pf["Weight %"]=pf["Value"]/pf["Value"].sum()*100
    priority=pf.sort_values(["Risk","Weight %"],ascending=False)
    st.dataframe(
        pf[["Ticker","Value","Weight %","Return %","Drawdown %","RSI","Risk"]]
        .style.format({"Value":"₩{:,.0f}","Weight %":"{:.1f}%","Return %":"{:.1f}%","Drawdown %":"{:.1f}%","RSI":"{:.0f}","Risk":"{:.0f}"}),
        use_container_width=True, hide_index=True
    )

    st.subheader("🎯 Sell Priority")
    for i,(_,r) in enumerate(priority.iterrows(),1):
        st.write(f"**{i}. {r['Ticker']}** — Risk {r['Risk']:.0f} / 보유비중 {r['Weight %']:.1f}%")

    st.subheader("🗓️ Monthly Sell Plan")
    weights={ "10월":0.30, "11월":0.35, "12월":0.35 }
    adj=1.0 if score<40 else (1.15 if score<60 else (1.30 if score<75 else 1.50))
    remain=need
    monthly=[]
    for m,w in weights.items():
        x=min(remain, need*w*adj)
        monthly.append([m,x])
        remain-=x
    st.dataframe(pd.DataFrame(monthly,columns=["월","권장 현금화 목표"]).style.format({"권장 현금화 목표":"₩{:,.0f}"}),use_container_width=True,hide_index=True)
else:
    st.info("포트폴리오 종목을 입력하세요.")

st.divider()
st.caption("Prototype: 규칙 기반 리스크 관리 도구이며 수익률이나 시장 방향을 보장하지 않습니다. 데이터는 Yahoo Finance 지연/가용성에 영향을 받을 수 있습니다.")
