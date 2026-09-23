"""한국어 위키백과에서 딥리서처용 코퍼스를 모은다.

과제 「위키백과 코퍼스 수집 프롬프트」 사양을 따른다.
  - 시드에서 2홉까지 넓혀 30건 이상을 corpus.json 한 파일로
  - 저장 형식: {"docs": {제목: 본문}, "links": {제목: [제목, ...]}}
  - links 에는 docs 안에 실제로 있는 제목만 남긴다
  - 본문 3000자 미만 토막글은 저장하지 않는다
  - MediaWiki API 만 사용 (HTML 크롤링 안 함)

두 단계로 나눠 받는 이유
  prop=extracts 는 무거운 확장 API 라 호출이 많아지면 429 로 막힌다 (실제로 막혔다).
  그래서 후보를 고르는 단계(수백 건)는 가벼운 action=raw 로 훑고,
  최종 선택분에만 과제가 지정한 prop=extracts / prop=links 를 쓴다.
  둘 다 MediaWiki 정식 경로이고 HTML 크롤링이 아니다.

실행:  python tools/collect_corpus.py
출력:  data/corpus.json
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

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://ko.wikipedia.org/w/api.php"
RAW = "https://ko.wikipedia.org/w/index.php?action=raw&title="
UA = "senior-health-researcher/1.0 (student assignment; python-urllib)"  # 아스키만
OUT = os.path.join(HERE, "..", "data", "corpus.json")
CACHE = os.path.join(HERE, "..", "data", "cache")

MIN_CHARS = 3000        # 토막글 기준
TARGET = 60             # 목표 문서 수 (필수는 30건 이상)
POOL = 170              # 2홉 후보 상한
PAUSE_RAW = 0.35        # 가벼운 경로
PAUSE_API = 1.0         # 무거운 경로 (extracts/links)

SEEDS = [
    # 인지·신경
    "치매", "알츠하이머병", "파킨슨병", "섬망", "주요 우울 장애",
    # 혈관·심장
    "뇌졸중", "고혈압", "심근 경색", "협심증", "동맥경화", "심방세동",
    "부정맥", "혈전", "뇌출혈",
    # 대사
    "당뇨병", "비만", "콜레스테롤", "인슐린", "통풍",
    # 감각기관
    "백내장", "녹내장",
    # 뼈·근육
    "골다공증",
    # 종양
    "암", "폐암", "위암", "대장암",
    # 감염·호흡
    "대상포진", "결핵", "천식",
    # 그 밖
    "노화", "불면증", "빈혈", "흡연", "수면 무호흡증",
    # 평가셋 질문이 가리키는데 2홉 확장에서 빠졌던 문서.
    # 코퍼스를 질문에 맞춘다. 질문을 코퍼스에 맞춰 깎으면 '자료에 있는 것만 묻는' 평가셋이 된다.
    "청각 장애", "당뇨병성 망막병증", "합병증", "ACE 억제제",
]

SKIP_PREFIX = ("파일:", "분류:", "틀:", "위키", "Image:", "File:",
               "Category:", "Special:", "목록:")
SKIP_PAT = re.compile(r"(^\d{1,4}년)|(목록$)|(일람$)|(연표$)")

_last = {"raw": 0.0, "api": 0.0}


# ── 캐시 ──────────────────────────────────────────────────────────
def cached(kind, title, fetch):
    """받은 것은 파일에 남긴다. 중간에 끊겨도 다시 받지 않는다."""
    os.makedirs(CACHE, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣]", "_", title)[:80]
    p = os.path.join(CACHE, f"{kind}_{abs(hash(title)) % 10**8}_{safe}.json")
    if os.path.exists(p):
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    v = fetch()
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False)
    return v


def _wait(lane, gap):
    d = time.time() - _last[lane]
    if d < gap:
        time.sleep(gap - d)


class Missing(Exception):
    """그 문서가 없다. 재시도해도 소용없으므로 건너뛴다."""


def _open(url, lane, gap, tries=5):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    err = None
    for i in range(tries):
        _wait(lane, gap)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                _last[lane] = time.time()
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            _last[lane] = time.time()
            if e.code in (400, 404):        # 없는 문서 — 기다려도 안 생긴다
                raise Missing(url) from e
            err = e
        except Exception as e:
            err = e
            _last[lane] = time.time()
        w = [3, 8, 20, 45, 90][i]
        print(f"    ...{type(err).__name__} — {w}초 후 재시도", flush=True)
        time.sleep(w)
    raise err


# ── 가벼운 경로: 후보 훑기 ─────────────────────────────────────────
LINK_RE = re.compile(r"\[\[([^\]\|#<>\[]+)(?:\|[^\]]*)?\]\]")
REDIR = re.compile(r"^\s*#\s*(넘겨주기|REDIRECT)", re.I)


def screen(title):
    """action=raw 로 (대략적인 본문 길이, 내부 링크 목록) 을 한 번에 얻는다.
    없는 문서는 길이 0 으로 돌려 자연스럽게 걸러지게 한다."""
    def fetch():
        try:
            wt = _open(RAW + urllib.parse.quote(title.replace(" ", "_")),
                       "raw", PAUSE_RAW)
        except Missing:
            return [0, []]
        if REDIR.match(wt):                 # 넘겨주기 문서는 버린다
            return [0, []]
        links = sorted({m.group(1).strip() for m in LINK_RE.finditer(wt)})
        links = [l for l in links if l and not l.startswith(SKIP_PREFIX)]
        t = re.sub(r"\{\{[^{}]*\}\}", " ", wt)
        t = re.sub(r"\{\|.*?\|\}", " ", t, flags=re.S)
        t = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", " ", t, flags=re.S)
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"\[\[(?:[^\]\|]*\|)?([^\]]*)\]\]", r"\1", t)
        t = re.sub(r"https?://\S+", " ", t)
        t = re.sub(r"[=*#'|\[\]]", " ", t)
        return [len(re.sub(r"\s+", " ", t)), links]
    return tuple(cached("rw", title, fetch))


# ── 과제가 지정한 경로: 최종 선택분만 ──────────────────────────────
def api(params):
    params = dict(params)
    params.update({"format": "json", "formatversion": "2"})
    return json.loads(_open(API + "?" + urllib.parse.urlencode(params),
                            "api", PAUSE_API))


def get_extract(title):
    """prop=extracts + explaintext. 평문 전체를 받을 때는 요청당 한 건만 온다."""
    def fetch():
        d = api({"action": "query", "prop": "extracts", "explaintext": 1,
                 "titles": title, "redirects": 1})
        for p in d.get("query", {}).get("pages", []):
            if p.get("extract"):
                return [p["title"], p["extract"]]
        return [None, None]
    return tuple(cached("ex", title, fetch))


def get_links(title):
    """prop=links. continue 가 있으면 이어 받는다."""
    def fetch():
        acc, cont = [], None
        while True:
            q = {"action": "query", "prop": "links", "titles": title,
                 "plnamespace": 0, "pllimit": "max", "redirects": 1}
            if cont:
                q["plcontinue"] = cont
            d = api(q)
            for p in d.get("query", {}).get("pages", []):
                acc += [l["title"] for l in p.get("links", [])]
            cont = d.get("continue", {}).get("plcontinue")
            if not cont:
                return acc
    return cached("lk", title, fetch)


def usable(t):
    return not t.startswith(SKIP_PREFIX) and not SKIP_PAT.search(t)


# ── 수집 ──────────────────────────────────────────────────────────
def collect():
    print(f"[훑기 1홉] 시드 {len(SEEDS)}건", flush=True)
    S = {}
    for s in SEEDS:
        S[s] = screen(s)
    live = [s for s in SEEDS if S[s][0] >= MIN_CHARS]
    drop = [s for s in SEEDS if s not in live]
    if drop:
        print(f"  제외(넘겨주기/토막글): {drop}", flush=True)

    freq = {}
    for s in live:
        for l in S[s][1]:
            if l not in live and usable(l):
                freq[l] = freq.get(l, 0) + 1
    cand = [t for t, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))][:POOL]
    print(f"[훑기 2홉] 후보 {len(cand)}건", flush=True)
    for i, c in enumerate(cand):
        S[c] = screen(c)
        if (i + 1) % 40 == 0:
            print(f"  {i+1}/{len(cand)}", flush=True)

    # 선택: 이미 뽑은 집합과 촘촘히 이어진 것부터.
    # 길이 순으로 뽑으면 「언어」「미국」 같은 큰 일반 문서가 딸려와 링크가 희박해진다.
    print("[선택] 링크 밀도 기준", flush=True)
    picked = list(live)
    avail = [c for c in cand if S[c][0] >= MIN_CHARS]
    for min_out in (2, 1):
        while len(picked) < TARGET and avail:
            ps = set(picked)
            best, bs = None, -1
            for t in avail:
                out = len([x for x in S[t][1] if x in ps])
                inn = sum(1 for p in picked if t in S[p][1])
                if out < min_out:
                    continue
                score = out * 2 + inn
                if score > bs:
                    best, bs = t, score
            if best is None:
                break
            picked.append(best)
            avail.remove(best)
        if len(picked) >= TARGET:
            break
        print(f"  [완화] out>={min_out} 로는 {len(picked)}건 — 조건을 낮춘다", flush=True)

    # 최종 선택분만 과제가 지정한 API 로 다시 받는다
    print(f"[확정] {len(picked)}건을 prop=extracts / prop=links 로 받는다", flush=True)
    docs, links = {}, {}
    for i, t in enumerate(picked):
        title, text = get_extract(t)
        if not text or len(text) < MIN_CHARS:
            continue
        docs[title] = text
        links[title] = get_links(title)
        if (i + 1) % 15 == 0:
            print(f"  {i+1}/{len(picked)}", flush=True)

    titles = set(docs)
    links = {t: sorted({l for l in links[t] if l in titles and l != t}) for t in docs}
    return docs, links


def report(docs, links):
    total = sum(len(v) for v in docs.values())
    out_n = [len(v) for v in links.values()]
    # 들어오는 링크를 따로 센다.
    # 탐색으로 닿지 못하는 문서는 '나가는 링크가 0' 이 아니라 '아무도 가리키지 않는' 문서다.
    inn = {t: 0 for t in docs}
    for a, ls in links.items():
        for b in ls:
            inn[b] += 1
    orphan = sorted(t for t in docs if inn[t] == 0)
    print("\n" + "=" * 62)
    print(f"문서 수                : {len(docs)}건        (필수 30건 이상)")
    print(f"총 글자 수             : {total:,}자")
    print(f"추정 토큰              : {total//2:,}        (창 128,000 기준)")
    print(f"모델 창 대비           : {total/2/128000:.2f}배   <- 1.0 을 넘어야 이 구조를 쓸 이유가 있다")
    print(f"나가는 링크 중앙값     : {statistics.median(out_n) if out_n else 0}")
    print(f"들어오는 링크 중앙값   : {statistics.median(inn.values()) if inn else 0}")
    print(f"아무도 가리키지 않는 문서: {len(orphan)}건")
    for t in orphan:
        print(f"   - {t}   (탐색으로는 닿지 못함 — 배정이 유일한 경로)")
    print("=" * 62)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    docs, links = collect()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump({"docs": docs, "links": links}, f, ensure_ascii=False, indent=1)
    report(docs, links)
    print(f"\n저장: {os.path.normpath(OUT)}")
