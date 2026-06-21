"""
Weekly Digest → Telegram 자동 전송
OpenAlex API 사용 (CORS 무관, 날짜 필터 지원)
"""
import requests, os, re
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
VERCEL_URL     = "https://paper-agent-theta.vercel.app"

JOURNALS = [
    "Nature Nanotechnology","Nature Materials","Nature Electronics",
    "Advanced Functional Materials","Advanced Materials","Materials Today",
    "ACS Nano","Small","npj Computational Materials",
    "npj 2D Materials and Applications","Nano Letters",
    "IEEE Transactions on Electron Devices","IEEE Electron Device Letters",
    "Applied Physics Letters","Journal of Applied Physics",
    "Microelectronic Engineering","Journal of Vacuum Science Technology",
    "Semiconductor Science and Technology","Thin Solid Films",
    "ECS Journal of Solid State Science",
]

def date_ago(days):
    return (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

def rebuild_abstract(inv):
    if not inv: return ''
    words = {}
    for w, positions in inv.items():
        for p in positions: words[p] = w
    if not words: return ''
    return ' '.join(words.get(i,'') for i in range(max(words)+1)).strip()

def parse_work(w):
    doi = (w.get('doi') or '').replace('https://doi.org/','')
    authors = ', '.join(
        a['author']['display_name']
        for a in (w.get('authorships') or [])[:3]
        if a.get('author') and a['author'].get('display_name')
    )
    src = ((w.get('primary_location') or {}).get('source') or {})
    return {
        'title':    (w.get('title') or '').strip(),
        'authors':  authors,
        'year':     w.get('publication_year') or 0,
        'date':     w.get('publication_date') or '',
        'abstract': rebuild_abstract(w.get('abstract_inverted_index')),
        'venue':    src.get('display_name',''),
        'citations':w.get('cited_by_count') or 0,
        'doi':      doi,
        'type':     w.get('type') or '',
    }

def is_research(p):
    if re.match(r'^(editorial|erratum|correction|retraction|book|dataset)',p.get('type',''),re.I): return False
    if re.search(r'highlights of recent|^erratum|^correction\b|global ties|annual report|^masthead|in memoriam',p.get('title',''),re.I): return False
    return True

def search_journal(journal, limit=3, from_date=None):
    f = 'primary_location.source.display_name.search:'+journal
    if from_date: f += ',from_publication_date:'+from_date
    try:
        r = requests.get('https://api.openalex.org/works',
            params={'filter':f,'per-page':limit+8,'sort':'publication_date:desc','mailto':'research@paperagent.app'},
            timeout=20, headers={'User-Agent':'PaperAgent/1.0'})
        if not r.ok: print(f'  [WARN] {journal}: {r.status_code}'); return []
        works = [parse_work(w) for w in r.json().get('results',[])]
        return [p for p in works if is_research(p)][:limit]
    except Exception as e: print(f'  [ERROR] {journal}: {e}'); return []

def extract_highlight(abstract):
    if not abstract: return ''
    sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])',abstract) if len(s.strip())>20]
    kw = ['show','demonstrat','achiev','exhibit','improv','enhanc','reduc','%','nm ','eV ','times','fold','superior','result','record']
    res = [s for s in sents if any(k in s.lower() for k in kw)]
    return ' '.join((res[:2] if res else sents[-2:]))[:300]

def build_message(papers):
    today = datetime.now().strftime('%Y.%m.%d')
    lines = [f'📅 *Weekly Digest — {today}*', f'반도체·재료공학 신규 논문 *{len(papers)}편*\n']
    for i,p in enumerate(papers,1):
        block = [f'*{i}. {(p["title"] or "")[:120]}*']
        if p['authors']: block.append(f'_{p["authors"]} ({p["date"] or p["year"]})_')
        if p['venue']:   block.append(f'📖 {p["venue"]}')
        hi = extract_highlight(p['abstract'])
        if hi: block.append(hi)
        if p['doi']: block.append(f'🔗 [원문](https://doi.org/{p["doi"]})')
        lines += ['\n'.join(block),'']
    lines.append(f'🖥 [웹에서 전체 보기]({VERCEL_URL})')
    return '\n'.join(lines)

def send_telegram(text):
    MAX=4000; parts=[]
    while len(text)>MAX:
        cut=text.rfind('\n\n',0,MAX)
        if cut==-1: cut=MAX
        parts.append(text[:cut]); text=text[cut:].lstrip()
    parts.append(text)
    url=f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    for part in parts:
        r=requests.post(url,json={'chat_id':TELEGRAM_CHAT,'text':part,'parse_mode':'Markdown','disable_web_page_preview':True},timeout=15)
        if not r.ok: print(f'  [ERROR] {r.text}'); return False
    return True

if __name__=='__main__':
    from_date=date_ago(7)
    print(f'[{datetime.now().strftime("%H:%M:%S")}] 시작 (기간: {from_date} ~ 오늘)')
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print('[ERROR] 환경변수 미설정'); exit(1)
    all_papers=[]; seen=set()
    for j in JOURNALS:
        print(f'  {j}')
        for p in search_journal(j, limit=3, from_date=from_date):
            key=(p['title'] or '').lower()[:50]
            if key not in seen: seen.add(key); all_papers.append(p)
    print(f'  총 {len(all_papers)}편')
    if not all_papers: print('[INFO] 이번 주 신규 논문 없음'); exit(0)
    ok=send_telegram(build_message(all_papers))
    print('✅ 완료' if ok else '❌ 실패'); exit(0 if ok else 1)
