# Market Risk & Sell Dashboard — Professional Trader Intelligence

모바일 브라우저에서 사용할 수 있는 Streamlit 웹앱 프로토타입입니다. 배포 후 iPhone Safari에서 URL을 열고 **공유 → 홈 화면에 추가**를 선택하면 앱처럼 접근할 수 있습니다.

## 포함 기능
- 일별 종가 기반 20/50/100/200 DMA, MA 기울기/거리, RSI(14), MACD, 1/3/6/12개월 모멘텀
- 52주 고점 대비 낙폭, 20/60일 연환산 실현변동성, 단순 스윙 구조
- 시장 레짐과 하위 구성요소/근거 표시
- SPY/RSP 상대 성과 프록시 (실제 S&P 500 constituent breadth와 명확히 구분)
- VIX, 미국 10년/13주 금리 프록시, DXY, USD/KRW, BTC
- 포트폴리오 비중/수익률 추정, 상관관계, 가상 스트레스 테스트
- 현금화 기한 우선 계산, 종목별 매도 우선순위 휴리스틱
- 각 보유 종목의 추세·모멘텀·변동성·낙폭·비중·평가손익을 반영한 종합의견과 대응 아이디어
- 미래 데이터 참조를 줄이기 위해 신호를 1일 lag 처리한 단순 추세 백테스트
- Mock Data 모드
- AI 자동 분석 화면 선택 시 현재 대시보드 지표·현금 계획을 OpenAI에 전송해 분석 (API 키 필요)

## 클라우드 배포
1. ZIP 압축을 풉니다.
2. GitHub에 새 저장소를 만들고 `app.py`, `analytics.py`, `requirements.txt`, `README.md`를 업로드합니다.
3. https://share.streamlit.io 에서 GitHub로 로그인 후 저장소를 선택합니다.
4. Main file path를 `app.py`로 지정하고 Deploy를 누릅니다.
5. 생성된 `*.streamlit.app` 주소를 iPhone Safari에서 엽니다.

## 로컬 실행
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## OpenAI 종합분석 설정 (선택)

AI 자동 분석 화면은 API 키 없이도 전송 데이터 미리보기와 프롬프트 복사를 제공합니다. 실제 OpenAI 호출을 켜려면 API 플랫폼에서 API 키와 결제 설정을 준비한 뒤 키를 환경변수로 설정하고 앱을 실행합니다.

```bash
export OPENAI_API_KEY="발급받은_API_키"
# 선택 사항: 기본 모델은 gpt-4.1-mini
export OPENAI_MODEL="gpt-4.1-mini"
streamlit run app.py
```

Streamlit 배포에서는 프로젝트의 `.streamlit/secrets.toml` 또는 배포 secret 설정에 다음 값을 등록할 수 있습니다. 키 파일을 저장소에 커밋하지 마세요.

```toml
OPENAI_API_KEY = "발급받은_API_키"
OPENAI_MODEL = "gpt-4.1-mini"
```

화면 위 고지를 확인하세요. `AI 자동 분석` 화면을 선택하면 티커·추정 평가액/비중·시장 지표·현금 계획 요약이 OpenAI로 전송됩니다. 각 화면 진입은 API 사용량에 따른 비용이 발생할 수 있습니다. 같은 화면에서 입력이 재실행돼도 중복 호출하지 않으며, 재요청은 `다시 분석 요청` 버튼으로 수행합니다. ChatGPT 구독과 API 결제는 별도입니다. 요청은 `store=False`를 사용하지만 이는 OpenAI의 데이터 처리 정책이나 보존 조건을 대체하지 않으므로 민감정보를 입력하지 마세요. API 키가 없거나 호출이 실패해도 나머지 대시보드는 사용할 수 있습니다.

## 데이터 한계와 주의사항
- Yahoo Finance 데이터는 가용성, 심볼 정책, 지연, 공급자 변경의 영향을 받습니다. 실시간 체결 데이터가 아닙니다.
- Yahoo `^TNX`/`^IRX`는 미 국채 수익률의 대용 지표입니다. 실질금리와 신용스프레드는 API를 연결하지 않았으므로 `Unavailable`로 표시합니다.
- 실제 S&P 500 구성종목 breadth/advance-decline/new highs-lows는 구현되어 있지 않습니다. SPY와 RSP의 성과 비교는 프록시이며 breadth 수치가 아닙니다.
- 포트폴리오 가격은 USD로 조회하고 USD/KRW를 적용해 원화 평가액을 대략 추정합니다. 브로커 표시값, 환전 스프레드, 세금 lot, 배당/수수료와 다를 수 있습니다.
- 종목별 종합의견과 Sell Priority는 기술적 지표·포트폴리오 위험에 기반한 설명 가능한 휴리스틱이며, 기업 실적·밸류에이션·뉴스를 반영한 펀더멘털 분석이나 최적화된 매도 조언이 아닙니다. 현금 목표는 입력값에 따라 달라집니다. 목표일이 가까우면 시장 전망보다 확보 일정이 우선입니다.
- 백테스트는 단순 예시이며 미래 수익을 보장하지 않습니다. 세금, 거래비용, 데이터 편향 및 전략 변경의 영향을 별도로 검토해야 합니다.
- 자동 주문 기능은 없습니다.
