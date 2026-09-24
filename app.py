"""app.py — 5단계 웹 데모

    python app.py          →  http://127.0.0.1:8000

127.0.0.1 에만 뜬다. 밖에서는 Cloudflare 터널(senior.dodami-ai.com)로만 들어온다.
서버는 작성자 키를 쓰지 않는다 — 직접 물어보기는 방문자가 넣은 키로만 돈다.

과제 원문 5)
    보고서와 함께 **누가 무엇을 읽고 무엇을 썼는지**를 보여 준다.
    숫자만 보여 주는 화면은 이 프로젝트의 요점을 놓친다.

그래서 화면의 가운데는 지표가 아니라 조사관 넷의 한 줄씩이다.
    읽은 경로 → 문서마다 뽑은 메모 → 쓴 원고(인용이 읽은 문서인지 색으로) → 충분 신고
지표는 맨 아래에 작게 둔다.

탭
    재생    runs.jsonl 기록을 다시 본다 — 키 없음 · 0원
    라이브  방문자 키로 새로 돌린다 — 기록은 runs_live.jsonl 에 따로, 결과는 번호표를 받은 사람만 연다
    설정    키 넣기 (이 브라우저 · 요청 머리에만)
    소리    결과의 「한마디로」 를 읽어 준다 (edge-tts) · 질문을 말로 넣는다 (브라우저 음성 인식)
"""
from __future__ import annotations

import json
import queue
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import graph
import metrics
from tools.pairs_4d import _가까운대목

루트 = Path(__file__).resolve().parent
기록파일 = metrics.기록파일

# 데모 서버는 작성자 키(.env)를 절대 쓰지 않는다. graph 가 불러온 키를 환경에서 지워 둔다.
# 이러면 남의키 밖에서 모델을 부르는 길이 생겨도 graph.모델() 의 검사에 걸려 멈춘다 (0원).
import os  # noqa: E402
import sys  # noqa: E402
os.environ.pop("OPENAI_API_KEY", None)

# 윈도우에서 서버를 그냥 띄우면 출력이 cp949 라, graph 가 찍는 「⚠️」 같은 글자에서 실행이 멈췄다
for _흐름 in (sys.stdout, sys.stderr):
    try:
        _흐름.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
설정 = graph.설정

_질문 = {q["id"]: q for q in
        json.loads((루트 / "data" / "questions.json").read_text(encoding="utf-8"))["questions"]}
# 두 코퍼스의 위키 57건은 본문이 똑같다 (확인함). 원문 대조는 큰 쪽 하나로 한다.
_원문 = json.loads((루트 / "data" / "corpus_full.json").read_text(encoding="utf-8"))["docs"]
# 법령 서가 — 확장 코퍼스에만 있는 6건. 화면에서 조사관이 어느 서가로 가는지 가른다
_법령 = sorted(set(_원문) - set(json.loads((루트 / "data" / "corpus.json").read_text(encoding="utf-8"))["docs"]))

# 재생에 싣는 단계. 스텁 · 2~3단계의 이름 없는 실행은 뺀다.
# 라이브(방문자가 직접 물어본 것)는 싣지 않는다 — 늘 켜 두는 공개 주소라 남의 질문이 목록에 쌓여 보이면 안 된다 (작성자 결정 b)
_싣는단계 = {"본실행", "시운전", "경로시험"}
# 라이브 기록은 따로 둔다 (.gitignore). 물어본 사람만 끝날 때 받은 번호표로 결과 · 소리를 연다
라이브파일 = 루트 / "output" / "runs_live.jsonl"
_번호표꼴 = re.compile(r"^[A-Za-z0-9_-]{16,40}$")

app = FastAPI(title="어르신 건강 조사팀", docs_url=None, redoc_url=None)


# ─────────────────────────────────────────────────────────────
# 기록 읽기 — 파일이 바뀌었을 때만 다시 읽는다
# ─────────────────────────────────────────────────────────────
_캐시: dict = {"때": None, "줄": []}


