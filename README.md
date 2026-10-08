# My Market Dashboard — Cloud Version

설치 없이 웹에서 실행할 수 있도록 만든 Streamlit 버전입니다.

## 가장 쉬운 배포 방법
1. GitHub에 이 폴더를 업로드
2. Streamlit Community Cloud에서 GitHub 저장소를 연결
3. `app.py`를 Main file로 선택
4. Deploy

배포 후 받은 웹 주소를 iPhone Safari에서 열면 됩니다.
Safari의 '홈 화면에 추가'를 사용하면 앱처럼 사용할 수 있습니다.

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 주의
시장 데이터는 Yahoo Finance의 가용성과 지연에 영향을 받을 수 있습니다.
Risk Score와 Sell Priority는 참고용 규칙 기반 지표입니다.
