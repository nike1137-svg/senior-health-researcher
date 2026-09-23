"""평가셋 질문이 코퍼스로 실제 답이 되는지 대조한다.

왜 필요한가
  질문이 가리키는 문서가 코퍼스에 없으면 조사관은 자기 상식으로 채운다.
  글은 나오지만 근거가 없고, 그걸 모른 채 측정하면 모델 탓으로 돌리게 된다.
  코퍼스나 질문을 고칠 때마다 이걸 다시 돌려야 한다.

무엇을 보는가
  ① why_split 에 «...» 로 적은 문서가 corpus.json 의 docs 에 실제로 있는가
  ② trace 질문의 경로가 links 를 타고 2홉 안에 이어지는가

실행:  python tools/check_questions.py
"""
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "..", "data", "corpus.json")
QUESTIONS = os.path.join(HERE, "..", "data", "questions.json")
HOPS = 2

CITE = re.compile(r"«([^»]+)»")


def reachable(links, a, b, hops=HOPS):
    """a 에서 links 를 타고 hops 홉 안에 b 에 닿는가."""
    cur, seen = {a}, {a}
    for _ in range(hops):
        nxt = set()
        for x in cur:
            for y in links.get(x, []):
                if y == b:
                    return True
                if y not in seen:
                    seen.add(y)
                    nxt.add(y)
        cur = nxt
    return False


def main():
    d = json.load(io.open(CORPUS, encoding="utf-8"))
    q = json.load(io.open(QUESTIONS, encoding="utf-8"))
    docs, links = set(d["docs"]), d["links"]

    print(f"코퍼스 {len(docs)}건 · 질문 {len(q['questions'])}건\n")
    print(f"{'ID':<5}{'성격':<8}{'언급':>4}  {'판정':<6} 비고")
    print("-" * 78)

    missing, broken = set(), []
    for it in q["questions"]:
        named = CITE.findall(it["why_split"])
        miss = [n for n in named if n not in docs]
        missing |= set(miss)

        note, verdict = "", "OK"
        if miss:
            verdict = "없음"
            note = "코퍼스에 없는 문서: " + ", ".join(miss)
        elif it["type"] == "trace" and len(named) >= 2:
            start, rest = named[0], [n for n in named[1:] if n in docs]
            bad = [n for n in rest if not reachable(links, start, n)]
            if bad:
                verdict = "경로끊김"
                broken.append(it["id"])
                note = f"{start} 에서 {HOPS}홉 안에 못 닿음: " + ", ".join(bad)
            else:
                note = f"{start} → " + " → ".join(rest)
        print(f"{it['id']:<5}{it['type']:<8}{len(named):>4}  {verdict:<6} {note}")

    print("-" * 78)
    ok = not missing and not broken
    if missing:
        print(f"[문제] 코퍼스에 없는 문서 {len(missing)}건: {', '.join(sorted(missing))}")
        print("       → 코퍼스에 넣거나(시드 추가), 질문을 고친다.")
    if broken:
        print(f"[문제] 경로가 끊긴 trace 질문: {', '.join(broken)}")
        print("       → 사이를 잇는 문서를 코퍼스에 넣는다.")
    if ok:
        print("[통과] 모든 질문이 코퍼스로 답이 된다.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