def _기록들() -> list[dict]:
    때 = 기록파일.stat().st_mtime if 기록파일.exists() else None
    if 때 != _캐시["때"]:
        줄 = []
        if 기록파일.exists():
            for x in 기록파일.read_text(encoding="utf-8").splitlines():
                if x.strip():
                    줄.append(json.loads(x))
        _캐시.update(때=때, 줄=줄)
    return _캐시["줄"]


def _꼬리(r: dict) -> dict | None:
    p = (r.get("꼬리표") or "").split("|")
    if len(p) != 5 or p[0] not in _싣는단계:
        return None
    단계, 코퍼스, 설정이름, 질문ID, 회차 = p
    # 시운전은 본실행 M1 1회차와 같은 실행이다 (ablation._정규 · 작성자 승인 A)
    단계 = "본실행" if 단계 == "시운전" else 단계
    R0 = 코퍼스 == "corpus.json"
    return {"단계": 단계, "코퍼스": "위키만 (R0)" if R0 else "위키 + 법령",
            "설정": "R0 기본" if R0 else 설정이름, "질문ID": 질문ID, "회차": 회차}


# ─────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────
@app.get("/api/runs")
def 목록():
    """재생할 수 있는 실행. 같은 (설정 · 질문 · 회차) 가 둘이면 나중 것."""
    남김: dict[tuple, dict] = {}
    for i, r in enumerate(_기록들()):
        k = _꼬리(r)
        if not k:
            continue
        m = r.get("계량", {})
        q = _질문.get(k["질문ID"], {})
        남김[(k["단계"], k["설정"], k["질문ID"], k["회차"])] = {
            "id": i, **k,
            "질문": q.get("text") or m.get("질문", ""),
            "성격": q.get("type", ""),
            "근거율": m.get("근거율"),
            "메모있음": any(s.get("메모") for s in r.get("절들", [])),
        }
    return sorted(남김.values(), key=lambda x: (x["질문ID"], x["설정"], x["회차"]))


def _조각(본문: str, 읽음: set[str]) -> list[dict]:
    """원고를 문장으로 나누고, 문장 안의 인용을 떼어 표시한다.
    문장 · 인용 규칙은 metrics 에 있는 것을 그대로 쓴다 (한 곳에만 둔다)."""
    out = []
    for 문장 in metrics.문장나누기(본문):
        조각, 앞 = [], 0
        for m in metrics._인용.finditer(문장):
            if m.start() > 앞:
                조각.append({"글": 문장[앞:m.start()]})
            이름 = m.group(1).strip()
            조각.append({"인용": 이름, "읽음": 이름 in 읽음})
            앞 = m.end()
        if 앞 < len(문장):
            조각.append({"글": 문장[앞:]})
        out.append({"문장": 문장, "조각": 조각})
    return out


def _재생기록(i: int) -> dict:
    """재생에 싣는 기록만 내준다. 라이브 · 스텁 줄은 번호를 알아도 열리지 않는다."""
    줄 = _기록들()
    if not 0 <= i < len(줄) or not _꼬리(줄[i]):
        raise HTTPException(404, "그런 기록이 없습니다")
    return 줄[i]


def _라이브기록(표: str) -> dict:
    if not _번호표꼴.match(표) or not 라이브파일.exists():
        raise HTTPException(404, "그런 기록이 없습니다")
    for x in 라이브파일.read_text(encoding="utf-8").splitlines():
        if x.strip():
            r = json.loads(x)
            if r.get("계량", {}).get("표") == 표:
                return r
    raise HTTPException(404, "그런 기록이 없습니다")


@app.get("/api/runs/{i}")
def 한편(i: int):
    r = _재생기록(i)
    return _한편만들기(r, i, _꼬리(r))


@app.get("/api/라이브결과/{token}")          # 주소 속 변수 이름은 영문만 된다 (Starlette)
def 라이브결과(token: str):
    표 = token
    r = _라이브기록(표)
    k = {"단계": "라이브", "코퍼스": "위키 + 법령", "설정": "기본", "질문ID": "직접", "회차": "-"}
    return {**_한편만들기(r, None, k), "표": 표}


