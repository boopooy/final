# 소소 — 스마트 소비 습관 관리

소비 내역을 기록하고, 월별 지출·예산·소비 성향을 확인하며 저축 목표를 관리하는 Streamlit 앱입니다.

## 실행 방법 (GitHub Codespaces)

```bash
python -m pip install -r requirements.txt
PYTHONPATH=src streamlit run src/final/app.py
```

실행 후 Codespaces가 안내하는 포트 8501의 브라우저 화면을 엽니다.

## 주요 기능

- 대시보드에서 월간 수입·지출·잔액, 예산 사용률, 카테고리와 최근 소비 확인
- 내역 입력 및 관리 화면에서 지출·수입 입력 전환, 카테고리 설정, 검색·필터·수정·삭제
- 월간 총예산과 카테고리별 한도 및 사용률, 80%·100% 알림
- 저축 목표 진행률과 최근 수입·지출에 기반한 달성 예상
- 예산·소비·저축 기록을 이용한 개인별 소비 개선 제안
- 소비 분석 및 리포트에서 월간 수입·지출·잔액, 전월 대비 변화와 사용자 지정 두 기간 비교
- 카테고리·월별·요일별 분석, 계획·충동 및 필수·선택 소비 비율, 주요 사용처와 소비 성향 진단

## 데이터 저장

소비·수입·카테고리·예산·저축 목표는 프로젝트의 `data/finance_data.sqlite3`에 자동 저장됩니다. 기존 `data/finance_data.json` 파일이 있으면 최초 실행 때 한 번 SQLite로 가져옵니다. 데이터 파일은 개인 금융 정보 보호를 위해 Git에서 제외됩니다. Codespace를 삭제하기 전에는 SQLite 파일을 안전한 위치에 백업하세요.

## 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
