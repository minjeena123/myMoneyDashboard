import time
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="투자 판단 대시보드", page_icon="📊", layout="wide")
st.title("📊 투자 판단 대시보드")
st.caption("목표일 기반 현금화 모드와 목표일 없는 장기 투자 모드를 비교합니다. 자동 주문은 실행하지 않습니다.")

BASE = "https://api.nhplug.com:8443"
TOKEN_URL = BASE + "/oauth2/token"
BALANCE_URL = BASE + "/gbstock/inquiry/v1/balance"
KR_BALANCE_URL = BASE + "/krstock/inquiry/v1/assetStatus"
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

def nh_domestic_balance():
    """NH PLUG 공식 가이드의 국내_주식_조회_자산현황 API."""
    _, _, acct = secrets_values()
    r = requests.post(
        KR_BALANCE_URL,
        headers={
            "Content-Type": "application/json;charset=utf-8",
            "Authorization": f"Bearer {token()}",
        },
        json={"Input_0": {
            "act_no": acct,
            "eal_aly_cd": "2",   # 시가평가
            "aet_bse": "1",      # 순자산 기준
            "qut_dit_cd": "UNT", # 통합시세
            "aly_qut_cd": "1",  # 정규장 시세
        }},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"국내주식 자산현황 API HTTP 오류: {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("국내주식 자산현황 응답이 JSON 형식이 아닙니다.")

    rows = data.get("Output_1", [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        rows = []

    # 공식 예시 응답은 rsp_cd/rsp_msg를 최상위에 두며 Output_0/Output_1로 결과를 반환한다.
    if "Output_0" not in data and "Output_1" not in data:
        raise RuntimeError(
            f"국내주식 API 응답 오류: {data.get('rsp_cd', '코드 없음')} / "
            f"{data.get('rsp_msg', '응답 데이터 없음')}"
        )
    return data.get("Output_0", {}), rows

def from_domestic_api(rows, broker="나무증권 국내"):
    out = []
    for x in rows:
        code = str(x.get("iem_cd", "")).strip()
        # API 필드 길이가 12자리로 정의돼 있어도 국내 상장 종목코드는 앞 6자리를 사용
        import re
        if re.match(r"^\d{6}", code):
            code = code[:6]
        qty = num(x.get("itg_bnc_qty", x.get("rsdl_qty", x.get("bnc_qty", 0))))
        value = num(x.get("eal_amt", x.get("evlu_amt", 0)))
        pnl = num(x.get("eal_pls_amt", x.get("evlu_pfls_amt", 0)))
        rate = num(x.get("pft_rt", x.get("evlu_pfls_rt", 0)))
        out.append({
            "종목명": x.get("iem_nm", "이름 없음"),
            "종목코드": code,
            "시장 티커": "",
            "평가금액(원)": value,
            "손익금액(원)": pnl,
            "수익률(%)": rate,
            "보유수량": qty,
            "증권사": broker,
        })
    return pd.DataFrame(out, columns=COLS)

def from_api(rows, broker):
    out = []
    for x in rows:
        out.append({"종목명": x.get("iem_nm", "이름 없음"), "종목코드": x.get("iem_cd", ""),
                    "시장 티커": "", "평가금액(원)": num(x.get("krw_eal_amt")),
                    "손익금액(원)": num(x.get("krw_eal_pls_amt")), "수익률(%)": num(x.get("eal_pft_rt1")),
                    "보유수량": num(x.get("cns_bse_bnc_qty")), "증권사": broker})
    return pd.DataFrame(out, columns=COLS)

def _norm_name(value):
    """종목명 비교용 정규화."""
    import re
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

def resolve_ticker(name, code=""):
    """Yahoo Finance 검색으로 티커 후보를 찾는다. 확신이 낮으면 빈 문자열을 반환한다."""
    import re
    name = str(name or "").strip()
    code = str(code or "").strip().upper()

    # 국내 상장 종목은 6자리 종목코드에 .KS(코스피) 또는 .KQ(코스닥)를 붙여 검증한다.
    if code and re.fullmatch(r"\d{6}", code):
        for suffix in (".KS", ".KQ"):
            candidate = code + suffix
            try:
                hist = yf.Ticker(candidate).history(period="1mo", interval="1d")
                if not hist.empty:
                    return candidate, f"국내 종목코드로 자동 연결: {candidate}"
            except Exception:
                pass

    # API의 종목코드가 이미 미국 시장 티커처럼 보이면 먼저 검증한다.
    if code and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", code):
        try:
            hist = yf.Ticker(code).history(period="1mo", interval="1d")
            if not hist.empty:
                return code, "종목코드가 티커로 검증됨"
        except Exception:
            pass

    if not name:
        return "", "종목명이 없어 자동 검색 불가"
    try:
        search = yf.Search(name, max_results=10, news_count=0)
        quotes = getattr(search, "quotes", []) or []
    except Exception:
        quotes = []

    if not quotes:
        return "", "Yahoo Finance 검색 결과 없음"

    target = _norm_name(name)
    candidates = []
    for q in quotes:
        symbol = str(q.get("symbol", "")).strip().upper()
        qtype = str(q.get("quoteType", "")).upper()
        label = str(q.get("longname") or q.get("shortname") or "")
        label_norm = _norm_name(label)
        if not symbol or (qtype and qtype not in {"EQUITY", "ETF", "MUTUALFUND"}):
            continue
        score = 0
        if target and label_norm == target:
            score = 100
        elif target and (target in label_norm or label_norm in target):
            score = 75
        else:
            # 이름이 길게 달라지는 경우에도 정확한 단어 일치 정도만 인정
            words = [w for w in re.split(r"[^A-Z0-9]+", name.upper()) if len(w) > 2]
            hits = sum(1 for w in words if w in label.upper())
            score = min(60, hits * 15)
        exchange = str(q.get("exchange", "")).upper()
        if exchange in {"NMS", "NYQ", "NGM", "NCM", "PCX", "ASE", "NAS", "NYE"}:
            score += 5
        candidates.append((score, symbol, label))

    candidates.sort(reverse=True)
    if not candidates:
        return "", "적합한 주식/ETF 검색 결과 없음"
    # 모호한 검색 결과는 잘못된 매도 판단을 막기 위해 자동 연결하지 않는다.
    best = candidates[0]
    second_score = candidates[1][0] if len(candidates) > 1 else -1
    if best[0] >= 80 and best[0] - second_score >= 10:
        return best[1], f"자동 연결: {best[2]}"
    return "", "검색 결과가 모호함 — 후보를 확인해 티커를 직접 선택하세요"

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

def expert_perspectives(row, stats, total, mode, shortfall=0, days=999999):
    """Separate source-based investing frameworks from actual expert stock recommendations."""
    val = num(row.get("평가금액(원)"))
    weight = val / total * 100 if total > 0 else 0
    ticker = str(row.get("시장 티커", "")).strip().upper() or "티커 미연결"
    if not stats:
        return {
            "views": [
                ("하워드 막스 · 위험 관리", "가격 데이터가 없어 위험 신호를 평가할 수 없습니다. 불확실한 상태에서 강한 보유·매도 판단을 내리지 않는 것이 우선입니다."),
                ("존 머피 · 추세 추종", "가격 데이터가 없어 이동평균과 모멘텀을 평가할 수 없습니다."),
                ("CFA · 목표·유동성", "잔금 일정, 필요한 현금, 세금 및 유동성 제약을 먼저 확인하세요.")
            ],
            "summary": "판단 보류 — 시장 데이터가 없어 투자 철학별 판단을 비교할 수 없습니다.",
            "counter": "티커와 가격 데이터가 확인되면 추세·위험 신호를 다시 평가할 수 있습니다.",
            "change": "가격 데이터 확보 및 보유 종목/티커 일치 여부 확인",
            "risk_count": None,
            "trend_score": None,
        }

    close = num(stats.get("최근 종가"))
    sma20 = num(stats.get("SMA20"))
    sma50 = num(stats.get("SMA50")) if stats.get("SMA50") is not None else None
    ret20 = stats.get("20거래일 변화(%)")
    vol = stats.get("연환산 변동성(%)")
    dd = stats.get("3개월 고점 대비(%)")
    risks = []
    if close < sma20: risks.append("종가가 20일 평균선 아래")
    if sma50 is not None and close < sma50: risks.append("종가가 50일 평균선 아래")
    if ret20 is not None and ret20 <= -8: risks.append("최근 20거래일 약세")
    if vol is not None and vol >= 45: risks.append("높은 변동성")
    if dd is not None and dd <= -15: risks.append("3개월 고점 대비 큰 하락")
    if weight >= 25: risks.append("포트폴리오 내 비중 집중")

    # Independent lenses, not endorsements or direct statements by the named people.
    trend_score = int(close >= sma20) + int(sma50 is not None and close >= sma50) + int(ret20 is not None and ret20 > 0)
    trend_max = 3 if sma50 is not None and ret20 is not None else 2
    if close >= sma20 and (sma50 is None or close >= sma50) and (ret20 is None or ret20 > 0):
        trend_label = "추세 관점: 긍정"
        trend_text = "종가와 단기 이동평균의 관계가 상대적으로 우호적입니다. 이는 추세 지속을 보장하지 않으며, 이동평균은 후행 지표입니다."
    elif close < sma20 and sma50 is not None and close < sma50 and (ret20 is not None and ret20 <= 0):
        trend_label = "추세 관점: 부정"
        trend_text = "단기·중기 추세와 최근 모멘텀이 약합니다. 반등을 가정하기보다 추세가 회복되는지 확인할 필요가 있습니다."
    else:
        trend_label = "추세 관점: 혼조"
        trend_text = "추세 신호가 엇갈립니다. 단일 이동평균 돌파만으로 전량 매도·추가 매수를 결정하기보다 다음 데이터 갱신을 확인하세요."

    risk_count = int(close < sma20) + int(sma50 is not None and close < sma50) + int(ret20 is not None and ret20 <= -8) + int(vol is not None and vol >= 45) + int(dd is not None and dd <= -15) + int(weight >= 25)
    risk_label = "위험 관리 관점: 주의" if risk_count >= 3 else ("위험 관리 관점: 점검" if risk_count == 2 else "위험 관리 관점: 뚜렷한 경보 제한적")
    risk_text = ("확인된 위험 요인: " + ", ".join(risks) + ".") if risks else "설정한 주요 위험 신호가 뚜렷하게 겹치지는 않습니다. 신호 부재가 안전이나 저평가를 뜻하지는 않습니다."
    risk_text += f" 포트폴리오 비중은 {weight:.1f}%이며, 이 화면의 위험 임계치는 검증 전인 운영 가정입니다."

    if mode == "목표일 있음":
        liquidity_label = "목표·유동성 관점: 현금 계획 우선"
        liquidity_text = f"목표일까지 {days}일 남았습니다. 입력된 미확보 현금 목표는 {krw(shortfall)}입니다. 잔금에 필요한 금액은 시장 전망과 분리해 확보 계획을 세우고, 환전·매도 결제·세금 일정을 확인하세요."
    else:
        liquidity_label = "목표·유동성 관점: 투자 기간 중심"
        liquidity_text = "날짜만을 이유로 매도하지 않습니다. 목표 비중, 투자 논리, 세금, 비상자금과 위험 허용도를 점검하고 필요할 때 리밸런싱을 검토합니다."

    if risk_count >= 3 and trend_score <= 1:
        summary = "종합: 위험 축소 검토 — 위험 신호가 여러 개이고 추세 확인도 약합니다. 전량 매도를 자동 지시하는 결론은 아닙니다."
        counter = "반대 근거: 단기 약세는 일시적 조정일 수 있고, 가격 지표만으로 기업·ETF의 장기 투자 논리가 훼손됐다고 단정할 수 없습니다."
        change = "가격이 20/50일 평균선을 회복하고 모멘텀이 개선되는지, 또는 위험 신호가 완화되는지 확인"
    elif risk_count <= 1 and trend_score >= 2:
        summary = "종합: 보유 검토 — 현재 가격 추세는 상대적으로 우호적이고 설정한 위험 신호가 제한적입니다."
        counter = "반대 근거: 좋은 추세라도 고평가, 종목 집중, 향후 현금 수요 또는 급격한 시장 변화를 배제하지 못합니다."
        change = "가격이 주요 평균선 아래로 내려가거나 변동성·고점 대비 하락·집중 위험이 동시에 커지는지 확인"
    else:
        summary = "종합: 관찰 / 일부 비중 조정 검토 — 추세와 위험 신호가 혼재하거나 중간 수준입니다."
        counter = "반대 근거: 혼재 신호는 매매 비용과 잦은 매매를 유발할 수 있습니다. 장기 투자 논리와 포트폴리오 전체 비중을 함께 확인하세요."
        change = "추세 신호와 위험 신호가 같은 방향으로 더 명확해지는지 확인"

    if mode == "목표일 있음" and shortfall > 0 and days <= 45:
        summary += " 목표일이 가까우므로 필요한 잔금 현금 확보가 시장 전망보다 우선입니다."

    return {
        "views": [
            ("하워드 막스 · 위험 관리 관점", risk_label + ". " + risk_text),
            ("존 머피 · 추세 분석 관점", trend_label + ". " + trend_text),
            ("CFA · 목표·유동성 관점", liquidity_label + ". " + liquidity_text),
        ],
        "summary": summary,
        "counter": counter,
        "change": change,
        "risk_count": risk_count,
        "trend_score": f"{trend_score}/{trend_max}",
    }

def recommendation(row, stats, days, shortfall, total, mode="목표일 있음"):
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
    if mode == "목표일 없음":
        # 장기 투자 모드: 달력에 따른 강제 매도가 아니라 추세/위험 신호를 중심으로 판단
        risk_count = int(bearish) + int(weak) + int(volatile) + int(drawdown) + int(weight >= 25)
        if risk_count >= 3:
            action, pct = "위험 축소 검토", 40
            why = "목표일이 없으므로 일정에 따른 매도는 적용하지 않습니다. 여러 위험 신호가 겹쳐 일부 비중 축소를 검토합니다."
        elif risk_count == 2:
            action, pct = "일부 매도 검토", 20
            why = "목표일이 없으므로 일정에 따른 매도는 적용하지 않습니다. 위험 신호 2개가 확인되어 리밸런싱을 검토합니다."
        elif risk_count == 1:
            action, pct = "관찰 / 보유 검토", 0
            why = "위험 신호가 제한적입니다. 단일 지표만으로 매도하지 말고 추세를 관찰하세요."
        else:
            action, pct = "보유 검토", 0
            why = "현재 설정한 위험 신호 기준이 충족되지 않았습니다. 정기적으로 포트폴리오 비중과 지표를 점검하세요."
    elif days <= 14:
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
    if risk and mode == "목표일 있음" and days > 14:
        if action == "유지 또는 분할 매도": action, pct = "일부 매도", 40
        elif action == "일부 매도": pct = min(pct + 15, 75)
        elif action == "매도": pct = min(pct + 10, 90)
        why += " 추가 위험 요인: " + ", ".join(risk) + "."
    elif risk and mode == "목표일 없음":
        why += " 확인된 위험 신호: " + ", ".join(risk) + "."
    if mode == "목표일 있음":
        why += f" 미확보 현금 입력값: {krw(shortfall)}."
    return action, pct, why, "; ".join(signals)

# 목표액은 사용자가 직접 입력: 추정치로 임의 계산하지 않음
st.sidebar.header("판단 모드")
mode = st.sidebar.radio("투자 판단 기준", ["목표일 있음", "목표일 없음"], help="목표일 있음: 잔금 현금 확보 일정 중심 / 목표일 없음: 추세와 위험 신호 중심")
if mode == "목표일 있음":
    target_date = st.sidebar.date_input("잔금/현금화 목표일", value=date(2026, 12, 18))
    target_cash = st.sidebar.number_input("주식에서 확보해야 할 현금 목표액 (원)", min_value=0, value=0, step=1_000_000)
    secured_cash = st.sidebar.number_input("이미 확보한 현금 (원)", min_value=0, value=0, step=1_000_000)
    days_left = (target_date - date.today()).days
    shortfall = max(target_cash - secured_cash, 0)
else:
    target_date = None
    target_cash = 0
    secured_cash = 0
    days_left = 999999  # 일정 기반 매도 규칙은 recommendation의 장기 모드 분기에서 사용하지 않음
    shortfall = 0

st.subheader("1. 보유 자산 불러오기")
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("🔄 나무증권 국내주식 잔고 조회", type="primary", use_container_width=True):
        try:
            with st.spinner("국내주식 잔고 조회 중..."):
                summary, items = nh_domestic_balance()
            st.session_state["nh_kr_df"] = from_domestic_api(items)
            st.session_state["nh_kr_summary"] = summary
            st.session_state["nh_kr_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.success(f"국내주식 {len(items)}개 종목을 불러왔습니다.")
        except requests.exceptions.Timeout:
            st.error("국내주식 API 요청 시간이 초과되었습니다. 잠시 후 다시 시도하세요.")
        except requests.exceptions.RequestException as exc:
            st.error(f"국내주식 네트워크 오류: {type(exc).__name__}")
        except Exception as exc:
            st.error(f"국내주식 잔고 조회 실패: {type(exc).__name__}")
            st.code(str(exc))
with c2:
    if st.button("🌎 나무증권 미국 주식 잔고 조회", use_container_width=True):
        try:
            with st.spinner("해외주식 잔고 조회 중..."):
                summary, items = nh_balance()
            st.session_state["nh_df"] = from_api(items, "나무증권 해외")
            st.session_state["nh_summary"] = summary
            st.session_state["nh_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.success(f"해외주식 {len(items)}개 종목을 불러왔습니다.")
        except requests.exceptions.Timeout:
            st.error("해외주식 API 요청 시간이 초과되었습니다. 잠시 후 다시 시도하세요.")
        except requests.exceptions.RequestException as exc:
            st.error(f"해외주식 네트워크 오류: {type(exc).__name__}")
        except Exception as exc:
            st.error(f"해외주식 잔고 조회 실패: {type(exc).__name__}")
            st.code(str(exc))
with c3:
    st.caption("국내·해외 잔고는 같은 NH PLUG 키와 계좌 설정을 사용합니다. 국내 주가 이력은 Yahoo Finance에서 조회하며 실시간 시세를 보장하지 않습니다.")

if st.session_state.get("nh_time"):
    st.caption("나무증권 해외주식 마지막 조회: " + st.session_state["nh_time"])
if st.session_state.get("nh_kr_time"):
    st.caption("나무증권 국내주식 마지막 조회: " + st.session_state["nh_kr_time"])

st.markdown("**다른 증권사 CSV 업로드 (선택 사항)**")
st.caption("필수 열: 종목명, 평가금액(원). 시장 분석을 위해 시장 티커 열도 입력하세요. 예: QQQM, NVDA, AAPL, 삼성전자 005930.KS, 에코프로 086520.KQ.")
upload = st.file_uploader("보유 종목 CSV", type=["csv"])
other = pd.DataFrame(columns=COLS)
if upload:
    try:
        other = read_csv(upload)
        st.success(f"CSV {len(other)}개 종목을 읽었습니다.")
    except Exception as exc:
        st.error(f"CSV 처리 실패: {exc}")

nh = st.session_state.get("nh_df", pd.DataFrame(columns=COLS))
nh_kr = st.session_state.get("nh_kr_df", pd.DataFrame(columns=COLS))
sources = [d for d in [nh_kr, nh, other] if d is not None and not d.empty]
portfolio = pd.concat(sources, ignore_index=True) if sources else pd.DataFrame(columns=COLS)
if portfolio.empty:
    st.info("나무증권 국내/해외 잔고를 조회하거나, 다른 증권사는 선택적으로 CSV를 업로드해 주세요.")
    st.stop()

# 자동 티커 연결 결과는 rerun 이후에도 유지한다.
ticker_map = st.session_state.get("ticker_map", {})
for idx, row in portfolio.iterrows():
    map_key = f"{str(row['증권사'])}|{str(row['종목코드'])}|{str(row['종목명'])}"
    if not str(row.get("시장 티커", "") or "").strip() and ticker_map.get(map_key):
        portfolio.at[idx, "시장 티커"] = ticker_map[map_key]

st.subheader("2. 종목 정보 확인 및 티커 연결")
st.write("자동 티커 찾기는 Yahoo Finance에서 종목명/코드를 검색합니다. 이름이 모호하면 잘못 연결하지 않고 비워 둡니다. 가격 데이터는 Yahoo Finance에서 가져오며 완전한 실시간 시세가 아닐 수 있습니다.")
if st.button("🔎 보유 종목 티커 자동 찾기", use_container_width=True):
    new_map = st.session_state.get("ticker_map", {}).copy()
    progress = st.progress(0)
    status = st.empty()
    total_rows = max(len(portfolio), 1)
    for n, (idx, row) in enumerate(portfolio.iterrows(), start=1):
        current = str(row.get("시장 티커", "") or "").strip().upper()
        map_key = f"{str(row['증권사'])}|{str(row['종목코드'])}|{str(row['종목명'])}"
        if current:
            new_map[map_key] = current
        else:
            ticker, reason = resolve_ticker(row.get("종목명", ""), row.get("종목코드", ""))
            if ticker:
                new_map[map_key] = ticker
            status.write(f"{row.get('종목명', '')}: {ticker or reason}")
        progress.progress(n / total_rows)
    st.session_state["ticker_map"] = new_map
    st.success("티커 검색이 끝났습니다. 자동 연결되지 않은 종목은 아래 표에서 직접 확인해 주세요.")
    st.rerun()

edited = st.data_editor(
    portfolio, use_container_width=True, hide_index=True, num_rows="fixed",
    disabled=["종목명", "종목코드", "평가금액(원)", "손익금액(원)", "수익률(%)", "보유수량", "증권사"],
    column_config={"시장 티커": st.column_config.TextColumn("시장 티커", help="자동 연결이 안 된 경우 예: QQQM, NVDA, 005930.KS, 086520.KQ")},
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
    action, pct, why, signal = recommendation(row, s, days_left, shortfall, total, mode)
    out = row.to_dict()
    out.update({"판단": action, "제안 매도 비율(%)": pct, "판단 근거": why, "시장 신호": signal})
    if s:
        out.update(s)
    else:
        out.update({"최근 종가": None, "SMA20": None, "SMA50": None, "20거래일 변화(%)": None,
                    "연환산 변동성(%)": None, "3개월 고점 대비(%)": None, "데이터 일자": None})
    results.append(out)

rec = pd.DataFrame(results)
order = {"매도 우선 검토": 0, "매도": 1, "위험 축소 검토": 2, "일부 매도 검토": 3, "일부 매도": 4, "관찰 / 보유 검토": 5, "유지 또는 분할 매도": 6, "보유 검토": 7, "판단 보류": 8}
rec["_order"] = rec["판단"].map(order).fillna(5)
rec["비중(%)"] = rec["평가금액(원)"].apply(lambda x: num(x) / total * 100 if total > 0 else 0)
rec = rec.sort_values(["_order", "제안 매도 비율(%)", "평가금액(원)"], ascending=[True, False, False]).drop(columns="_order")

st.subheader("4. 오늘의 매도 판단")
m1, m2, m3, m4 = st.columns(4)
m1.metric("주식 평가금액", krw(total))
if mode == "목표일 있음":
    m2.metric("목표일까지", f"{days_left}일")
    m3.metric("현금 목표", krw(target_cash))
    m4.metric("미확보 현금", krw(shortfall))
    if days_left <= 45:
        st.warning("잔금일까지 45일 이하입니다. 잔금에 필요한 돈은 주식 변동성에 노출되지 않도록 실제 현금화 일정을 확인하세요.")
else:
    m2.metric("판단 기준", "시장 위험")
    m3.metric("목표일", "없음")
    m4.metric("위험 신호", "다중 지표")
    st.info("목표일 없음 모드: 일정에 따른 강제 매도는 적용하지 않습니다. 여러 위험 신호가 겹칠 때만 비중 축소를 검토합니다.")
st.caption("규칙은 선택한 모드에 따라 기한 또는 20/50일 이동평균, 최근 20거래일 수익률, 변동성, 고점 대비 하락, 종목 집중도를 참고합니다. 예측이나 수익 보장은 아닙니다.")
with st.expander("📚 전문가의 실제 공개 자료와 판단 프레임워크", expanded=True):
    st.caption("실제 공개 자료와 앱이 계산한 지표 해석은 별개입니다. 아래 자료는 전문가들이 발표한 내용이며, 특정 보유 종목에 대한 실시간 추천은 아닙니다. 링크는 원문을 직접 확인하기 위한 것입니다.")
    st.markdown("- **하워드 막스 / Oaktree** — [AI Hurtles Ahead (2026-02-26)](https://www.oaktreecapital.com/insights/memo/ai-hurtles-ahead): AI와 투자 판단에 관한 실제 메모. 개별 종목 추천으로 해석하지 않습니다.")
    st.markdown("- **하워드 막스 / Oaktree** — [Shall We Repeal the Laws of Economics – Part III (2026-09-22)](https://www.oaktreecapital.com/insights/memo/shall-we-repeal-the-laws-of-economics---part-iii): 경제 개입과 인센티브에 관한 실제 메모로, 시장 전망을 단정하는 신호가 아닙니다.")
    st.markdown("- **존 머피** — [Technical Analysis of the Financial Markets 출판사 안내](https://www.penguinrandomhouse.com/books/350647/technical-analysis-of-the-financial-markets-by-john-j-murphy/): 이동평균·추세 등 기술적 분석의 참고 문헌입니다.")
    st.markdown("- **CFA Institute** — [Asset Allocation with Real-World Constraints (2026)](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/asset-allocation-with-real-world-constraints): 투자기간, 유동성, 세금과 외부 제약을 고려하는 프레임워크입니다.")
    st.markdown("- **김승호** — [돈의 속성](https://www.yes24.com/Product/Search?domain=ALL&query=%EB%8F%88%EC%9D%98%20%EC%86%8D%EC%84%B1): 장기적 자산 축적과 기업 선별에 관한 관점을 참고합니다. 이 앱의 해석이며 저자의 특정 종목 추천이 아닙니다.")
    st.caption("현재 버전은 이 출처들을 실시간으로 자동 수집하거나 원문 전체를 요약하지 않습니다. 링크에 표시된 발행일과 원문을 직접 확인하세요.")

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
        st.markdown("**투자 철학별 독립 판단**")
        st.caption("아래 의견은 공개된 투자 프레임워크를 현재 지표에 적용한 앱의 해석입니다. 이름이 표시된 전문가가 이 종목을 직접 평가하거나 추천했다는 뜻은 아닙니다.")
        assessment = expert_perspectives(
            row, stats.get(str(row.get("시장 티커", "")).strip().upper()), total, mode,
            shortfall=shortfall, days=days_left
        )
        for perspective_title, perspective_text in assessment["views"]:
            st.markdown(f"**{perspective_title}**")
            st.write(perspective_text)
        st.markdown("**종합 판단 및 반대 근거**")
        st.info(assessment["summary"])
        st.write("**반대 관점 / 이 판단이 틀릴 수 있는 이유**")
        st.write(assessment["counter"])
        st.write("**판단을 바꿀 조건**")
        st.write(assessment["change"])
        st.caption(f"참고 지표: 위험 신호 {assessment['risk_count'] if assessment['risk_count'] is not None else '산출 불가'}개 · 추세 점수 {assessment['trend_score'] if assessment['trend_score'] is not None else '산출 불가'}")
        st.caption("제안은 규칙 기반 참고 정보입니다. 임계치는 검증 전 가정이며, 실제 주문 전에 세금·환율·수수료·결제일과 잔금 필요액을 확인하세요.")

st.download_button("📥 매도 판단 CSV 다운로드",
    data=rec.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
    file_name="cashout_recommendations.csv", mime="text/csv")

with st.expander("나무증권 API 요약"):
    kr_summary = st.session_state.get("nh_kr_summary", {})
    us_summary = st.session_state.get("nh_summary", {})
    if kr_summary:
        st.markdown("**국내주식**")
        st.write("총평가금액:", krw(kr_summary.get("tot_eal_amt")))
        st.write("총평가손익:", krw(kr_summary.get("tot_eal_pls_amt")))
        st.write("출금가능금액:", krw(kr_summary.get("drn_pbl_amt")))
    if us_summary:
        st.markdown("**해외주식**")
        st.write("평가금액 합계:", krw(us_summary.get("eal_amt_sum")))
        st.write("평가손익 합계:", krw(us_summary.get("eal_pls_sum_amt")))
    if not kr_summary and not us_summary:
        st.caption("아직 잔고 조회 결과가 없습니다.")

st.divider()
st.caption("가격 데이터는 Yahoo Finance(yfinance)를 통해 조회합니다. 데이터가 지연되거나 누락될 수 있으며, 공식 증권사 잔고/체결 가격을 대체하지 않습니다. 자동 매매는 실행하지 않습니다.")