def _한편만들기(r: dict, i: int | None, k: dict) -> dict:
    m = r.get("계량", {})

    # 최종본에 실린 원고 — graph 의 접기() 를 그대로 쓴다 (두 번째 원고 방침이 같은 규칙으로 적용된다)
    최종 = graph.접기(r.get("절들", []))
    목차 = r.get("목차") or []
    절들 = []
    for 번호 in sorted(최종):
        s = 최종[번호]
        읽음 = s.get("읽음") or []
        절들.append({
            "번호": 번호, "절": s.get("절"), "역할": s.get("역할"),
            "시작문서": 목차[번호].get("시작문서") if 번호 < len(목차) else None,
            "읽음": 읽음, "메모": s.get("메모"),
            "충분": s.get("충분"), "부족사유": s.get("부족사유"), "한줄": s.get("한줄"),
            "바퀴": s.get("바퀴", 1),
            "인용수": len(metrics.인용뽑기(s.get("본문", ""))),
            "원고": _조각(s.get("본문", ""), set(읽음)),
        })
    # 재위임으로 버려진 원고가 있으면 따로 (4단계에선 한 번도 없었다)
    지난원고 = [{"번호": s["번호"], "바퀴": s.get("바퀴", 1), "절": s.get("절")}
               for s in r.get("절들", []) if s is not 최종.get(s["번호"])]

    return {
        "id": i, **k, "라이브": k.get("단계") == "라이브",
        "질문": _질문.get(k.get("질문ID"), {}).get("text") or m.get("질문", ""),
        "왜나눌만한가": _질문.get(k.get("질문ID"), {}).get("why_split", ""),
        "면책": 설정.get("면책", ""),
        "한마디로": r.get("한마디로", ""), "한마디로근거": r.get("한마디로근거", []),
        "목차": r.get("목차", []), "고침": r.get("고침", []),
        "절들": 절들, "지난원고": 지난원고,
        "보고서": r.get("보고서", ""),
        "계량": {x: m.get(x) for x in (
            "근거율", "격리율", "중복률", "절겹침률", "편중", "절당읽기", "절당글자", "고침수",
            "경보_인용0곳절", "경보_허위인용", "경보_한마디로근거0", "경보_한마디로빗나감", "경보_기획파싱실패",
            "바퀴", "종료", "코디글자", "읽은글자", "읽은문서수", "문장수", "보고서글자", "걸린초")},
        "비용원": round((r.get("비용달러") or 0) * 1450, 1),
        "법령": _법령, "위키수": len(_원문) - len(_법령),
        "지표설명": {x: v[1] for x, v in metrics.지표표.items() if v[0] != "버림"},
    }


@app.get("/api/원문")
def 원문대목(문서: str, 문장: str):
    """인용 하나를 눌렀을 때 — 그 문서에서 문장과 낱말이 가장 많이 겹치는 대목(후보)."""
    if 문서 not in _원문:
        return {"있음": False}
    점, 대목, 겹 = _가까운대목(문장, _원문[문서])
    return {"있음": True, "점": round(점, 2), "대목": 대목, "겹친낱말": 겹, "문서글자": len(_원문[문서])}


