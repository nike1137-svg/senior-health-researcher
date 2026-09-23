"""국가법령정보 OPEN API 에서 노인 관련 법령을 모아 위키 코퍼스와 합친다.

입력 : data/corpus.json        (위키만 — collect_corpus.py 가 만든 것)
출력 : data/corpus_full.json   (위키 + 법령)

왜 따로 두는가
  위키만 모은 것이 R0 기준선이고, 법령을 더한 것이 확장이다.
  같은 질문을 두 코퍼스로 돌려 비교하면 "자료원을 늘리면 무엇이 달라지는가" 가 실험이 된다.

링크 규칙 (한 줄로 설명되는 것만 쓴다)
  문서 B의 제목이나 그 별칭이 문서 A의 본문에 나오면  A -> B
  위키백과 내부 링크가 하는 일과 같고, 사람이 읽어도 납득이 된다.

실행:  python tools/collect_laws.py     (.env 의 LAW_OC 필요)
"""
import io
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(__file__)
IN_WIKI = os.path.join(HERE, "..", "data", "corpus.json")
OUT = os.path.join(HERE, "..", "data", "corpus_full.json")

UA = "deep-researcher-corpus/1.0 (student assignment)"
MIN_CHARS = 3000
PAUSE = 0.25

# 이 검색어들로 법령 목록을 훑는다.
# "건강보험" 은 나중에 넣었다 — 이게 없으면 국민건강보험법이 검색에 안 걸린다 (실제로 빠졌었다).
QUERIES = ["노인", "치매", "장기요양", "기초연금", "고령자", "요양보호사", "건강보험"]

# 받을 법령을 이름으로 못박는다. 검색어에 걸리는 것을 전부 담으면 33건이 되고,
# 그 대부분이 시행령·시행규칙이라 위임 관계만 반복돼 리서치 자료로는 잡음이다.
#
# 6건으로 좁힌 이유: 이 코퍼스는 R0(위키 57건)와 견줄 '확장'이다.
# 둘의 차이가 「법령을 넣었다」 하나로 남으려면 더한 쪽이 작고 또렷할수록 낫다.
받을법령 = [
    "치매관리법",
    "노인장기요양보험법",
    "노인복지법",
    "기초연금법",
    "국민건강보험법",
    "노인 일자리 및 사회활동 지원에 관한 법률",
]


def 이름맞춤(s):
    """법령명한글의 띄어쓰기가 목록과 다를 수 있어 공백을 지우고 견준다."""
    return re.sub(r"\s+", "", s or "")

