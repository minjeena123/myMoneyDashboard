from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd
import streamlit as st

from analytics import (compute_asset_metrics, market_regime, portfolio_risk, stress_test,
    sell_priority, cash_plan, historical_backtest, fetch_prices, macro_snapshot, stock_overall_opinion)

st.set_page_config(page_title="개인 투자 의사결정 대시보드", page_icon="📈", layout="wide")
st.markdown("""
<style>
.block-container{padding:1.15rem 1.2rem 2rem;max-width:1500px}
h1{font-size:1.8rem!important} h2{font-size:1.35rem!important}
[data-testid="stMetric"]{background:rgba(128,128,128,.07);border:1px solid rgba(128,128,128,.15);padding:.7rem .8rem;border-radius:12px}
[data-testid="stMetricValue"]{font-size:1.35rem}
.small-note{font-size:.86rem;opacity:.8}
</style>""", unsafe_allow_html=True)

st.title("📈 개인 투자 의사결정 대시보드")
st.caption("시장 국면 · 종목별 추세 · 포트폴리오 위험 · 주택자금 확보 계획 | 분석 보조 도구이며 자동 주문은 실행하지 않습니다")

DEFAULT = pd.DataFrame([
    ["QQQM", 38.7, 358197, "Core ETF"], ["NVDA", 15.839, 281841, "Growth"],
    ["AMD", 4.44, 495608, "Growth"], ["TSLA", 6.6374, 525203, "High volatility"],
    ["GOOGL", 6.98, 442589, "Mega-cap"], ["PLTR", 10.81, 238839, "High volatility"],
    ["MSFT", 2.905, 687581, "Mega-cap"]], columns=["Ticker","Shares","Average Cost KRW","Category"])
with st.sidebar:
    st.header("⚙️ 설정")
    mode=st.radio("데이터 모드",["Live market data","Mock demo data"],index=0)
    st.caption("실시간 데이터는 Yahoo Finance의 지연·가용성 영향을 받습니다.")
    st.divider(); st.subheader("현금 확보 목표")
    target_date=st.date_input("현금 필요일",value=date(2026,12,18))
    required_cash=st.number_input("필요 현금 목표 (원)",min_value=0,value=100_000_000,step=5_000_000)
    cash_now=st.number_input("현재 사용 가능한 현금 (원)",min_value=0,value=0,step=5_000_000)
    confirmed_inflows=st.number_input("확정 유입 자금 (원)",min_value=0,value=0,step=5_000_000)
    emergency_reserve=st.number_input("별도 비상금 (원)",min_value=0,value=10_000_000,step=1_000_000)
    tax_buffer=st.number_input("세금·수수료 버퍼 (원)",min_value=0,value=3_000_000,step=500_000)
    st.caption("미확정 대출·예상 수입은 확정 유입 자금에 포함하지 마세요.")

with st.expander("보유 종목 및 매입가 수정",expanded=False):
    portfolio=st.data_editor(DEFAULT,num_rows="dynamic",use_container_width=True,hide_index=True,
      column_config={"Ticker":st.column_config.TextColumn("티커",required=True),
      "Shares":st.column_config.NumberColumn("보유 수량",min_value=0.0,format="%.4f",required=True),
      "Average Cost KRW":st.column_config.NumberColumn("평균 매입가(원)",min_value=0,format="₩%.0f"),
      "Category":st.column_config.SelectboxColumn("분류",options=["Core ETF","Growth","Mega-cap","High volatility","Other"])})

portfolio["Ticker"]=portfolio["Ticker"].astype(str).str.strip().str.upper()
tickers=list(dict.fromkeys([t for t in portfolio.Ticker if t]))
market_tickers=["SPY","RSP","^GSPC","^NDX","^VIX","^TNX","^IRX","DX-Y.NYB","KRW=X","BTC-USD","IEF","HYG"]
all_tickers=list(dict.fromkeys(tickers+market_tickers))
with st.spinner("시장 데이터를 불러오는 중…"):
    prices, data_source=fetch_prices(all_tickers,period="2y",mock=(mode=="Mock demo data"))
