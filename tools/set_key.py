"""set_key.py — .env 에 OpenAI 키를 넣고, 진짜 되는지 확인한다

    python -m tools.set_key --메모장   ← 메모장으로 넣기 (권장)
    python -m tools.set_key            ← 터미널에 붙여넣기 (화면에 안 보임)
    python -m tools.set_key --확인     ← 인증되는지만 확인 (비용 0원)

빨리 실패하게 한다 (fail fast, 수업 3-C) — 키가 잘못된 것을 첫 API 호출이 아니라 **여기서** 알아야 한다.
실제로 키 자리에 한글 자모가 섞여 들어가 인증이 계속 실패한 사고가 있었다.

메모장으로 넣을 때 흔한 사고 셋을 이 파일이 자동으로 정리한다:
  ⑴ 따옴표로 감싸서 붙여넣음   ⑵ = 뒤에 공백   ⑶ 저장 인코딩이 바뀌어 BOM 이 붙음
셋 다 증상이 '인증 실패' 하나뿐이라, 눈으로는 구별이 안 된다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

루트 = Path(__file__).resolve().parent.parent
ENV = 루트 / ".env"
이름 = "OPENAI_API_KEY"


# ─────────────────────────────────────────────────────────────
# .env 읽고 쓰기 — utf-8-sig 로 읽어 BOM 을 삼키고, utf-8(BOM 없이) 로 쓴다
# ─────────────────────────────────────────────────────────────
def _줄들() -> list[str]:
    if not ENV.exists():
        return []
    return ENV.read_text(encoding="utf-8-sig").splitlines()


def _쓰기(줄들: list[str]) -> None:
    ENV.write_text("\n".join(줄들) + "\n", encoding="utf-8")


def 읽은값() -> str:
    for 줄 in _줄들():
        s = 줄.lstrip("﻿").strip()
        if s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == 이름:
            return v
    return ""


def 다듬기(v: str) -> str:
    """메모장에서 딸려 들어오는 것들을 걷어낸다."""
    v = v.lstrip("﻿").strip()
    for q in ('"', "'"):
        if len(v) >= 2 and v.startswith(q) and v.endswith(q):
            v = v[1:-1]
    return v.strip()


def 넣기(k: str) -> None:
    줄들 = _줄들()
    찾음 = False
    새줄 = []
    for 줄 in 줄들:
        s = 줄.lstrip("﻿").strip()
        if not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == 이름:
            새줄.append(f"{이름}={k}")
            찾음 = True
        else:
            새줄.append(줄.lstrip("﻿"))
    if not 찾음:
        새줄.append(f"{이름}={k}")
    _쓰기(새줄)


def 자리보장() -> None:
    """메모장을 열기 전에 OPENAI_API_KEY= 줄이 있는지 확인하고, 없으면 만들어 둔다.
    빈 파일을 열어 주면 마커스님이 줄 이름을 직접 타이핑해야 하고, 오타가 난다."""
    if any(
        not 줄.lstrip("﻿").strip().startswith("#")
        and "=" in 줄
        and 줄.lstrip("﻿").split("=", 1)[0].strip() == 이름
        for 줄 in _줄들()
    ):
        return
    줄들 = _줄들()
    줄들 += ["", "# OpenAI API 키 — 아래 = 뒤에 붙여넣으십시오 (따옴표·공백 없이)", f"{이름}="]
    _쓰기(줄들)


# ─────────────────────────────────────────────────────────────
# 검사
# ─────────────────────────────────────────────────────────────
def 검사(k: str) -> list[str]:
    탈 = []
    if not k:
        return ["비어 있습니다. = 뒤에 키를 붙여넣고 저장하셨는지 보십시오."]
    if not k.isascii():
        섞인 = sorted({c for c in k if not c.isascii()})
        탈.append(
            f"ASCII 가 아닌 글자가 섞였습니다: {섞인[:5]} "
            f"— 한/영 전환 상태에서 붙여넣으면 이렇게 됩니다."
        )
    if not k.startswith("sk-"):
        탈.append(f"'sk-' 로 시작하지 않습니다 (시작: {k[:3]!r}).")
    if len(k) < 40:
        탈.append(f"길이가 {len(k)}자로 너무 짧습니다. 잘려 붙은 것으로 보입니다.")
    if any(c.isspace() for c in k):
        탈.append("가운데에 공백/줄바꿈이 들어 있습니다. 키가 두 줄로 붙은 것으로 보입니다.")
    return 탈


def 정리하고검사() -> tuple[str, list[str]]:
    """읽고 → 다듬고 → 달라졌으면 되써 주고 → 검사 결과를 돌려준다."""
    원본 = 읽은값()
    키 = 다듬기(원본)
    if 키 and 키 != 원본:
        넣기(키)
        군더더기 = []
        if 원본.strip() != 원본:
            군더더기.append("공백")
        if 원본.strip()[:1] in ('"', "'"):
            군더더기.append("따옴표")
        if 원본.startswith("﻿"):
            군더더기.append("BOM")
        print(f"🧹 {' · '.join(군더더기) or '군더더기'} 를 걷어내고 다시 저장했습니다.")
    return 키, 검사(키)


# ─────────────────────────────────────────────────────────────
# 인증 확인 — models.list 는 토큰을 쓰지 않아 비용이 0원이다
# ─────────────────────────────────────────────────────────────
def 인증확인() -> int:
    키, 탈 = 정리하고검사()
    if 탈:
        print(f"\n❌ {ENV} 의 {이름} 이 이상합니다. (길이 {len(키)}자)")
        for t in 탈:
            print("  -", t)
        print("\n  다시 넣으려면:  python -m tools.set_key --메모장")
        return 1

    from openai import OpenAI

    try:
        목록 = OpenAI(api_key=키).models.list()
    except Exception as e:
        print(f"\n❌ 인증 실패: {type(e).__name__}")
        print(f"   {str(e)[:300]}")
        print("\n  키 형식은 멀쩡하니, 키가 폐기됐거나 다른 조직의 키일 수 있습니다.")
        print("  platform.openai.com/api-keys 에서 새로 발급받아 보십시오.")
        return 1

    이름들 = {m.id for m in 목록.data}
    쓸모델 = "gpt-4o-mini"
    print(f"\n✅ 인증 성공 · 쓸 수 있는 모델 {len(이름들)}개 (비용 0원)")
    if 쓸모델 in 이름들:
        print(f"   «{쓸모델}» 사용 가능: 예")
        return 0
    print(f"   «{쓸모델}» 사용 가능: 아니오 — config.json 의 모델.이름 을 바꿔야 합니다.")
    return 1


# ─────────────────────────────────────────────────────────────
def 메모장으로() -> int:
    자리보장()
    print(f"메모장으로 {ENV} 를 엽니다.\n")
    print(f"  1. {이름}=  줄을 찾으십시오")
    print("  2. = 뒤에 키를 붙여넣으십시오 — 따옴표 없이, 공백 없이, 한 줄로")
    print(f"       {이름}=sk-...")
    print("  3. Ctrl+S 로 저장하고 메모장을 닫으십시오\n")

    try:
        subprocess.Popen(["notepad.exe", str(ENV)])
    except FileNotFoundError:
        print(f"메모장을 못 열었습니다. 직접 여십시오: {ENV}")

    input("저장하셨으면 여기서 Enter 를 누르십시오... ")
    return 인증확인()


if __name__ == "__main__":
    # 한글 플래그가 셸 인코딩 때문에 깨지는 자리를 대비해 영문 별칭도 받는다
    인자 = set(sys.argv[1:])
    if 인자 & {"--메모장", "--notepad", "-n"}:
        sys.exit(메모장으로())

    if 인자 & {"--확인", "--check", "-c"}:
        sys.exit(인증확인())

    # 기본 — 터미널에 붙여넣기 (화면에 안 보임)
    import getpass

    print(f"{ENV} 의 {이름} 을 채웁니다.")
    print("입력한 글자는 화면에 보이지 않습니다. 붙여넣고 Enter 를 누르십시오.\n")
    키 = 다듬기(getpass.getpass("OpenAI API Key: "))
    탈 = 검사(키)
    if 탈:
        print("\n❌ 키가 이상합니다. 저장하지 않았습니다.")
        for t in 탈:
            print("  -", t)
        sys.exit(1)
    넣기(키)
    print(f"\n✅ 저장했습니다. ({len(키)}자 · sk-… 로 시작 · ASCII)")
    sys.exit(인증확인())