# ─────────────────────────────────────────────────────────────
# 키 — 사용자가 자기 OpenAI 키를 넣는다
#   키는 요청 머리(X-OpenAI-Key)로만 받는다. 파일 · 로그 · 기록 어디에도 쓰지 않는다
#   오류 메시지에 키를 되돌려 주지 않는다 (OpenAI 오류문에는 키 일부가 섞여 온다)
# ─────────────────────────────────────────────────────────────
@app.post("/api/키확인")
def 키확인(x_openai_key: str = Header(default="")):
    """모델 목록만 불러 본다 — 토큰을 쓰지 않으므로 0원."""
    try:
        graph.남의키(x_openai_key)                      # 모양 검사만 (sk- · 길이 · 공백)
    except ValueError:
        return {"됨": False, "까닭": "키 모양이 아니에요. sk- 로 시작하는 키를 붙여 넣어 주세요."}
    from openai import APIConnectionError, AuthenticationError, OpenAI, PermissionDeniedError

    try:
        이름들 = {m.id for m in OpenAI(api_key=x_openai_key.strip(), timeout=10, max_retries=0).models.list()}
    except AuthenticationError:
        return {"됨": False, "까닭": "OpenAI 가 이 키를 받지 않았어요. 키를 다시 복사해 주세요."}
    except PermissionDeniedError:
        return {"됨": False, "까닭": "이 키에는 권한이 없어요. 프로젝트 권한을 확인해 주세요."}
    except APIConnectionError:
        return {"됨": False, "까닭": "OpenAI 에 연결하지 못했어요. 인터넷을 확인해 주세요."}
    except Exception:
        return {"됨": False, "까닭": "확인하지 못했어요. 잠시 뒤 다시 해 주세요."}
    모델 = 설정["모델"]["이름"]
    if 모델 not in 이름들:
        return {"됨": False, "까닭": f"키는 맞지만 이 데모가 쓰는 모델({모델})을 쓸 수 없는 키예요."}
    return {"됨": True, "모델": 모델}


# ─────────────────────────────────────────────────────────────
# 라이브 — 사용자 키로 새로 돌리고, 진행 알림을 실시간으로 흘려보낸다 (SSE)
#   · 한 번에 한 질문만 — graph 의 모델 · 설정이 전역이라 둘이 겹치면 키가 섞인다
#   · 서버는 절대 제 키(.env)로 대신 부르지 않는다 — 키가 없으면 여기서 막는다
#   · 한 번 실행 상한 $0.07(약 100원) — graph.남의키 가 부르기 전에 검사한다
#   · 스텁=true 는 LLM 을 한 번도 부르지 않는 배선 시험용 (0원 · 키 불필요 · 기록 안 함)
# ─────────────────────────────────────────────────────────────
_라이브잠금 = threading.Lock()
라이브상한달러 = 0.07


def _사건(내용: dict) -> str:
    return "data: " + json.dumps(내용, ensure_ascii=False) + "\n\n"