macro=macro_snapshot(prices)
regime=market_regime(prices)
risk_df,total_value,fx=portfolio_risk(portfolio,prices)
asset_metrics={}
for t in tickers:
    if t in prices and not prices[t].dropna().empty: asset_metrics[t]=compute_asset_metrics(prices[t])
cash=cash_plan(required_cash,cash_now,confirmed_inflows,emergency_reserve,tax_buffer,target_date)

# Persistent tab structure: each page has a distinct purpose.
t_overview,t_market,t_stock,t_sell,t_backtest=st.tabs(["🏠 종합 대시보드","🌐 시장 분석","🔎 종목 분석","💰 매도 계획","🧪 전략 검증"])

with t_overview:
    st.subheader("오늘의 의사결정 요약")
    if data_source.startswith("MOCK"):
        st.warning("데모 데이터입니다. 아래 수치와 신호는 실제 시장 판단에 사용하지 마세요.")
    st.caption(f"데이터: {data_source} · 종가 기준 · 최근 데이터 날짜는 공급자별로 다를 수 있음")
    cols=st.columns(4)
    cols[0].metric("시장 위험 점수",f"{regime['risk_score']}/100")
    cols[1].metric("시장 국면",regime["regime"])
    cols[2].metric("포트폴리오 평가액(추정)",f"₩{total_value:,.0f}")
    cols[3].metric("현금화 필요액",f"₩{cash['required_liquidation']:,.0f}")
    cols=st.columns(3)
    cols[0].metric("마감까지",f"{cash['days_remaining']}일")
    cols[1].metric("최대 단일 종목 비중",f"{risk_df['Weight %'].max():.1f}%" if not risk_df.empty else "—")
    cols[2].metric("상태 신뢰도",regime["confidence"])
    if cash["days_remaining"] < 0 and cash["required_liquidation"]>0: st.error("현금 필요일이 지났습니다. 날짜와 현금 목표를 확인하세요.")
    elif cash["days_remaining"]<=30 and cash["required_liquidation"]>0: st.error("마감이 30일 이내입니다. 시장 전망보다 필요한 현금 확보를 우선 검토하세요.")
    elif cash["required_liquidation"]<=0: st.success("입력 기준상 추가 현금화 목표가 충족됩니다. 위험 점수만으로 추가 매도할 필요는 없습니다.")
    else: st.info("현금 확보 목표가 남아 있습니다. 매도 계획 탭에서 종목별 위험과 일정안을 확인하세요.")
    st.subheader("시장 국면을 판단한 근거")
    st.write(" · ".join(regime["reasons"]) if regime["reasons"] else "강한 단일 방향 신호가 제한적이거나 데이터가 충분하지 않습니다.")
    st.dataframe(pd.DataFrame(regime["components"]),use_container_width=True,hide_index=True)
    if not risk_df.empty:
        st.subheader("포트폴리오 상위 보유 종목")
        st.dataframe(risk_df.sort_values("Weight %",ascending=False)[["Ticker","Value KRW","Weight %","Unrealized P/L %","52W DD %","Vol 20d %"]].style.format({"Value KRW":"₩{:,.0f}","Weight %":"{:.1f}%","Unrealized P/L %":"{:+.1f}%","52W DD %":"{:.1f}%","Vol 20d %":"{:.1f}%"}),use_container_width=True,hide_index=True)
    st.caption("점수와 종목 의견은 규칙 기반 참고치이며, 검증된 예측 모델이나 매수·매도 지시가 아닙니다.")

