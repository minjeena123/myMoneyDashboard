import time
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="12월 잔금 현금화 대시보드", page_icon="📊", layout="wide")
st.title("📊 12월 잔금용 투자 현금화 대시보드")
st.caption("보유 종목별 가격 추세와 잔금 기한을 분석해 매도/일부 매도/유지/판단 보류를 제안합니다. 자동 주문은 실행하지 않습니다.")

BASE = "https://api.nhplug.com:8443"
TOKEN_URL = BASE + "/oauth2/token"
BALANCE_URL = BASE + "/gbstock/inquiry/v1/balance"
COLS = ["종목명", "종목코드", "시장 티커", "평가금액(원)", "손익금액(원)", "수익률(%)", "보유수량", "증권사"]

def num(x, default=0.0):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip()) if x not in (None, "") else default
    except (ValueError, TypeError):
        return default

def krw(x):
    return f"₩{num(x):,.0f}"

def secrets_values():
    needed = ["NHPLUG_APP_KEY", "NHPLUG_APP_SECRET", "NHPLUG_ACCOUNT_NO"]
    missing = [k for k in needed if k not in st.secrets]
    if missing:
        raise ValueError("Streamlit Secrets 누락: " + ", ".join(missing))
    key, secret, acct = [str(st.secrets[k]).strip() for k in needed]
    if not acct.isdigit() or len(acct) != 11:
        raise ValueError("NHPLUG_ACCOUNT_NO는 숫자 11자리인지 확인하세요.")
    return key, secret, acct

def token():
    now = time.time()
    cached = st.session_state.get("nh_token")
    if cached and now < st.session_state.get("nh_token_expiry", 0):
        return cached
    key, secret, _ = secrets_values()
    r = requests.post(TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"appkey": key, "appsecretkey": secret, "grant_type": "client_credentials", "scope": "oob"},
        timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"토큰 발급 HTTP 오류: {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("토큰 응답이 JSON 형식이 아닙니다.")
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError(f"토큰 발급 실패: {data.get('error', '코드 없음')} / {data.get('error_description', data.get('rsp_msg', '메시지 없음'))}")
    st.session_state["nh_token"] = tok
    st.session_state["nh_token_expiry"] = now + max(num(data.get("expires_in"), 86400) - 120, 60)
    return tok

