"""ablation.py — 스위치를 하나씩 끄고 재는 실험

지금 들어 있는 것
    --스위치시험   스위치를 끄면 그 장치의 코드가 실제로 안 불리는지 코드가 판정한다 (0원)

곧 들어올 것 (4-C)
    같은 질문으로 설정을 바꿔 가며 보고서를 여러 편 만들고 output/ablation.json 에 모은다

────────────────────────────────────────────────────────────
스위치시험이 필요한 이유
    과제가 든 흔한 사고 둘째 — 「스위치를 껐다고 로그만 찍고 실제 코드 경로는 그대로」.
    4-C 에서 「배정끔」 보고서가 기본과 똑같이 나오면 두 가지 뜻일 수 있다.
      배정이 값을 안 했다   /   배정이 안 꺼졌다
    이 시험이 없으면 둘을 가를 수 없다.

켜짐도 같이 시험하는 이유
    꺼짐만 보면 속는다. 「재위임을 끄니 1바퀴로 끝났다」 는 루프가 원래 고장 나서 켜도
    1바퀴로 끝나는 것일 수 있다. 그래서 스위치마다 켜짐·꺼짐을 둘 다 돌려
    결과가 갈리는지를 본다.

돈이 안 드는 이유
    진짜 AI 대신 정해진 답만 돌려주는 가짜 응답기를 graph.부르기 자리에 끼운다.
    그래프의 나머지 코드(기획 검증 · 팬아웃 · 조사 루프 · 점검 · 종합)는 진짜로 돈다.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys

import graph

질문 = "어머님이 깜빡하시는데 치매인가요?"
코퍼스 = "corpus_full.json"

# 가짜 기획이 돌려줄 목차 — 네 절 모두 확장 코퍼스에 실제로 있는 문서
가짜목차 = [
    {"절": "치매",         "역할": "증상 담당", "시작문서": "치매",         "물음": "초기 증상은?"},
    {"절": "섬망",         "역할": "진단 담당", "시작문서": "섬망",         "물음": "어떻게 구별하나?"},
    {"절": "알츠하이머병", "역할": "원인 담당", "시작문서": "알츠하이머병", "물음": "왜 생기나?"},
    {"절": "치매관리법",   "역할": "제도 담당", "시작문서": "치매관리법",   "물음": "무엇을 받을 수 있나?"},
]

# 두 번째 원고 시험용 — 1바퀴는 인용이 멀쩡하고, 2바퀴는 인용을 빠뜨린다
멀쩡한원고 = "첫 문장이다 «치매». 둘째 문장이다 «치매»."
빠뜨린원고 = "인용을 빠뜨린 문장이다. 또 빠뜨린 문장이다."


# ─────────────────────────────────────────────────────────────
# 가짜 응답기 — 무엇을 받았는지 전부 적어 두고, 정해진 답만 돌려준다
# ─────────────────────────────────────────────────────────────
class 녹음기:
    def __init__(self, 부족시키기: bool = False):
        self.부족시키기 = 부족시키기     # True 면 1바퀴 원고가 전부 「부족」 신고
        self.프롬프트: list[tuple[str, str]] = []
        self.피하기: list[set[str]] = []

    def 부르기(self, 프롬프트: str, 태그: str) -> str:
        self.프롬프트.append((태그, 프롬프트))
        if 태그 == "기획":
            return json.dumps({"목차": 가짜목차}, ensure_ascii=False)
        if 태그.startswith("원고"):
            첫바퀴 = "_1바퀴" in 태그
            return json.dumps({
                "본문": 멀쩡한원고 if 첫바퀴 else 빠뜨린원고,
                "충분": not (self.부족시키기 and 첫바퀴),
                "부족": "가짜 부족 신고" if (self.부족시키기 and 첫바퀴) else "",
                "한줄": "가짜 한 줄",
            }, ensure_ascii=False)
        if 태그 == "편집자":
            return json.dumps({"한마디로": "가짜", "근거": ["치매"],
                               "머리말": "", "맺음말": ""}, ensure_ascii=False)
        return "가짜 메모"      # 읽기 · 고르기


@contextlib.contextmanager
def 설정바꿔(녹, **바꿀것):
    """graph 의 설정과 함수를 잠깐 바꿨다가 반드시 되돌린다.
    수업 3-Z 처럼 설정을 바꿔 돌린 뒤에는 꼭 원래대로 돌려놓는다.
    안 돌려놓으면 다음 실험이 바뀐 설정 그대로 돈다."""
    원래설정 = copy.deepcopy(graph.설정)
    원래부르기, 원래후보목록, 원래스텁 = graph.부르기, graph.후보목록, graph.스텁모드

    def 후보목록_엿듣기(읽음, 피하기):
        녹.피하기.append(set(피하기))
        return 원래후보목록(읽음, 피하기)

    try:
        for 키, 값 in 바꿀것.items():
            if 키 == "두번째원고":
                graph.설정["두번째원고"]["방식"] = 값
            else:
                graph.설정["스위치"][키] = 값
        graph.부르기 = 녹.부르기
        graph.후보목록 = 후보목록_엿듣기
        graph.스텁모드 = False            # 진짜 코드 경로를 탄다. 돈은 가짜 응답기가 막는다
        graph.코퍼스읽기(코퍼스)
        yield
    finally:
        graph.설정.clear()
        graph.설정.update(원래설정)
        graph.부르기, graph.후보목록, graph.스텁모드 = 원래부르기, 원래후보목록, 원래스텁


def 돌리기(녹, **바꿀것) -> dict:
    with 설정바꿔(녹, **바꿀것), contextlib.redirect_stdout(io.StringIO()):
        return graph.실행(질문)


# ─────────────────────────────────────────────────────────────
# 스위치마다 「밖에서 볼 수 있는 흔적」 하나씩
# ─────────────────────────────────────────────────────────────
def 흔적_배정(결과, 녹):
    """조사관의 첫 읽기가 배정받은 시작문서와 같은 절 수"""
    # 절 번호로 짝을 짓는다. 제목으로 지으면 제목이 같은 절끼리 섞인다 (REPORT 부록 F)
    시작 = {i: t["시작문서"] for i, t in enumerate(결과["목차"])}
    같음 = [s for s in 결과["sections"] if s["바퀴"] == 1
            and s["읽음"] and s["읽음"][0] == 시작.get(s["번호"])]
    return len(같음), f"첫 읽기 = 시작문서 {len(같음)}/{len(시작)}절"


def 흔적_구역(결과, 녹):
    """조사관이 받은 피하기 목록 중 비어 있지 않은 것의 수"""
    찬것 = sum(1 for p in 녹.피하기 if p)
    return 찬것, f"피하기가 찬 호출 {찬것}/{len(녹.피하기)}번"


def 흔적_역할(결과, 녹):
    """보낸 프롬프트 안에 역할 이름이 나온 곳의 수"""
    이름들 = graph.설정["역할명단"]
    곳 = sum(p.count(이름) for _, p in 녹.프롬프트 for 이름 in 이름들)
    return 곳, f"프롬프트 속 역할 이름 {곳}곳"


def 흔적_재위임(결과, 녹):
    """돈 바퀴 수에서 1을 뺀 것 (0 이면 루프가 안 돈 것)"""
    바퀴 = 결과.get("바퀴", 0)
    원고 = sum(1 for t, _ in 녹.프롬프트 if t.startswith("원고"))
    return 바퀴 - 1, f"바퀴 {바퀴} · 원고 {원고}편 · 종료({결과.get('종료')})"


def 흔적_두번째원고(결과, 녹):
    """최종 보고서에 실린 절 중 인용을 빠뜨린 원고의 수 (0 이면 멀쩡한 원고를 지켰다)

    graph.접기() 를 여기서 다시 부르면 안 된다 — 이 함수는 설정을 되돌린 뒤에 불리므로
    「덮어쓰기」 시험도 되돌려진 설정(인용밀도)으로 접혀 버린다 (처음에 실제로 그렇게 틀렸다).
    그래서 실행 도중에 만들어진 보고서를 본다. 독자가 받는 것도 이것이다.
    """
    보고서 = 결과.get("보고서", "")
    빠뜨린 = 보고서.count(빠뜨린원고)
    멀쩡 = 보고서.count(멀쩡한원고)
    return 빠뜨린, f"보고서에 실린 절 — 멀쩡 {멀쩡}편 · 인용 빠뜨린 것 {빠뜨린}편"


# (이름, 흔적 함수, 켜짐 설정, 꺼짐 설정, 부족시키기, 켜짐일 때 흔적이 있어야 하나)
시험들 = [
    ("배정",   흔적_배정,   {"배정": True},   {"배정": False},   False, True),
    ("구역",   흔적_구역,   {"구역": True},   {"구역": False},   False, True),
    ("역할",   흔적_역할,   {"역할": True},   {"역할": False},   False, True),
    ("재위임", 흔적_재위임, {"재위임": True}, {"재위임": False}, True,  True),
]


def 스위치시험() -> int:
    print("스위치를 켜고 끄며 흔적이 갈리는지 봅니다. 진짜 AI 는 한 번도 안 부릅니다 (0원).\n")
    머리 = f"{'스위치':<8} {'켜짐':<34} {'꺼짐':<34} 판정"
    print(머리)
    print("-" * 90)

    실패 = 0
    for 이름, 흔적, 켬, 끔, 부족, _ in 시험들:
        녹켬, 녹끔 = 녹음기(부족), 녹음기(부족)
        n켬, 말켬 = 흔적(돌리기(녹켬, **켬), 녹켬)
        n끔, 말끔 = 흔적(돌리기(녹끔, **끔), 녹끔)

        # 켜짐 → 흔적이 있다  그리고  꺼짐 → 흔적이 줄었다 (배정은 우연히 겹치는 절이 있을 수 있어 '줄었다')
        if 이름 == "배정":
            ok = n켬 == len(가짜목차) and n끔 < n켬
        else:
            ok = n켬 > 0 and n끔 == 0
        if not ok:
            실패 += 1
            if n켬 == 0:
                원인 = "켜도 흔적이 없음 — 장치가 원래 안 돈다"
            else:
                원인 = "껐는데 흔적이 남음 — 안 꺼졌다"
        print(f"{이름:<8} {말켬:<34} {말끔:<34} {'✅' if ok else '❌ ' + 원인}")

    # 두 번째 원고 — 재위임이 돌 때만 탈 수 있다. 방식을 바꿔 가며 결과가 갈리는지 본다
    print()
    print("■ 두 번째 원고 처리 — 1바퀴는 인용이 멀쩡하고 2바퀴는 인용을 빠뜨리게 했다")
    녹1, 녹2 = 녹음기(True), 녹음기(True)
    n밀, 말밀 = 흔적_두번째원고(돌리기(녹1, 재위임=True, 두번째원고="인용밀도"), 녹1)
    n덮, 말덮 = 흔적_두번째원고(돌리기(녹2, 재위임=True, 두번째원고="덮어쓰기"), 녹2)
    ok = n밀 == 0 and n덮 > 0
    if not ok:
        실패 += 1
    print(f"  인용밀도 (우리 방식)  {말밀}")
    print(f"  덮어쓰기 (수업 방식)  {말덮}")
    print(f"  {'✅ 인용밀도는 멀쩡한 원고를 지켰고, 덮어쓰기는 지웠다' if ok else '❌ 두 방식이 갈리지 않는다'}")

    print()
    if 실패:
        print(f"❌ {실패}건 실패. 4-C 로 가기 전에 고쳐야 합니다.")
    else:
        print("✅ 스위치 네 개가 켜면 일하고 끄면 멈춥니다. 두 번째 원고 방침도 실제로 탑니다.")
    return 1 if 실패 else 0


# ═════════════════════════════════════════════════════════════
# 4-C 실험 — 같은 질문으로 설정을 바꿔 가며 보고서를 여러 편 만든다
#
#   계획과 예측은 REPORT 부록 E (2026-09-23 17:09 에 적음. 이 코드는 그 뒤에 돈다).
#
#   지킬 것
#     한 번에 하나만 끈다   둘을 같이 끄면 어느 쪽 때문인지 가를 수 없다 (수업 3-AD)
#     켜고 반드시 되돌린다  안 되돌리면 다음 실험이 바뀐 설정으로 돈다 (수업 3-Z)
#     끊겨도 이어서         이미 만든 (코퍼스·설정·질문·회차) 는 건너뛴다. 돈을 두 번 안 쓴다
#     두 회차               한 번 돌린 결과로 단정하지 않는다 (REPORT 부록 G-2)
# ═════════════════════════════════════════════════════════════
import time
from pathlib import Path

import metrics

확장, R0 = "corpus_full.json", "corpus.json"

# 설정 — graph.설정 에 덮어쓸 것. "혼자" 는 baseline.py 로 돈다
실험설정: dict[str, dict] = {
    "기본":     {},
    "배정끔":   {"스위치": {"배정": False}},
    "구역끔":   {"스위치": {"구역": False}},
    "역할끔":   {"스위치": {"역할": False}},
    "혼자":     {"혼자": True},
    "절예산4":  {"절예산": 4},
}
경로시험설정 = {"절예산": 1}                 # 재위임이 실제 AI 에서 도는지 — 부록 E-2

실험질문 = ["S2", "M1", "M7", "M3", "T1", "T5"]   # REPORT 부록 E · 1단계 예측을 검증할 질문
경로시험질문 = ["M1", "T1"]
회차들 = [1, 2]

# 오늘 실제 실행에서 잰 1편 비용(원). 본 실행 전에 남은 예산을 따지는 데만 쓴다
어림비용 = {"기본": 32, "배정끔": 32, "구역끔": 32, "역할끔": 32,
           "혼자": 30, "절예산4": 42, "경로시험": 20}

보고서방 = Path(graph.루트) / "output" / "reports"
집계파일 = Path(graph.루트) / "output" / "ablation.json"


def _질문글(qid: str) -> str:
    qs = json.loads((Path(graph.루트) / "data" / "questions.json").read_text(encoding="utf-8"))
    return next(q["text"] for q in qs["questions"] if q["id"] == qid)


def _꼬리표(단계: str, 코퍼스: str, 설정이름: str, qid: str, 회차: int) -> str:
    return f"{단계}|{코퍼스}|{설정이름}|{qid}|{회차}"


def _정규(꼬리표: str) -> str:
    """시운전 편을 본실행 편으로 친다 — 작성자 승인 A (2026-09-23).

    시운전(M1 × 6설정 × 1회차)은 본실행의 M1 1회차와 같은 실행이다.
    시운전 뒤에 실행 결과를 바꾸는 파일(graph.py · baseline.py · metrics.py · config.json ·
    tools/cost.py · corpus_full.json)이 하나도 안 바뀐 것을 수정 시각으로 확인했다.
    처음엔 「시운전 뒤 코드를 고치면 섞으면 안 된다」 는 이유로 따로 두려 했는데, 고친 게 없으므로
    다시 쓰는 것이 맞다. 약 190원을 아낀다.
    """
    단계, *나머지 = 꼬리표.split("|")
    return "|".join(["본실행" if 단계 == "시운전" else 단계, *나머지])


def _이미한것() -> set[str]:
    if not metrics.기록파일.exists():
        return set()
    꼬리들 = {json.loads(x).get("꼬리표", "") for x in
             metrics.기록파일.read_text(encoding="utf-8").splitlines() if x.strip()}
    return 꼬리들 | {_정규(t) for t in 꼬리들}


@contextlib.contextmanager
def _설정적용(덮어쓸것: dict, 코퍼스: str):
    """설정을 덮어쓰고, 무슨 일이 있어도 되돌린다."""
    원래 = copy.deepcopy(graph.설정)
    try:
        for 키, 값 in 덮어쓸것.items():
            if 키 == "스위치":
                graph.설정["스위치"].update(값)
            elif 키 != "혼자":
                graph.설정[키] = 값
        graph.스텁모드 = False
        graph.코퍼스읽기(코퍼스)
        yield
    finally:
        graph.설정.clear()
        graph.설정.update(원래)


def 한편(단계: str, 코퍼스: str, 설정이름: str, 덮어쓸것: dict, qid: str, 회차: int) -> dict:
    """보고서 한 편을 만들고 기록한다. 계량을 돌려준다."""
    import baseline

    꼬리 = _꼬리표(단계, 코퍼스, 설정이름, qid, 회차)
    질문 = _질문글(qid)
    전, _ = graph.차단기.누적()
    시작 = time.time()
    with _설정적용(덮어쓸것, 코퍼스), contextlib.redirect_stdout(io.StringIO()):
        if 덮어쓸것.get("혼자"):
            결과 = baseline.혼자(질문)
            계량 = baseline.재기(결과)
        else:
            결과 = graph.실행(질문)
            계량 = 결과["계량"]
        스위치 = dict(graph.설정["스위치"])
        절예산 = graph.설정["절예산"]
    걸린 = round(time.time() - 시작, 1)
    후, _ = graph.차단기.누적()

    계량 = {**계량, "설정": 설정이름, "질문ID": qid, "회차": 회차,
            "절예산": 절예산, "걸린초": 걸린}
    metrics.기록({**결과, "코퍼스이름": 코퍼스, "스위치": 스위치}, 계량,
                비용=후 - 전, 꼬리표=꼬리)

    보고서방.mkdir(parents=True, exist_ok=True)
    (보고서방 / (꼬리.replace("|", "_").replace(".json", "") + ".md")).write_text(
        결과.get("보고서", ""), encoding="utf-8")
    return 계량


def 목록(단계: str, 회차: int | None = None) -> list[tuple[str, str, dict, str, int]]:
    """(코퍼스, 설정이름, 덮어쓸것, 질문, 회차) 목록. 회차를 주면 그 회차만 — 작성자 승인 C.
    1회차를 먼저 돌려 보고, 이상하면 2회차를 안 돌리고 멈출 수 있게 한다."""
    rs = [회차] if 회차 else 회차들
    if 단계 == "시운전":
        return [(확장, 이름, 설정, "M1", 1) for 이름, 설정 in 실험설정.items()]
    if 단계 == "경로시험":
        return [(확장, "경로시험", 경로시험설정, q, r) for q in 경로시험질문 for r in rs]
    if 단계 == "본실행":
        일 = [(확장, 이름, 설정, q, r)
             for r in rs for q in 실험질문 for 이름, 설정 in 실험설정.items()]
        일 += [(R0, "기본", {}, q, r) for r in rs for q in 실험질문]
        return 일
    raise ValueError(단계)


def 돌리기_실험(단계: str, 회차: int | None = None) -> int:
    할일 = 목록(단계, 회차)
    한것 = _이미한것()
    남은 = [x for x in 할일 if _꼬리표(단계, x[0], x[1], x[3], x[4]) not in 한것]

    예상원 = sum(어림비용.get(x[1], 32) for x in 남은)
    쓴돈, _ = graph.차단기.누적()
    남은상한원 = (graph.차단기.상한 - 쓴돈) * 1450
    원꼬리 = {json.loads(x).get("꼬리표", "") for x in
             metrics.기록파일.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if metrics.기록파일.exists() else set()
    재사용 = [x for x in 할일 if _꼬리표(단계, x[0], x[1], x[3], x[4]) not in 원꼬리
             and _꼬리표(단계, x[0], x[1], x[3], x[4]) in 한것]
    print(f"■ {단계}{f' {회차}회차' if 회차 else ''} — 전체 {len(할일)}편 · "
          f"이미 한 것 {len(할일) - len(남은)}편 (그중 시운전에서 가져온 것 {len(재사용)}편) · "
          f"남은 {len(남은)}편")
    print(f"  상한 ${graph.차단기.상한:.2f} · 누적 ${쓴돈:.4f}")
    print(f"  예상 약 {예상원:,}원 · 상한까지 남은 돈 약 {남은상한원:,.0f}원")
    if 예상원 > 남은상한원:
        print("  ❌ 예상 비용이 상한을 넘습니다. 돌리지 않습니다.")
        return 1
    print()

    for i, (코퍼스, 이름, 설정, qid, 회차) in enumerate(남은, 1):
        try:
            m = 한편(단계, 코퍼스, 이름, 설정, qid, 회차)
        except Exception as e:        # 예산초과(차단기) 포함 — 멈추고 알린다. 기록된 것은 남는다
            print(f"  [{i}/{len(남은)}] ❌ {코퍼스} {이름} {qid} {회차}회차 — {type(e).__name__}: {e}")
            print("  여기서 멈춥니다. 다시 돌리면 이미 한 것은 건너뛰고 이어서 합니다.")
            return 1
        경 = metrics.경보들(m)
        print(f"  [{i}/{len(남은)}] {코퍼스[:-5]:<11} {이름:<6} {qid} {회차}회차  "
              f"근거율 {m.get('근거율')}% · 읽음 {m.get('절당읽기')}×{m.get('절수')} · "
              f"{m['걸린초']}초 · {'경보 없음' if not 경 else '⚠️ ' + ' · '.join(경)}", flush=True)

    쓴돈2, _ = graph.차단기.누적()
    print(f"\n  이번에 쓴 돈 ${쓴돈2 - 쓴돈:.4f} (약 {(쓴돈2 - 쓴돈) * 1450:.0f}원) · "
          f"누적 ${쓴돈2:.4f} / 상한 ${graph.차단기.상한:.2f}")
    return 0


def 집계() -> None:
    """runs.jsonl 에서 4-C 실행만 모아 output/ablation.json 으로. 두 회차를 나란히 놓는다."""
    줄 = [json.loads(x) for x in metrics.기록파일.read_text(encoding="utf-8").splitlines() if x.strip()]
    실험 = [r for r in 줄 if r.get("꼬리표", "").split("|")[0] in ("본실행", "시운전", "경로시험")]
    모음 = {}
    for r in 실험:
        원래단계 = r["꼬리표"].split("|")[0]
        단계, 코퍼스, 이름, qid, 회차 = _정규(r["꼬리표"]).split("|")   # 시운전 M1 1회차 = 본실행
        모음.setdefault(f"{단계}|{코퍼스}|{이름}|{qid}", {})[f"{회차}회차"] = {
            "출처": 원래단계,
            **{k: r["계량"].get(k) for k in metrics.지표표},
            "읽은문서": sorted({d for s in r["절들"] for d in (s.get("읽음") or [])}),
            "역할": [t.get("역할") for t in r.get("목차", [])],
            "비용원": round(r.get("비용달러", 0) * 1450),
            "걸린초": r["계량"].get("걸린초"),
        }
    집계파일.write_text(json.dumps(모음, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{집계파일} — {len(모음)}묶음 ({len(실험)}편)")


# ─────────────────────────────────────────────────────────────
# 돈 쓰기 전 점검 — 가짜 응답기로 실험 코드가 끝까지 도는지 (0원)
# ─────────────────────────────────────────────────────────────
def 실험점검(단계: str = "시운전", 회차: int | None = None) -> int:
    """진짜 실험과 같은 코드를 가짜 응답기로 돌린다. 기록은 임시 파일에 남기고 지운다.
    본실행이면 진짜 시운전 기록을 임시 파일에 넣어, 시운전 재사용(A)이 실제로 되는지도 본다."""
    import tempfile

    import baseline

    녹 = 녹음기()
    원래기록 = metrics.기록파일
    원래보고서방 = globals()["보고서방"]
    원래부르기 = graph.부르기
    임시 = Path(tempfile.mkdtemp())
    try:
        시운전줄 = []
        if 단계 == "본실행" and 원래기록.exists():
            시운전줄 = [x for x in 원래기록.read_text(encoding="utf-8").splitlines()
                       if x.strip() and json.loads(x).get("꼬리표", "").startswith("시운전|")]
        metrics.기록파일 = 임시 / "runs.jsonl"
        metrics.기록파일.write_text("".join(x + "\n" for x in 시운전줄), encoding="utf-8")
        globals()["보고서방"] = 임시 / "reports"
        graph.부르기 = 녹.부르기

        def 혼자가짜(프롬프트, 태그):
            if 태그 == "혼자_시작":
                return json.dumps({"시작문서": "치매"}, ensure_ascii=False)
            if 태그 == "혼자_쓰기":
                return json.dumps({"본문": "가짜 문장이다 «치매».", "한마디로": "가짜",
                                   "근거": ["치매"]}, ensure_ascii=False)
            return 녹.부르기(프롬프트, 태그)
        graph.부르기 = 혼자가짜

        전, 호출전 = graph.차단기.누적()
        결과 = 돌리기_실험(단계, 회차)
        # 끊겨도 이어서 — 같은 걸 다시 돌리면 전부 건너뛰어야 한다
        print("\n■ 같은 단계를 한 번 더 — 전부 건너뛰어야 한다")
        결과2 = 돌리기_실험(단계, 회차)
        후, 호출후 = graph.차단기.누적()

        줄 = [json.loads(x) for x in metrics.기록파일.read_text(encoding="utf-8").splitlines()]
        # 스위치는 기록의 「계량」 안에 들어 있다 (metrics.재기 가 넣는다)
        설정확인 = {r["꼬리표"].split("|")[2]: (r["계량"].get("절예산"), r["계량"].get("스위치", {}))
                    for r in 줄}
        print("\n■ 기록된 설정 — 켠 것이 기록에 남았나, 끝나고 되돌아왔나")
        for 이름, (예산, 스) in 설정확인.items():
            꺼진 = [k for k, v in 스.items() if v is False]
            print(f"  {이름:<8} 절예산 {예산} · 꺼진 스위치 {꺼진 or '없음'}")
        print(f"  실험이 끝난 뒤 graph.설정 — 절예산 {graph.설정['절예산']} · "
              f"스위치 {graph.설정['스위치']}")
        되돌아옴 = graph.설정["절예산"] == 3 and all(graph.설정["스위치"].values())

        print(f"\n■ 비용 — 호출 {호출전}회 → {호출후}회 ({'0원 ✅' if 호출전 == 호출후 else '❌ 진짜 AI 를 불렀다'})")
        # 기록에 남은 것(시운전 재사용 + 새로 만든 것)이 해야 할 목록을 정확히 덮어야 한다
        덮음 = {_정규(r["꼬리표"]) for r in 줄}
        해야할 = {_꼬리표(단계, x[0], x[1], x[3], x[4]) for x in 목록(단계, 회차)}
        빠짐 = 해야할 - 덮음
        새로 = sum(1 for r in 줄 if r["꼬리표"].startswith(단계 + "|"))
        print(f"\n■ 목록 {len(해야할)}편 — 새로 만든 것 {새로}편 · 시운전에서 가져온 것 "
              f"{len(해야할) - 새로 - len(빠짐)}편 · 빠진 것 {len(빠짐)}편")
        ok = 결과 == 0 and 결과2 == 0 and 되돌아옴 and 호출전 == 호출후 and not 빠짐
        print("\n" + ("✅ 실험 코드가 끝까지 돌고, 이어하기가 되고, 설정이 되돌아옵니다."
                       if ok else "❌ 점검 실패 — 돈 쓰기 전에 고쳐야 합니다."))
        return 0 if ok else 1
    finally:
        metrics.기록파일 = 원래기록
        globals()["보고서방"] = 원래보고서방
        graph.부르기 = 원래부르기
        import shutil
        shutil.rmtree(임시, ignore_errors=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--스위치시험", action="store_true", help="스위치가 진짜 꺼지나 (0원)")
    ap.add_argument("--점검", metavar="단계", nargs="?", const="시운전",
                    help="실험 코드를 가짜 응답기로 끝까지 돌려 본다 (0원)")
    ap.add_argument("--시운전", action="store_true", help="M1 × 6설정 × 1회 (돈 씀)")
    ap.add_argument("--경로시험", action="store_true", help="절예산 1 로 재위임이 도는지 (돈 씀)")
    ap.add_argument("--본실행", action="store_true", help="6질문 × 6설정 × 2회 + R0 기본 (돈 씀)")
    ap.add_argument("--집계", action="store_true", help="output/ablation.json 만들기")
    ap.add_argument("--회차", type=int, choices=회차들,
                    help="이 회차만 (예: --본실행 --회차 1). 안 주면 두 회차 다")
    a = ap.parse_args()

    if a.스위치시험:
        sys.exit(스위치시험())
    if a.점검:
        sys.exit(실험점검(a.점검, a.회차))
    if a.시운전:
        sys.exit(돌리기_실험("시운전"))
    if a.경로시험:
        sys.exit(돌리기_실험("경로시험", a.회차))
    if a.본실행:
        sys.exit(돌리기_실험("본실행", a.회차))
    if a.집계:
        집계()
        sys.exit(0)
    ap.print_help()