with t_market:
    st.subheader("시장 환경")
    snap=[("^GSPC","S&P 500"),("^NDX","NASDAQ 100"),("^VIX","VIX"),("^TNX","미국 10년물 금리"),("DX-Y.NYB","달러지수 DXY"),("KRW=X","USD/KRW")]
    cols=st.columns(3)
    for i,(ticker,label) in enumerate(snap):
        s=prices.get(ticker)
        if s is not None and not s.dropna().empty:
            v=float(s.dropna().iloc[-1]); cols[i%3].metric(label,f"{v:.2f}"+("%" if ticker=="^TNX" else ""))
        else: cols[i%3].metric(label,"데이터 없음")
    st.subheader("시장 국면 점수 구성")
    st.dataframe(pd.DataFrame(regime["components"]),use_container_width=True,hide_index=True)
    for w in regime["warnings"]: st.warning(w)
    st.subheader("시장 폭 참고 지표")
    spy,rsp=prices.get("SPY"),prices.get("RSP")
    if spy is not None and rsp is not None and len(spy.dropna())>65 and len(rsp.dropna())>65:
        sm,rm=compute_asset_metrics(spy),compute_asset_metrics(rsp)
        spread=sm.get("mom_3m_pct",np.nan)-rm.get("mom_3m_pct",np.nan)
        a,b,c=st.columns(3); a.metric("SPY 3개월 수익률",f"{sm['mom_3m_pct']:+.2f}%"); b.metric("RSP 3개월 수익률",f"{rm['mom_3m_pct']:+.2f}%"); c.metric("성과 차이(프록시)",f"{spread:+.2f}%p")
        st.info("SPY와 RSP 비교는 시장 폭의 프록시일 뿐, S&P 500 구성종목 중 이동평균선 위에 있는 비율을 나타내지 않습니다.")
    else: st.info("SPY/RSP 데이터가 없어 프록시 지표를 표시할 수 없습니다.")
    st.subheader("금리·환율·유동성")
    macro_rows=[{"지표":k,"최근 값":v.get("latest"),"1개월 변화":v.get("change_1m"),"3개월 변화":v.get("change_3m"),"상태":v.get("status"),"출처·제한":v.get("source")} for k,v in macro.items()]
    st.dataframe(pd.DataFrame(macro_rows),use_container_width=True,hide_index=True)