def nh_balance():
    key, secret, acct = secrets_values()
    r = requests.post(BALANCE_URL,
        headers={"Content-Type": "application/json; charset=UTF-8", "Authorization": f"Bearer {token()}",
                 "x-client-id": key, "x-client-secret": secret},
        json={"Input_0": {"act_no": acct, "qut_iqr_dit_cd": "9", "fc_sec_trd_nat_cd": "200", "cur_cd": "KRW", "xns_dit_cd": "0"}},
        timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"잔고 조회 HTTP 오류: {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("잔고 응답이 JSON 형식이 아닙니다.")
    if "Output_0" not in data and "Output_1" not in data:
        raise RuntimeError(f"API 응답 오류: {data.get('rsp_cd', '코드 없음')} / {data.get('rsp_msg', '메시지 없음')}")
    rows = data.get("Output_1", [])
    if isinstance(rows, dict):
        rows = [rows]
    return data.get("Output_0", {}), rows if isinstance(rows, list) else []

def from_api(rows, broker):
    out = []
    for x in rows:
        out.append({"종목명": x.get("iem_nm", "이름 없음"), "종목코드": x.get("iem_cd", ""),
                    "시장 티커": "", "평가금액(원)": num(x.get("krw_eal_amt")),
                    "손익금액(원)": num(x.get("krw_eal_pls_amt")), "수익률(%)": num(x.get("eal_pft_rt1")),
                    "보유수량": num(x.get("cns_bse_bnc_qty")), "증권사": broker})
    return pd.DataFrame(out, columns=COLS)

def read_csv(upload):
    if upload is None:
        return pd.DataFrame(columns=COLS)
    df = pd.read_csv(upload, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    if "종목명" not in df or "평가금액(원)" not in df:
        raise ValueError("CSV 필수 열은 종목명, 평가금액(원)입니다.")
    defaults = {"종목코드": "", "시장 티커": "", "손익금액(원)": 0, "수익률(%)": 0, "보유수량": 0, "증권사": "기타 증권사"}
    for c, v in defaults.items():
        if c not in df:
            df[c] = v
    df = df[COLS].copy()
    for c in ["평가금액(원)", "손익금액(원)", "수익률(%)", "보유수량"]:
        df[c] = df[c].apply(num)
    df["시장 티커"] = df["시장 티커"].fillna("").astype(str).str.strip().str.upper()
    return df

def market_stats(ticker):
    try:
        h = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=True)
        close = h["Close"].dropna()
        if len(close) < 20:
            return None
        last = float(close.iloc[-1])
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        prev = float(close.iloc[-21]) if len(close) >= 21 else None
        ret20 = (last / prev - 1) * 100 if prev else None
        returns = close.pct_change().dropna()
        vol = float(returns.tail(20).std() * (252 ** 0.5) * 100) if len(returns) >= 10 else None
        high = float(close.tail(63).max())
        dd = (last / high - 1) * 100 if high else None
        return {"최근 종가": last, "SMA20": sma20, "SMA50": sma50, "20거래일 변화(%)": ret20,
                "연환산 변동성(%)": vol, "3개월 고점 대비(%)": dd, "데이터 일자": str(close.index[-1].date())}
    except Exception:
        return None

def recommendation(row, stats, days, shortfall, total):
    val = num(row["평가금액(원)"])
    ticker = str(row["시장 티커"]).strip().upper()
    weight = val / total * 100 if total > 0 else 0
    if val <= 0:
        return "판단 보류", 0, "평가금액이 0 이하입니다.", "데이터 확인 필요"
    if not ticker or stats is None:
        return "판단 보류", 0, "시장 티커/가격 데이터를 확인할 수 없습니다. 티커를 입력하고 다시 분석하세요.", "시장 데이터 없음"
    bearish = stats["최근 종가"] < stats["SMA20"] and stats["SMA50"] is not None and stats["최근 종가"] < stats["SMA50"]
    weak = stats["20거래일 변화(%)"] is not None and stats["20거래일 변화(%)"] <= -8
    volatile = stats["연환산 변동성(%)"] is not None and stats["연환산 변동성(%)"] >= 45
    drawdown = stats["3개월 고점 대비(%)"] is not None and stats["3개월 고점 대비(%)"] <= -15
    signals = []
    if bearish: signals.append("종가가 20일·50일 평균선 아래")
    elif stats["최근 종가"] < stats["SMA20"]: signals.append("종가가 20일 평균선 아래")
    if weak: signals.append("20거래일 하락률 8% 이상")
    if volatile: signals.append("연환산 변동성 45% 이상")
    if drawdown: signals.append("3개월 고점 대비 15% 이상 하락")
    if weight >= 25: signals.append("포트폴리오 비중 25% 이상")
    if not signals: signals = ["위험 신호 기준 미충족"]
    if days <= 14:
        action, pct = "매도 우선 검토", 100
        why = "목표일까지 2주 이하입니다. 잔금에 필요한 자금이라면 반등을 기다리기보다 현금 확보를 우선 검토하세요."
    elif days <= 45:
        action, pct = "매도", 75
        why = "목표일까지 45일 이하이므로 단기 변동 위험을 낮추기 위해 현금화를 우선 검토합니다."
    elif days <= 90:
        action, pct = "일부 매도", 50
        why = "목표일까지 90일 이하입니다. 단계적으로 현금 비중을 높이는 방안을 검토합니다."
    else:
        action, pct = "유지 또는 분할 매도", 25
        why = "목표일까지 시간이 남아 있습니다. 계획에 따라 분할 현금화를 검토합니다."
    risk = []
    if bearish: risk.append("추세 약세")
    if weak: risk.append("최근 모멘텀 약세")
    if volatile: risk.append("높은 변동성")
    if drawdown: risk.append("고점 대비 큰 하락")
    if weight >= 25: risk.append("종목 집중")
    if risk and days > 14:
        if action == "유지 또는 분할 매도": action, pct = "일부 매도", 40
        elif action == "일부 매도": pct = min(pct + 15, 75)
        elif action == "매도": pct = min(pct + 10, 90)
        why += " 추가 위험 요인: " + ", ".join(risk) + "."
    why += f" 미확보 현금 입력값: {krw(shortfall)}."
    return action, pct, why, "; ".join(signals)

# 목표액은 사용자가 직접 입력: 추정치로 임의 계산하지 않음
st.sidebar.header("현금화 계획")
target_date = st.sidebar.date_input("잔금/현금화 목표일", value=date(2026, 12, 18))
target_cash = st.sidebar.number_input("주식에서 확보해야 할 현금 목표액 (원)", min_value=0, value=0, step=1_000_000)
secured_cash = st.sidebar.number_input("이미 확보한 현금 (원)", min_value=0, value=0, step=1_000_000)
days_left = (target_date - date.today()).days
shortfall = max(target_cash - secured_cash, 0)

st.subheader("1. 보유 자산 불러오기")
c1, c2 = st.columns([1, 2])
with c1:
    if st.button("🔄 나무증권 미국 주식 잔고 조회", type="primary", use_container_width=True):
        try:
            with st.spinner("잔고 조회 중..."):
                summary, items = nh_balance()
            st.session_state["nh_df"] = from_api(items, "나무증권")
            st.session_state["nh_summary"] = summary
            st.session_state["nh_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.success(f"{len(items)}개 종목을 불러왔습니다.")
        except requests.exceptions.Timeout:
            st.error("API 요청 시간이 초과되었습니다. 잠시 후 다시 시도하세요.")
        except requests.exceptions.RequestException as exc:
            st.error(f"네트워크 오류: {type(exc).__name__}")
        except Exception as exc:
            st.error(f"잔고 조회 실패: {type(exc).__name__}")
            st.code(str(exc))
with c2:
    st.caption("티커는 증권사 종목코드와 다를 수 있어 자동 추정하지 않습니다. 잔고 조회 후 티커를 직접 연결해 주세요.")

if st.session_state.get("nh_time"):
    st.caption("나무증권 마지막 조회: " + st.session_state["nh_time"])

st.markdown("**다른 증권사 CSV 업로드**")
st.caption("필수 열: 종목명, 평가금액(원). 시장 분석을 위해 시장 티커 열도 입력하세요. 예: QQQM, NVDA, AAPL.")
upload = st.file_uploader("보유 종목 CSV", type=["csv"])
other = pd.DataFrame(columns=COLS)
if upload:
    try:
        other = read_csv(upload)
        st.success(f"CSV {len(other)}개 종목을 읽었습니다.")
    except Exception as exc:
        st.error(f"CSV 처리 실패: {exc}")

nh = st.session_state.get("nh_df", pd.DataFrame(columns=COLS))
sources = [d for d in [nh, other] if d is not None and not d.empty]
portfolio = pd.concat(sources, ignore_index=True) if sources else pd.DataFrame(columns=COLS)
if portfolio.empty:
    st.info("잔고를 조회하거나 다른 증권사 CSV를 업로드해 주세요.")
    st.stop()

st.subheader("2. 종목 정보 확인 및 티커 연결")
st.write("‘시장 티커’ 열을 직접 입력해 주세요. 티커가 없거나 가격 데이터 조회가 안 되면 매도/유지를 임의로 추천하지 않고 판단 보류합니다.")
edited = st.data_editor(
    portfolio, use_container_width=True, hide_index=True, num_rows="fixed",
    disabled=["종목명", "종목코드", "평가금액(원)", "손익금액(원)", "수익률(%)", "보유수량", "증권사"],
    column_config={"시장 티커": st.column_config.TextColumn("시장 티커", help="예: QQQM, NVDA, AAPL")},
    key="holdings_editor"
)
edited["시장 티커"] = edited["시장 티커"].fillna("").astype(str).str.strip().str.upper()
for col in ["평가금액(원)", "손익금액(원)", "수익률(%)", "보유수량"]:
    edited[col] = edited[col].apply(num)

st.subheader("3. 시장 지표 분석")
if st.button("📈 시장 지표 분석 및 매도 판단 생성", type="primary"):
    stats = {}
    for ticker in sorted(set(t for t in edited["시장 티커"] if t)):
        with st.spinner(f"{ticker} 가격 데이터 조회 중..."):
            stats[ticker] = market_stats(ticker)
    st.session_state["market_stats"] = stats
    st.session_state["analysis_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

stats = st.session_state.get("market_stats", {})
if not stats:
    st.info("티커를 입력한 뒤 시장 지표 분석 버튼을 눌러 주세요.")
    st.stop()
if st.session_state.get("analysis_time"):
    st.caption("마지막 시장 분석: " + st.session_state["analysis_time"])

total = edited["평가금액(원)"].sum()
results = []
for _, row in edited.iterrows():
    ticker = str(row["시장 티커"]).strip().upper()
    s = stats.get(ticker) if ticker else None
    action, pct, why, signal = recommendation(row, s, days_left, shortfall, total)
    out = row.to_dict()
    out.update({"판단": action, "제안 매도 비율(%)": pct, "판단 근거": why, "시장 신호": signal})
    if s:
        out.update(s)
    else:
        out.update({"최근 종가": None, "SMA20": None, "SMA50": None, "20거래일 변화(%)": None,
                    "연환산 변동성(%)": None, "3개월 고점 대비(%)": None, "데이터 일자": None})
    results.append(out)

rec = pd.DataFrame(results)
order = {"매도 우선 검토": 0, "매도": 1, "일부 매도": 2, "유지 또는 분할 매도": 3, "판단 보류": 4}
rec["_order"] = rec["판단"].map(order).fillna(5)
rec["비중(%)"] = rec["평가금액(원)"].apply(lambda x: num(x) / total * 100 if total > 0 else 0)
rec = rec.sort_values(["_order", "제안 매도 비율(%)", "평가금액(원)"], ascending=[True, False, False]).drop(columns="_order")

st.subheader("4. 오늘의 매도 판단")
m1, m2, m3, m4 = st.columns(4)
m1.metric("주식 평가금액", krw(total))
m2.metric("목표일까지", f"{days_left}일")
m3.metric("현금 목표", krw(target_cash))
m4.metric("미확보 현금", krw(shortfall))
if days_left <= 45:
    st.warning("잔금일까지 45일 이하입니다. 잔금에 필요한 돈은 주식 변동성에 노출되지 않도록 실제 현금화 일정을 확인하세요.")
st.caption("규칙은 기한, 20/50일 이동평균, 최근 20거래일 수익률, 변동성, 고점 대비 하락, 종목 집중도를 사용합니다. 예측이나 수익 보장은 아닙니다.")

display_cols = ["판단", "종목명", "시장 티커", "평가금액(원)", "비중(%)", "제안 매도 비율(%)",
                "판단 근거", "시장 신호", "20거래일 변화(%)", "연환산 변동성(%)", "3개월 고점 대비(%)", "데이터 일자"]
st.dataframe(rec[display_cols].style.format({
    "평가금액(원)": "₩{:,.0f}", "비중(%)": "{:.2f}%", "제안 매도 비율(%)": "{:.0f}%",
    "20거래일 변화(%)": "{:.2f}%", "연환산 변동성(%)": "{:.2f}%", "3개월 고점 대비(%)": "{:.2f}%"
}, na_rep="—"), use_container_width=True, hide_index=True)

st.subheader("5. 종목별 상세 판단")
for _, row in rec.iterrows():
    with st.expander(f"{row['판단']} · {row['종목명']} ({row['시장 티커'] or '티커 미연결'})",
                     expanded=row["판단"] in ["매도 우선 검토", "매도", "일부 매도"]):
        a, b, c = st.columns(3)
        a.metric("평가금액", krw(row["평가금액(원)"]))
        b.metric("제안 매도 비율", f"{num(row['제안 매도 비율(%)']):.0f}%")
        c.metric("현재 수익률", f"{num(row['수익률(%)']):.2f}%")
        st.write("**판단 근거**")
        st.write(row["판단 근거"])
        st.write("**시장 신호**")
        st.write(row["시장 신호"])
        if pd.notna(row.get("최근 종가")):
            st.write(f"최근 종가: {row['최근 종가']:.2f} · 20일 평균: {row['SMA20']:.2f}")
            if pd.notna(row.get("SMA50")):
                st.write(f"50일 평균: {row['SMA50']:.2f}")
        st.caption("제안은 규칙 기반 참고 정보입니다. 매도 전 세금, 환율, 수수료, 결제일과 잔금 필요액을 확인하세요.")

st.download_button("📥 매도 판단 CSV 다운로드",
    data=rec.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
    file_name="cashout_recommendations.csv", mime="text/csv")

with st.expander("나무증권 API 요약"):
    summary = st.session_state.get("nh_summary", {})
    if summary:
        st.write("평가금액 합계:", krw(summary.get("eal_amt_sum")))
        st.write("평가손익 합계:", krw(summary.get("eal_pls_sum_amt")))
    else:
        st.caption("아직 잔고 조회 결과가 없습니다.")

st.divider()
st.caption("가격 데이터는 Yahoo Finance(yfinance)를 통해 조회합니다. 데이터가 지연되거나 누락될 수 있으며, 공식 증권사 잔고/체결 가격을 대체하지 않습니다. 자동 매매는 실행하지 않습니다.")
