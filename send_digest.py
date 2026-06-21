"""
Weekly Digest → Telegram 자동 전송 스크립트
GitHub Actions에서 매주 월요일 09:00 KST 실행
"""
import requests
import os
import re
from datetime import datetime

# ── 환경변수 (GitHub Secrets에서 주입) ──────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
VERCEL_URL     = "https://paper-agent-theta.vercel.app"

# ── IF 내림차순 상위 20개 저널 ───────────────────────────────────
JOURNALS = [
    "Nature Nanotechnology",
    "Nature Materials",
    "Nature Electronics",
    "Advanced Functional Materials",
    "Advanced Materials",
    "Materials Today",
    "ACS Nano",
    "Small",
    "npj Computational Materials",
    "npj 2D Materials and Applications",
    "Nano Letters",
    "IEEE Transactions on Electron Devices",
    "IEEE Electron Device Letters",
    "Applied Physics Letters",
    "Journal of Applied Physics",
    "Microelectronic Engineering",
    "Journal of Vacuum Science Technology",
    "Semiconductor Science and Technology",
    "Thin Solid Films",
    "ECS Journal of Solid State Science",
]

# ── 비연구 논문 제거 패턴 ────────────────────────────────────────
JUNK = [
    r"highlights of recent", r"\beditorial\b", r"^erratum",
    r"^correction\b", r"^retraction", r"^reply to", r"^comment on",
    r"\bbook review\b", r"^issue information", r"^(front|back) cover",
    r"global ties", r"^masthead", r"\bnewsletter\b", r"annual report",
    r"^notice\b", r"^news\b", r"^preface\b", r"^foreword\b",
]

def is_junk(title: str, abstract: str) -> bool:
    for pat in JUNK:
        if re.search(pat, title, re.IGNORECASE):
            return True
    return len(abstract or "") < 80

# ── Semantic Scholar 검색 ────────────────────────────────────────
def search_papers(journal: str, limit: int = 3) -> list:
    try:
        r = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": f"{journal} semiconductor",
                "limit": limit + 10,
                "fields": "title,authors,year,abstract,venue,citationCount,externalIds",
            },
            timeout=20,
        )
        if not r.ok:
            print(f"  [WARN] {journal}: HTTP {r.status_code}")
            return []
        papers = r.json().get("data", [])
        filtered = [
            p for p in papers
            if not is_junk(p.get("title", ""), p.get("abstract", ""))
        ]
        return filtered[:limit]
    except Exception as e:
        print(f"  [ERROR] {journal}: {e}")
        return []

# ── 핵심 결과 문장 추출 ──────────────────────────────────────────
def extract_highlight(abstract: str) -> str:
    """초록에서 주요 결과 문장을 뽑아 300자 이내로 반환"""
    if not abstract:
        return ""
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", abstract)
    sents = [s.strip() for s in sents if len(s.strip()) > 20]

    result_kw = [
        "show", "demonstrat", "achiev", "exhibit", "improv", "enhanc",
        "reduc", " % ", "nm ", "eV ", "times", "fold", "superior",
        "outperform", "result", "obtain", "record", "highest", "lowest",
    ]
    result_sents = [
        s for s in sents if any(k in s.lower() for k in result_kw)
    ]
    chosen = result_sents[:2] if result_sents else sents[-2:]
    return " ".join(chosen)[:300]

def get_url(paper: dict) -> str:
    ids = paper.get("externalIds") or {}
    if ids.get("DOI"):
        return f"https://doi.org/{ids['DOI']}"
    if ids.get("ArXiv"):
        return f"https://arxiv.org/abs/{ids['ArXiv']}"
    return ""

# ── 텔레그램 메시지 포맷 ─────────────────────────────────────────
def build_message(papers: list) -> str:
    today = datetime.now().strftime("%Y.%m.%d")
    lines = [
        f"📅 *Weekly Digest — {today}*",
        f"반도체·재료공학 신규 논문 *{len(papers)}편*\n",
    ]

    for i, p in enumerate(papers, 1):
        title     = (p.get("title") or "")[:120]
        authors   = ", ".join(a["name"] for a in (p.get("authors") or [])[:2])
        year      = p.get("year") or ""
        venue     = p.get("venue") or ""
        highlight = extract_highlight(p.get("abstract", ""))
        url       = get_url(p)

        block = [f"*{i}. {title}*"]
        if authors:
            block.append(f"_{authors} ({year})_")
        if venue:
            block.append(f"📖 {venue}")
        if highlight:
            block.append(highlight)
        if url:
            block.append(f"🔗 [원문]({url})")

        lines.append("\n".join(block))
        lines.append("")

    lines.append(f"🖥 [웹에서 전체 보기]({VERCEL_URL})")
    return "\n".join(lines)

# ── 텔레그램 전송 (4096자 초과 시 분할) ─────────────────────────
def send_telegram(text: str) -> bool:
    MAX = 4000
    parts = []
    while len(text) > MAX:
        cut = text.rfind("\n\n", 0, MAX)
        if cut == -1:
            cut = MAX
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    parts.append(text)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for part in parts:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT,
                "text": part,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if not r.ok:
            print(f"  [ERROR] 텔레그램 전송 실패: {r.text}")
            return False
    return True

# ── 메인 ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Weekly Digest 시작")

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print("[ERROR] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        exit(1)

    all_papers = []
    seen: set = set()

    for journal in JOURNALS:
        print(f"  검색 중: {journal}")
        for p in search_papers(journal, limit=3):
            key = (p.get("title") or "").lower().replace(" ", "")[:50]
            if key not in seen:
                seen.add(key)
                all_papers.append(p)

    print(f"  총 {len(all_papers)}편 수집")

    if not all_papers:
        print("[ERROR] 수집된 논문 없음. 종료.")
        exit(1)

    msg = build_message(all_papers)
    ok  = send_telegram(msg)
    print("✅ 전송 완료" if ok else "❌ 전송 실패")
    exit(0 if ok else 1)
