"""cost.py — API 비용 차단기

돈이 나가기 전에 막는다. 잔액을 몰라도 폭주가 물리적으로 불가능해야 한다.

쓰는 법:
    from tools.cost import 차단기
    차단기.확인()                      # 상한을 넘었으면 여기서 멈춘다 (호출 전)
    ...
    차단기.기록(resp.usage, "기획")    # 호출 뒤 실제 토큰을 누적

    python -m tools.cost              # 지금까지 쓴 금액 보기
    python -m tools.cost --초기화     # 누적 지우기 (실수로 쓴 테스트분 정리용)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

루트 = Path(__file__).resolve().parent.parent
_설정 = json.loads((루트 / "config.json").read_text(encoding="utf-8"))
장부 = 루트 / "output" / "cost.jsonl"

# 1M 토큰당 달러. 2026-09 기준 공식 가격표를 옮겨 적은 것.
# 모델을 바꾸면 여기도 바꿔야 한다 — 안 바꾸면 장부가 조용히 틀린 값을 쌓는다.
가격표 = {
    "gpt-4o-mini": {"입력": 0.15, "출력": 0.60},
    "gpt-4o":      {"입력": 2.50, "출력": 10.00},
}

# 지출 상한(달러). **config.json 에 두지 않는다** — config.json 은 과제가 정한 대로
# '도메인에 묶인 값'(절수·절예산·바퀴 상한·역할 명단)만 담는 자리이고, 예산은 도메인 값이 아니다.
#
# 값을 넉넉히 잡은 이유: 과제 4단계가 대조군에 "같은 읽기 예산 · 예산을 다 쓰는지 확인"을
# 요구한다. 상한이 실험을 중간에 끊으면 그건 이긴 것이 아니라 상대를 묶어 둔 것이 된다.
# 이 값은 '폭주 방지선'이지 '아껴 쓰기 목표'가 아니다.
상한달러 = float(os.environ.get("RESEARCH_BUDGET_USD", "5.0"))


class 예산초과(RuntimeError):
    pass


class 차단기_:
    def __init__(self) -> None:
        self.상한 = 상한달러

    # ── 읽기 ────────────────────────────────────────────────
    def 누적(self) -> tuple[float, int]:
        """(지금까지 쓴 달러, 호출 수)"""
        if not 장부.exists():
            return 0.0, 0
        총, n = 0.0, 0
        for 줄 in 장부.read_text(encoding="utf-8").splitlines():
            if not 줄.strip():
                continue
            총 += json.loads(줄)["달러"]
            n += 1
        return 총, n

    # ── 검사 ────────────────────────────────────────────────
    def 확인(self, 예상달러: float = 0.0) -> None:
        """LLM 을 부르기 **전에** 호출한다. 상한을 넘으면 예외로 멈춘다."""
        쓴돈, _ = self.누적()
        if 쓴돈 + 예상달러 >= self.상한:
            raise 예산초과(
                f"누적 ${쓴돈:.4f} + 예상 ${예상달러:.4f} ≥ 상한 ${self.상한:.2f} — 실행을 멈춥니다.\n"
                f"  상한을 올리려면 config.json 의 예산.상한달러 를 고치십시오.\n"
                f"  장부: {장부}"
            )

    # ── 기록 ────────────────────────────────────────────────
    def 값(self, usage, 모델: str | None = None) -> float:
        """장부에 쓰지 않고 달러만 셈한다. 남의 키로 도는 데모 실행이 쓴다 (그 돈은 내 장부가 아니다)."""
        return self._셈(usage, 모델)[2]

    def 기록(self, usage, 태그: str = "", 모델: str | None = None) -> float:
        """호출 뒤 실제 토큰을 누적. usage 는 OpenAI 응답의 usage 객체 또는 (입력, 출력) 튜플."""
        모델 = 모델 or _설정["모델"]["이름"]
        입력, 출력, 달러 = self._셈(usage, 모델)

        장부.parent.mkdir(parents=True, exist_ok=True)
        with 장부.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "때": datetime.now().isoformat(timespec="seconds"),
                "태그": 태그, "모델": 모델,
                "입력": 입력, "출력": 출력, "달러": round(달러, 6),
            }, ensure_ascii=False) + "\n")
        return 달러

    def _셈(self, usage, 모델: str | None = None) -> tuple[int, int, float]:
        모델 = 모델 or _설정["모델"]["이름"]
        if isinstance(usage, tuple):
            입력, 출력 = usage
        else:  # langchain 은 token_usage(prompt/completion), openai 는 input/output
            입력 = _꺼내기(usage, ("prompt_tokens", "input_tokens"))
            출력 = _꺼내기(usage, ("completion_tokens", "output_tokens"))

        p = 가격표.get(모델)
        if p is None:
            raise KeyError(f"가격표에 «{모델}» 이 없습니다. tools/cost.py 의 가격표에 먼저 넣으십시오.")
        달러 = 입력 / 1_000_000 * p["입력"] + 출력 / 1_000_000 * p["출력"]
        return 입력, 출력, 달러


def _꺼내기(u, 이름들: tuple[str, ...]) -> int:
    for n in 이름들:
        v = getattr(u, n, None)
        if v is None and isinstance(u, dict):
            v = u.get(n)
        if v is not None:
            return int(v)
    return 0


차단기 = 차단기_()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--초기화", action="store_true")
    a = ap.parse_args()

    if a.초기화:
        장부.unlink(missing_ok=True)
        print("장부를 지웠습니다.")
    else:
        쓴돈, n = 차단기.누적()
        원 = 쓴돈 * 1450
        print(f"누적  ${쓴돈:.4f}  (약 {원:,.0f}원) · 호출 {n}회")
        print(f"상한  ${차단기.상한:.2f}   남음 ${차단기.상한 - 쓴돈:.4f}")
