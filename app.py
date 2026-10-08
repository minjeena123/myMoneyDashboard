
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import date
import requests
import streamlit as st

if st.button("나무 PLUG 연결 테스트"):
    try:
        response = requests.post(
            "https://api.nhplug.com:8443/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "appkey": st.secrets["NHPLUG_APP_KEY"],
                "appsecretkey": st.secrets["NHPLUG_APP_SECRET"],
                "grant_type": "client_credentials",
                "scope": "oob",
            },
            timeout=20,
        )

        if response.ok and response.json().get("access_token"):
            st.success("인증 성공! 나무 PLUG에 연결할 준비가 됐어.")
        else:
            st.error(
                f"인증 실패: HTTP {response.status_code}. "
                "API 신청 상태와 Secrets 설정을 확인해 줘."
            )
    except Exception:
        st.error("연결에 실패했어. Secrets와 네트워크 설정을 확인해 줘.")
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

import time
import requests
import pandas as pd
import streamlit as st


def get_nhplug_token():
    """세션에 유효한 토큰이 있으면 재사용."""
    now = time.time()
    token = st.session_state.get("nhplug_token")
    expires_at = st.session_state.get("nhplug_token_expires_at", 0)

    if token and now < expires_at:
        return token

    response = requests.post(
        "https://api.nhplug.com:8443/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={
            "appkey": st.secrets["NHPLUG_APP_KEY"],
            "appsecretkey": st.secrets["NHPLUG_APP_SECRET"],
            "grant_type": "client_credentials",
            "scope": "oob",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    token = data.get("access_token")
    if not token:
        raise RuntimeError("접근 토큰이 응답에 없습니다.")

    st.session_state["nhplug_token"] = token
    st.session_state["nhplug_token_expires_at"] = (
        now + int(data.get("expires_in", 86400)) - 60
    )
    return token


def get_nhplug_us_balance():
    token = get_nhplug_token()

    response = requests.post(
        "https://api.nhplug.com:8443/gbstock/inquiry/v1/balance",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Bearer {token}",
        },
        json={
            "Input_0": {
                "act_no": st.secrets["NHPLUG_ACCOUNT_NO"],
                "qut_iqr_dit_cd": "9",
                "fc_sec_trd_nat_cd": "200",
                "cur_cd": "KRW",
                "xns_dit_cd": "0",
            }
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


st.subheader("나무 PLUG 해외주식 잔고")

if st.button("나무 계좌 잔고 불러오기"):
    try:
        result = get_nhplug_us_balance()

        if result.get("rsp_cd") != "00166":
            st.error("API 조회 결과를 확인해 주세요.")
            st.write("응답 코드:", result.get("rsp_cd"))
            st.write("응답 메시지:", result.get("rsp_msg"))
        else:
            summary = result.get("Output_0", {})
            holdings = result.get("Output_1", [])

            st.metric(
                "해외주식 평가금액 합계",
                f'{summary.get("eal_amt_sum", 0):,.0f}원'
            )
            st.metric(
                "평가손익 합계",
                f'{summary.get("eal_pls_sum_amt", 0):,.0f}원'
            )

            if holdings:
                df = pd.DataFrame(holdings)
                columns = {
                    "iem_cd": "종목코드",
                    "iem_nm": "종목명",
                    "cns_bse_bnc_qty": "보유수량",
                    "sll_pbl_qty1": "매도가능수량",
                    "krw_eal_amt": "원화평가금액",
                    "krw_eal_pls_amt": "원화평가손익",
                    "eal_pft_rt1": "평가수익률(%)",
                }
                available = [
                    col for col in columns if col in df.columns
                ]
                df = df[available].rename(columns=columns)

                st.dataframe(df, use_container_width=True)
            else:
                st.info("조회된 해외주식 보유 종목이 없어.")
    except Exception:
            except requests.exceptions.HTTPError as e:
        st.error("API가 HTTP 오류를 반환했어.")
        r = e.response

        if r is not None:
            st.write("HTTP 상태 코드:", r.status_code)

            try:
                data = r.json()
                st.write("응답 코드:", data.get("rsp_cd", data.get("error", "미제공")))
                st.write("응답 메시지:", data.get("rsp_msg", data.get("error_description", "미제공")))
            except ValueError:
                st.write("응답 본문을 JSON으로 읽지 못했어.")

    except requests.exceptions.RequestException as e:
        st.error("네트워크 요청에 실패했어.")
        st.write("오류 종류:", type(e).__name__)

    except Exception as e:
        st.error("API 조회 중 오류가 발생했어.")
        st.write("오류 종류:", type(e).__name__)
        st.write("오류 메시지:", str(e))