# 법령 -> 별칭. 위키 본문에 이 말이 나오면 그 법령으로 링크를 건다.
# 법령명 자체는 위키 본문에 거의 안 나오기 때문에 별칭이 필요하다 (실측으로 확인됨).
ALIAS = {
    "노인장기요양보험법": ["장기요양", "요양보호사", "요양등급", "노인요양"],
    "치매관리법": ["치매안심센터", "치매검진", "치매상담", "광역치매센터"],
    "기초연금법": ["기초연금", "노령연금"],
    "노인복지법": ["노인복지시설", "경로당", "노인학대", "노인복지"],
    "국민건강보험법": ["국민건강보험", "건강보험", "요양급여"],
    "노인 일자리 및 사회활동 지원에 관한 법률": ["노인일자리", "노인 일자리"],
    "장애인ㆍ노인ㆍ임산부 등의 편의증진 보장에 관한 법률": ["편의시설", "무장애"],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            time.sleep(PAUSE)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            err = e
            time.sleep([2, 6, 15, 30][attempt])
    raise err


def search(oc, q):
    u = (f"http://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target=law&type=JSON"
         f"&display=100&query=" + urllib.parse.quote(q))
    d = json.loads(get(u)).get("LawSearch", {}).get("law", [])
    return [d] if isinstance(d, dict) else d


def articles(oc, mst):
    """조문만 뽑는다. 별표·서식·부칙·개정문은 버린다.
    전체 JSON 을 그대로 세면 실제 조문의 6배가 나온다 (별표가 대부분)."""
    b = json.loads(get(f"http://www.law.go.kr/DRF/lawService.do?OC={oc}"
                       f"&target=law&type=JSON&MST={mst}"))["법령"]
    unit = b.get("조문", {}).get("조문단위", [])
    if isinstance(unit, dict):
        unit = [unit]
    out = []
    for u in unit:
        if u.get("조문여부") == "전문":      # 편·장·절 제목만 있는 칸
            continue
        c = u.get("조문내용")
        if isinstance(c, str):
            out.append(c)
        for h in (u.get("항") or []):
            if not isinstance(h, dict):
                continue
            out.append(str(h.get("항내용", "")))
            for ho in (h.get("호") or []):
                if isinstance(ho, dict):
                    out.append(str(ho.get("호내용", "")))
    t = " ".join(x for x in out if x)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def collect_laws(oc):
    원하는 = {이름맞춤(x): x for x in 받을법령}
    laws = {}
    for q in QUERIES:
        if len(laws) == len(원하는):
            break
        for it in search(oc, q):
            n = it["법령명한글"]
            키 = 이름맞춤(n)
            if 키 not in 원하는 or 원하는[키] in laws:
                continue                       # 목록에 없는 법령·시행령·시행규칙은 건너뛴다
            try:
                t = articles(oc, it["법령일련번호"])
            except Exception as e:
                print(f"  건너뜀 {n}: {type(e).__name__}")
                continue
            if len(t) < MIN_CHARS:
                print(f"  {len(t):>7,}자  {n}  ← {MIN_CHARS:,}자 미만이라 버림", flush=True)
                continue
            laws[원하는[키]] = t                # 목록에 적은 이름으로 담는다 (ALIAS 와 맞추려고)
            print(f"  {len(t):>7,}자  {n}", flush=True)

    못받은 = [x for x in 받을법령 if x not in laws]
    if 못받은:
        print(f"\n  ⚠️ 못 받은 법령 {len(못받은)}건: {못받은}")
        print("     검색어(QUERIES)로 안 걸렸거나 API 가 막힌 것이다. 그냥 넘어가지 말 것.")
    return laws


def build_links(docs, wiki_titles, law_titles, 위키링크):
    """법령이 한쪽에 걸린 쌍만 새로 계산한다. 위키끼리의 링크는 corpus.json 것을 그대로 물려받는다.

    ★ 왜 물려받는가
      corpus.json 의 위키 링크는 **위키백과가 실제로 건 내부 링크**다.
      여기 규칙은 **B의 제목이나 별칭이 A의 본문에 나오면 A→B** 로, 서로 다른 관계다.
      전부 새로 계산하면 두 코퍼스에서 위키끼리의 링크가 달라지고,
      그러면 4단계에서 「법령을 넣어서 달라진 것」인지 「링크 규칙이 바뀌어서 달라진 것」인지
      가를 수 없다. 과제가 경고한 "지표가 좋아진 줄 알았는데 문장 분리 규칙이 바뀐 것" 과 같은 종류다.

      위키 → 위키 : corpus.json 그대로   (안 건드린다)
      위키 → 법령 / 법령 → 위키 / 법령 → 법령 : 여기서 계산
    """
    terms = {}
    for t in docs:
        ts = [t]
        ts += ALIAS.get(t, [])
        if t in law_titles:
            # 시행령·시행규칙은 본법 이름으로도 걸리게
            base = re.sub(r"\s*시행(령|규칙)$", "", t)
            if base != t:
                ts.append(base)
        terms[t] = [x for x in ts if len(x) >= 2]

    links = {}
    for a, body in docs.items():
        # 위키 문서는 원래 링크에서 출발한다
        hit = set(위키링크.get(a, [])) if a in wiki_titles else set()
        for b, ws in terms.items():
            if b == a:
                continue
            if a in wiki_titles and b in wiki_titles:
                continue                      # 위키끼리는 새로 계산하지 않는다
            if any(w in body for w in ws):
                hit.add(b)
        links[a] = sorted(hit)
    return links


def report(docs, links, wiki_titles, law_titles, 위키링크):
    total = sum(len(v) for v in docs.values())
    counts = [len(v) for v in links.values()]
    zero = sorted(t for t in docs if not links[t])
    cross = sum(1 for a in wiki_titles for b in links[a] if b in law_titles)
    back = sum(1 for a in law_titles for b in links[a] if b in wiki_titles)
    print("\n" + "=" * 62)
    print(f"문서 수            : {len(docs)}건  (위키 {len(wiki_titles)} + 법령 {len(law_titles)})")
    print(f"총 글자 수         : {total:,}자")
    print(f"모델 창 대비       : {total/2/128000:.2f}배")
    print(f"문서당 링크 중앙값 : {statistics.median(counts) if counts else 0}")
    print(f"위키 -> 법령 링크  : {cross}개   <- 0 이면 두 자료원이 분리된 섬이다")
    print(f"법령 -> 위키 링크  : {back}개")
    print(f"링크 0개 문서      : {len(zero)}건 {zero[:6]}")

    # 위키끼리의 링크가 corpus.json 과 똑같은지 본다. 다르면 두 코퍼스를 견줄 수 없다.
    원래 = sum(len([b for b in 위키링크.get(a, []) if b in wiki_titles]) for a in wiki_titles)
    지금 = sum(len([b for b in links[a] if b in wiki_titles]) for a in wiki_titles)
    맞나 = "그대로 ✅" if 원래 == 지금 else f"⚠️ 달라짐 ({원래} -> {지금})"
    print(f"위키 -> 위키 링크  : {지금}개   {맞나}")
    print("=" * 62)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    oc = os.environ.get("LAW_OC")
    if not oc:
        for line in io.open(os.path.join(HERE, "..", ".env"), encoding="utf-8"):
            if line.startswith("LAW_OC="):
                oc = line.split("=", 1)[1].strip()
    assert oc, "LAW_OC 가 없습니다. .env 를 확인하세요."

    wiki = json.load(io.open(IN_WIKI, encoding="utf-8"))
    print(f"위키 코퍼스 {len(wiki['docs'])}건 읽음\n[법령 수집]", flush=True)
    laws = collect_laws(oc)

    docs = dict(wiki["docs"]); docs.update(laws)
    links = build_links(docs, set(wiki["docs"]), set(laws), wiki.get("links", {}))

    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump({"docs": docs, "links": links}, f, ensure_ascii=False, indent=1)
    report(docs, links, set(wiki["docs"]), set(laws), wiki.get("links", {}))
    print(f"\n저장: {os.path.normpath(OUT)}")