with t_stock:
    st.subheader("종목별 기술적 분석")
    valid=[t for t in tickers if t in prices and not prices[t].dropna().empty]
    if not valid: st.warning("분석 가능한 가격 데이터가 없습니다.")
    else:
        selected=st.selectbox("분석할 종목",valid)
        s=prices[selected].dropna(); m=asset_metrics.get(selected,compute_asset_metrics(s))
        holding=portfolio[portfolio.Ticker==selected]
        rmatch=risk_df[risk_df.Ticker==selected] if not risk_df.empty else pd.DataFrame()
        value=float(rmatch.iloc[0]["Value KRW"]) if not rmatch.empty else 0
        pnl=float(rmatch.iloc[0]["Unrealized P/L %"]) if not rmatch.empty and pd.notna(rmatch.iloc[0]["Unrealized P/L %"]) else np.nan
        c=st.columns(4); c[0].metric("최근 종가",f"${m.get('close',np.nan):,.2f}"); c[1].metric("200일선 대비",f"{m.get('dist_200_pct',np.nan):+.1f}%" if pd.notna(m.get('dist_200_pct',np.nan)) else "—"); c[2].metric("RSI(14)",f"{m.get('rsi14',np.nan):.1f}" if pd.notna(m.get('rsi14',np.nan)) else "—"); c[3].metric("평가손익률",f"{pnl:+.1f}%" if pd.notna(pnl) else "—")
        chart=pd.DataFrame({"종가":s,"5일선":s.rolling(5).mean(),"20일선":s.rolling(20).mean(),"60일선":s.rolling(60).mean(),"200일선":s.rolling(200).mean()}).tail(260)
        st.line_chart(chart,use_container_width=True)
        st.caption("종가와 이동평균선은 일별 데이터 기준입니다. 이동평균선은 차트 분석 도구이지 자동 매매 신호가 아닙니다.")
        metrics_table=pd.DataFrame([{"항목":"20일선","값":m.get("ma20")},{"항목":"50일선","값":m.get("ma50")},{"항목":"100일선","값":m.get("ma100")},{"항목":"200일선","값":m.get("ma200")},{"항목":"50일선 기울기(%/20거래일)","값":m.get("slope_50_pct")},{"항목":"MACD","값":m.get("macd")},{"항목":"MACD 시그널","값":m.get("macd_signal")},{"항목":"1개월 모멘텀(%)","값":m.get("mom_1m_pct")},{"항목":"3개월 모멘텀(%)","값":m.get("mom_3m_pct")},{"항목":"6개월 모멘텀(%)","값":m.get("mom_6m_pct")},{"항목":"12개월 모멘텀(%)","값":m.get("mom_12m_pct")},{"항목":"52주 고점 대비 낙폭(%)","값":m.get("drawdown_52w_pct")},{"항목":"20일 연환산 변동성(%)","값":m.get("vol20_ann_pct")},{"항목":"60일 연환산 변동성(%)","값":m.get("vol60_ann_pct")},{"항목":"스윙 구조(근사)","값":m.get("structure")},{"항목":"종가 기준 200일선","값":m.get("signal")}])
        st.subheader("지표와 추세 상태"); st.dataframe(metrics_table,use_container_width=True,hide_index=True)
        category=str(holding.iloc[0]["Category"]) if not holding.empty else "Other"
        weight=float(rmatch.iloc[0]["Weight %"]) if not rmatch.empty else None
        opinion=stock_overall_opinion(m,category,weight,pnl,cash["days_remaining"],cash["required_liquidation"]>0)
        st.subheader("종목별 종합 의견")
        st.markdown(f"**{opinion['view']}**")
        st.write(opinion["action"]); st.caption(opinion["reason"])
        st.subheader("분할 매도 시나리오 (가정치)")
        fraction=st.slider("가정 매도 비율 (%)",min_value=0,max_value=100,value=30,step=5)
        shares=float(holding.iloc[0]["Shares"]) if not holding.empty else 0
        a,b,c=st.columns(3); a.metric("가정 매도 수량",f"{shares*fraction/100:.4f}주"); b.metric("평가액 기준 현금화",f"₩{value*fraction/100:,.0f}"); c.metric("잔여 평가액",f"₩{value*(1-fraction/100):,.0f}")
        st.caption("세금·수수료·환전 스프레드 미반영. 지표 하나만으로 매도 여부를 결정하지 마세요.")