@app.post("/api/라이브")
def 라이브(몸: dict = Body(...), x_openai_key: str = Header(default="")):
    질문 = str(몸.get("질문", "")).strip()
    스텁 = bool(몸.get("스텁"))
    if not 5 <= len(질문) <= 300:
        raise HTTPException(400, "질문은 5자 이상 300자 이하로 적어 주세요.")
    if not 스텁:
        try:
            graph.남의키(x_openai_key)                   # 모양만 먼저 본다 — 키가 없으면 여기서 끝
        except ValueError:
            raise HTTPException(400, "키가 없거나 모양이 아니에요. ⚙ 키 에서 넣어 주세요.")
    if not _라이브잠금.acquire(blocking=False):
        raise HTTPException(409, "다른 질문을 돌리는 중이에요. 끝난 뒤 다시 해 주세요.")

    q: queue.Queue = queue.Queue()

    def 돌리기():
        시작 = time.time()
        try:
            graph.코퍼스읽기("corpus_full.json")
            graph.스텁모드 = 스텁
            graph.알림받이 = q.put
            q.put({"종류": "시작", "법령": _법령, "위키수": len(_원문) - len(_법령), "상한원": round(라이브상한달러 * 1450)})
            if 스텁:
                # 상한 0원 가짜 키 안에서 돈다 — 스텁이 실수로 모델을 부르면 부르기 전에 멈춘다
                with graph.남의키("sk-stub-" + "0" * 24, 상한달러=0.0):
                    결과, 쓴돈 = graph.실행(질문), 0.0
            else:
                with graph.남의키(x_openai_key, 상한달러=라이브상한달러) as 남:
                    결과 = graph.실행(질문)
                    쓴돈 = 남.쓴돈
            계량 = dict(결과.get("계량", {}), 걸린초=round(time.time() - 시작, 1))
            if 스텁:
                q.put({"종류": "끝", "표": None, "비용원": 0})
                return
            표 = secrets.token_urlsafe(16)              # 추측할 수 없는 번호표 — 물어본 사람에게만 준다
            metrics.기록(
                {**결과, "코퍼스이름": "corpus_full.json", "스위치": dict(설정["스위치"])},
                dict(계량, 표=표), 비용=쓴돈,
                꼬리표=f"라이브|corpus_full.json|기본|직접|{datetime.now():%Y%m%d-%H%M%S}",
                파일=라이브파일,
            )
            q.put({"종류": "끝", "표": 표, "비용원": round(쓴돈 * 1450, 1)})
        except graph.예산초과:
            q.put({"종류": "오류", "까닭": f"한 번 실행 상한(약 {round(라이브상한달러 * 1450)}원)에 닿아 멈췄어요."})
        except Exception as e:
            from openai import AuthenticationError
            까닭 = ("OpenAI 가 이 키를 받지 않았어요. ⚙ 키 에서 확인해 주세요."
                   if isinstance(e, AuthenticationError) else "실행 중에 문제가 생겨 멈췄어요.")
            print(f"라이브 오류: {type(e).__name__}", flush=True)   # 오류문에는 키 일부가 섞일 수 있어 종류만 남긴다
            q.put({"종류": "오류", "까닭": 까닭})
        finally:
            graph.알림받이 = None
            graph.스텁모드 = False
            q.put(None)
            _라이브잠금.release()

    threading.Thread(target=돌리기, daemon=True).start()

    def 흘리기():
        while True:
            try:
                x = q.get(timeout=10)
            except queue.Empty:
                yield ": 살아 있음\n\n"          # 터널 · 프록시가 조용한 연결을 끊지 않게
                continue
            if x is None:
                return
            yield _사건(x)

    return StreamingResponse(흘리기(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────────────────────────────────────────────────
# 소리 — 「한마디로」 를 읽어 준다 (edge-tts · 무료 · 키 없음)
#   아무 글이나 받지 않고 기록 번호만 받는다. 공개 주소에서 남이 읽기 기계로 쓰는 길을 막는다
#   같은 기록은 한 번 만든 소리를 다시 쓴다
# ─────────────────────────────────────────────────────────────
목소리 = "ko-KR-SunHiNeural"
_소리: dict[str, bytes] = {}


async def _소리로(열쇠: str, 글: str):
    from fastapi.responses import Response
    if not 글:
        raise HTTPException(404, "읽어 줄 한마디로가 없습니다")
    if 열쇠 not in _소리:
        import edge_tts
        소리 = b""
        try:
            async for 조각 in edge_tts.Communicate(글, 목소리).stream():
                if 조각["type"] == "audio":
                    소리 += 조각["data"]
        except Exception as e:
            print(f"듣기 오류: {type(e).__name__}", flush=True)
            raise HTTPException(502, "소리를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.")
        if len(_소리) >= 200:
            _소리.clear()
        _소리[열쇠] = 소리
    return Response(_소리[열쇠], media_type="audio/mpeg")


@app.get("/api/듣기/{i}")
async def 듣기(i: int):
    return await _소리로(f"기록{i}", _재생기록(i).get("한마디로", ""))


@app.get("/api/듣기/라이브/{token}")
async def 듣기_라이브(token: str):
    return await _소리로(f"라이브{token}", _라이브기록(token).get("한마디로", ""))


# ─────────────────────────────────────────────────────────────
# 화면
# ─────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=루트 / "static"), name="static")


@app.get("/")
def 첫화면():
    # 화면 파일을 고쳤는데 브라우저가 예전 것을 붙들고 있던 일이 있었다 — 매번 새로 받게 한다
    return FileResponse(루트 / "static" / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    print("어르신 건강 조사팀 데모 → http://127.0.0.1:8000  (끄려면 Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
