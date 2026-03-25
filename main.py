from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import feedparser
import requests
from datetime import datetime, timezone
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict

app = FastAPI()

# 🔴 THREADPOOL 축소
executor = ThreadPoolExecutor(max_workers=2)

# 캐시
CACHE = []
LAST_UPDATE = 0
MARKET_CACHE = []

# 🔴 LRU 번역 캐시
TRANSLATE_CACHE = OrderedDict()
MAX_TRANSLATE_CACHE = 200

RSS_FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "CNN": "https://rss.cnn.com/rss/edition_world.rss",
    "REUTERS": "https://www.reuters.com/world/rss.xml",
    "AL JAZEERA": "https://www.aljazeera.com/xml/rss/all.xml",
    "NYT": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "GUARDIAN": "https://www.theguardian.com/world/rss",
    "AP": "https://apnews.com/hub/world-news?utm_source=rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
    "ABC": "https://abcnews.go.com/abcnews/internationalheadlines",
    "CBS": "https://www.cbsnews.com/latest/rss/world",
    "FOX": "https://moxie.foxnews.com/google-publisher/world.xml",
}

WAR_KEYWORDS = [
    "war","military","battle","airstrike","shelling","invasion",
    "troops","missile","attack","bombing","offensive",
    "conflict","escalation","ceasefire"
]

BREAKING_WORDS = [
    "breaking","urgent","attack","bombing",
    "airstrike","offensive","escalation","missile"
]

# 🔴 번역 (LRU 적용)
def translate_to_korean(text):
    if text in TRANSLATE_CACHE:
        TRANSLATE_CACHE.move_to_end(text)
        return TRANSLATE_CACHE[text]
    try:
        url="https://translate.googleapis.com/translate_a/single"
        params={
            "client":"gtx",
            "sl":"en",
            "tl":"ko",
            "dt":"t",
            "q":text
        }
        r=requests.get(url,params=params,timeout=2)
        translated = r.json()[0][0][0]

        TRANSLATE_CACHE[text] = translated
        if len(TRANSLATE_CACHE) > MAX_TRANSLATE_CACHE:
            TRANSLATE_CACHE.popitem(last=False)

        return translated
    except:
        return text

def time_ago(struct_time):
    try:
        dt=datetime(*struct_time[:6],tzinfo=timezone.utc)
        now=datetime.now(timezone.utc)
        diff=(now-dt).total_seconds()
        minutes=int(diff//60)
        hours=int(diff//3600)
        if minutes<60:
            return f"{minutes}분 전"
        elif hours<24:
            return f"{hours}시간 전"
        else:
            return dt.strftime("%Y-%m-%d")
    except:
        return ""

def fetch_feed(publisher,url):
    results=[]
    seen=set()
    try:
        feed=feedparser.parse(url)

        # 🔴 8 → 5 축소
        for entry in feed.entries[:5]:
            title=entry.get("title","")
            lower=title.lower()

            if not any(k in lower for k in WAR_KEYWORDS):
                continue

            hash_id=hashlib.md5(title.encode()).hexdigest()
            if hash_id in seen:
                continue
            seen.add(hash_id)

            published_time=entry.get("published_parsed")
            display_time=time_ago(published_time) if published_time else ""

            is_breaking=any(w in lower for w in BREAKING_WORDS)

            translated=translate_to_korean(title)

            results.append({
                "title":translated,
                "publisher":publisher,
                "time":display_time,
                "breaking":is_breaking,
                "link":entry.get("link"),
                "raw_time":published_time
            })

        del feed  # 🔴 메모리 해제
    except:
        pass

    return results

def collect_news():
    all_results=[]
    futures=[]

    for publisher,url in RSS_FEEDS.items():
        futures.append(
            executor.submit(fetch_feed,publisher,url)
        )

    for f in futures:
        try:
            all_results.extend(f.result(timeout=5))
        except:
            continue

    all_results.sort(
        key=lambda x: x["raw_time"] or 0,
        reverse=True
    )

    return all_results

# 🔴 market 기능 제거 (메모리 절약)
def collect_markets():
    global MARKET_CACHE
    MARKET_CACHE = []

# 🔴 백그라운드 캐시 루프
async def background_collector():
    global CACHE, LAST_UPDATE

    while True:
        loop = asyncio.get_event_loop()

        news = await loop.run_in_executor(
            executor,
            collect_news
        )

        CACHE = news

        await loop.run_in_executor(
            executor,
            collect_markets
        )

        LAST_UPDATE = datetime.now().timestamp()

        # 🔴 10 → 30초
        await asyncio.sleep(30)

@app.on_event("startup")
async def startup():
    loop = asyncio.get_event_loop()

    news = await loop.run_in_executor(executor, collect_news)
    CACHE.extend(news)

    await loop.run_in_executor(executor, collect_markets)

    asyncio.create_task(background_collector())

@app.get("/api/news")
async def get_news():
    return JSONResponse(content={"news":CACHE})

@app.get("/api/markets")
async def get_markets():
    return JSONResponse(content={"markets":MARKET_CACHE})

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <html>
        <head><title>War News</title></head>
        <body>
            <h1>War News</h1>
            <div id="news"></div>

            <script>
                fetch('/api/news')
                .then(res => res.json())
                .then(data => {
                    const container = document.getElementById('news');
                    data.news.forEach(n => {
                        const div = document.createElement('div');
                        div.innerHTML = `<p>${n.title} (${n.publisher})</p>`;
                        container.appendChild(div);
                    });
                });
            </script>
        </body>
    </html>
    """