with t_sell:
    st.subheader("현금 확보 계획")
    st.caption("계산식: 목표 현금 + 비상금 + 세금·비용 버퍼 − 현재 가용 현금 − 확정 유입액. 비상금·버퍼는 별도 추가로 계산됩니다.")
    c=st.columns(4); c[0].metric("필요 현금 목표",f"₩{required_cash:,.0f}"); c[1].metric("추가 현금화 필요액",f"₩{cash['required_liquidation']:,.0f}"); c[2].metric("남은 날짜",f"{cash['days_remaining']}일"); c[3].metric("하루 평균 확보 필요액",f"₩{cash['daily_required']:,.0f}")
    denominator=max(required_cash+emergency_reserve+tax_buffer,1)
    progress=min(1,max(0,(cash_now+confirmed_inflows)/denominator))
    st.progress(progress,text=f"현재 현금·확정 유입 기준 충족률 {progress*100:.1f}% (보유 주식 매도 대금은 제외)")
    if cash["required_liquidation"]<=0: st.success("입력한 목표가 충족됐습니다. 목표를 넘겨 불필요하게 매도하지 않도록 확인하세요.")
    elif cash["days_remaining"]<=30: st.error("마감이 임박했습니다. 계획한 최소 현금을 우선 확보하는 시나리오를 검토하세요.")
    if not risk_df.empty:
        priority=sell_priority(portfolio,risk_df,asset_metrics,cash["days_remaining"],cash["required_liquidation"])
        st.subheader("종목별 매도 검토 우선순위")
        st.dataframe(priority,use_container_width=True,hide_index=True)
        st.caption("우선순위는 변동성·낙폭·비중·기한을 반영한 휴리스틱이며 세금 lot, 예상 세금, 실제 체결가격을 계산하지 않습니다.")
        st.subheader("매도 일정 초안")
        monthly=pd.DataFrame(cash["monthly_plan"])
        st.dataframe(monthly,use_container_width=True,hide_index=True)
        st.info("일정은 균등 분할의 출발점입니다. 시장 신호가 좋아지더라도 마감일까지 필요한 현금이 확보되지 않으면 현금 부족액을 다시 계산하세요.")
    st.subheader("포트폴리오 집중도와 스트레스 테스트")
    if not risk_df.empty:
        a,b,c=st.columns(3); a.metric("상위 3개 비중",f"{risk_df.nlargest(3,'Weight %')['Weight %'].sum():.1f}%"); b.metric("USD/KRW 환율(근사)",f"{fx:,.2f}"); c.metric("보유 종목 수",f"{len(risk_df)}")
        sh1,sh2,sh3=st.columns(3); growth=sh1.number_input("성장주 충격 (%)",value=-20.0,step=5.0); other=sh2.number_input("기타 자산 충격 (%)",value=-10.0,step=5.0); fxshock=sh3.number_input("USD/KRW 변화 (%)",value=5.0,step=1.0)
        stres=stress_test(portfolio,risk_df,growth,other,fxshock)
        st.metric("가정 시나리오 평가액 변화",f"₩{stres['change_krw']:,.0f}",delta=f"{stres['change_pct']:+.1f}%")
        st.caption("단순 충격 가정이며 예측값이 아닙니다. USD/KRW 효과도 근사치입니다.")

with t_backtest:
    st.subheader("전략 검증")
    valid=[t for t in tickers if t in prices and len(prices[t].dropna())>250]
    if not valid: st.info("백테스트에는 충분한 일별 가격 데이터가 필요합니다.")
    else:
        bt_ticker=st.selectbox("백테스트 종목",valid)
        fee=st.number_input("거래 수수료 가정 (bps)",min_value=0,max_value=200,value=10)
        slippage=st.number_input("슬리피지 가정 (bps)",min_value=0,max_value=200,value=5)
        bt=historical_backtest(prices[bt_ticker],fee_bps=fee,slippage_bps=slippage)
        if bt.get("Status")=="Insufficient data": st.warning("데이터가 충분하지 않습니다.")
        else:
            st.dataframe(pd.DataFrame([bt]),use_container_width=True,hide_index=True)
            st.caption("단순 50일선>200일선 전략입니다. 신호를 하루 지연해 룩어헤드 위험을 줄였지만, 세금·배당·워크포워드 검증은 제한적입니다. 과거 성과는 미래를 보장하지 않습니다.")
    st.subheader("데이터 품질과 제한")
    st.write(f"- 데이터 출처: {data_source}")
    st.write("- 일별 종가 기반이며 장중 신호는 제공하지 않습니다.")
    st.write("- 스윙 구조는 최근 국지적 고점·저점의 단순 규칙 기반 근사치입니다.")
    st.write("- 실제 S&P 구성종목 breadth, 실질금리, 신용스프레드는 미연결이면 데이터 없음으로 표시합니다.")
    st.write("- 매도 우선순위는 설명 가능한 휴리스틱이며 최적화된 매도 알고리즘이 아닙니다.")

st.divider()
st.caption("개인용 프로토타입 · 투자 조언 또는 수익 보장 아님 · 데이터 지연·누락 가능 · 세금은 증권사/세무 전문가 확인 필요")
