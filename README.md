# 시니어 건강 조사팀 — 딥리서처 에이전트

어르신 · 보호자의 건강 질문 하나를 넣으면, **팀장(코디네이터)** 이 목차를 짜고 **조사원(서브에이전트) 넷** 이
자료를 나눠 읽어 각자 한 절씩 쓰고, 편집자가 이어 붙여 보고서를 만든다.

> 의학적 진단·처방이 아닙니다. 한국어 위키백과 질환 문서와 법령을 정리한 것입니다.

설계 · 지표 · 실험 결과 · 회고는 **[REPORT.md](REPORT.md)** 에 있다.

---

## 1. 설치

Python 3.12 에서 확인했다.

```bash
git clone https://github.com/nike1137-svg/senior-health-researcher.git
cd senior-health-researcher
python -m venv .venv
```

가상환경 켜기 — Windows `.venv\Scripts\activate` · macOS/Linux `source .venv/bin/activate`

```bash
pip install -r requirements.txt
```

## 2. 데모 — 키 없이 바로

```bash
python app.py
```

브라우저에서 **http://127.0.0.1:8000**

| 쪽 | 하는 일 |
|---|---|
| ① 질문 고르기 | 지난 실험 질문 6개 중 하나를 누른다 — **키 없이 · 0원** (기록을 다시 틀어 준다) |
| ② 회의실 | 팀장과 조사원 넷이 나누기 → 찾아 읽기 → 모아 정리하는 모습 |
| ③ 결과 | 「한마디로」(🔊 듣기) · 사람별 줄(누르면 읽은 자료 → 메모 → 쓴 글 → 원문 대목) · 보고서 |

| ① 질문 고르기 | ② 회의실 | ③ 결과 |
|---|---|---|
| ![질문 고르기](docs/img/1_고르기.png) | ![회의실](docs/img/2_회의실.png) | ![결과](docs/img/3_결과.png) |

### 직접 물어보기 — 내 OpenAI 키로

1. 오른쪽 위 **⚙ 키** 를 누른다
2. 키를 붙여 넣고 **「넣기」** 를 누른다 (「키 확인」 만 누르면 키가 들어가지 않는다)
3. ① 쪽 **직접 물어보기** 칸에 질문을 쓰거나 **🎤 말하기** 로 말한다 (크롬 · 엣지) → **물어보기**

- 한 번에 약 **$0.02 (약 30원)**, 한 번 상한 $0.07. 10~40초 걸린다
- 키는 이 브라우저와 서버로 가는 요청 머리에만 있다. **서버는 키를 저장하지 않는다**
- 서버는 `.env` 의 키를 **쓰지 않는다** — `app.py` 가 뜰 때 환경에서 지운다

## 3. 명령줄로 돌리기

`.env` 에 키를 넣는다 — Windows `copy .env.example .env` · macOS/Linux `cp .env.example .env` 후 `OPENAI_API_KEY` 채우기.
**`.env` 는 커밋되지 않는다.**

| 명령 | 하는 일 | 비용 |
|---|---|---|
| `python graph.py --질문 "…" --코퍼스 corpus_full.json` | 보고서 한 편 → `output/reports/_last.md` · 기록 `output/runs.jsonl` | 약 $0.02 |
| `python baseline.py --질문 "…"` | 혼자 하는 대조군 한 편 | 약 $0.02 |
| `python ablation.py --본실행 --회차 1` | 6질문 × 7설정 한 회차. **`runs.jsonl` 에 이미 있는 편은 건너뛴다** — 이 저장소 그대로면 새로 만드는 편이 없다 | 한 회차 약 $0.8 |
| `python ablation.py --집계` | 두 회차 → `output/ablation.json` | 0원 |
| `python -m tools.cost` | 지금까지 쓴 돈 (상한 $5 — 넘으면 AI 를 부르기 전에 멈춘다) | 0원 |
| `python tools/collect_corpus.py` | *(선택)* 위키백과 문서 다시 모으기 → `data/corpus.json` | 0원 (위키백과 API) |
| `python tools/collect_laws.py` | *(선택)* `corpus.json` 에 법령 6건을 더해 → `data/corpus_full.json`. `.env` 에 `LAW_OC` 필요 ([국가법령정보 OPEN API](https://open.law.go.kr) 무료 신청) | 0원 |

> 자료는 이미 `data/` 에 들어 있다. 수집 명령을 돌리면 **`data/*.json` 을 새로 쓰므로** 문서 구성이 달라질 수 있다.

### 0원 점검 — 키 없이

| 명령 | 확인하는 것 |
|---|---|
| `python ablation.py --스위치시험` | 스위치를 끄면 그 코드가 실제로 안 불리는지 |
| `python baseline.py --대조표` | 팀과 혼자가 같은 예산을 다 쓰는지 |
| `python metrics.py --자가시험` | 같은 글에 같은 문장 수 · 인용 수가 나오는지 |
| `python metrics.py --규칙확인` | 문장 · 인용 세는 규칙이 한 곳에만 있는지 |
| `python metrics.py --지표표` | 지표 · 한 줄 설명 · 먼저 의심할 장치 |
| `python graph.py --키시험` | 데모에서 받은 키가 어디에도 안 남는지 |

> `python graph.py --스텁` 도 0원이지만 `output/runs.jsonl` 에 시험 줄이 쌓인다.

## 4. 들어 있는 것

```
data/          corpus.json (위키 57건) · corpus_full.json (+ 법령 6건) · questions.json (20건 · 왜 나눌 만한가)
config.json    절수 4 · 절예산 3 · 바퀴 상한 2 · 역할 명단 · 스위치
graph.py       기획 → 배치 → 조사 × 4 → 점검 → 종합 → 평가 (LangGraph)
metrics.py     지표 — 정답표 · 판정 모델 없이
ablation.py    스위치를 하나씩 끄고 재는 실험
baseline.py    혼자 하는 대조군 (같은 자료 · 모델 · 도구 · 읽기 예산)
app.py         데모 서버 (FastAPI) · static/index.html 화면
output/        runs.jsonl (89편 기록) · ablation.json · reports/ (88편) · 4D/ (나란히 읽기 재료 5개)
tools/         코퍼스 · 법령 수집 · 질문 대조 · 비용 장부 · 4D 재료 만들기
docs/          화면 캡처 · 작업기록.md (누가 무엇을 했나 · 커밋 기록)
REPORT.md      과제 6항목 + 부록 A~I
```

- 모델 `gpt-4o-mini` · temperature 0
- 자료: [한국어 위키백과](https://ko.wikipedia.org) (CC BY-SA) · [국가법령정보센터 OPEN API](https://open.law.go.kr)
