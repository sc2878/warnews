from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import feedparser
import requests
from datetime import datetime, timezone
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf

app = FastAPI()

# THREADPOOL (과부하 방지)
executor = ThreadPoolExecutor(max_workers=5)

# 캐시
CACHE = []
LAST_UPDATE = 0
MARKET_CACHE = []
TRANSLATE_CACHE = {}

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
    "DEFENSE NEWS": "https://www.defensenews.com/arc/outboundfeeds/rss/",
    "THE WAR ZONE": "https://www.thedrive.com/the-war-zone/feed",
    "FINANCIAL JUICE": "https://www.financialjuice.com/feed",
    "LIVEUAMAP": "https://liveuamap.com/en/rss"
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

MARKET_TICKERS = ["^GSPC","^NDX","CL=F","GC=F","DX-Y.NYB","BTC-USD"]

MARKET_NAMES = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq-100",
    "CL=F": "WTI",
    "GC=F": "GOLD",
    "DX-Y.NYB": "US Dollar Index",
    "BTC-USD": "BTC"
}

def translate_to_korean(text):
    if text in TRANSLATE_CACHE:
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
        for entry in feed.entries[:8]:
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
    except:
        pass
    return results

def collect_news():
    all_results=[]
    futures=[]

    for publisher,url in RSS_FEEDS.items():
        futures.append(executor.submit(fetch_feed,publisher,url))

    for f in futures:
        try:
            all_results.extend(f.result(timeout=5))
        except:
            continue

    all_results.sort(key=lambda x: x["raw_time"] or 0, reverse=True)
    return all_results

def collect_markets():
    global MARKET_CACHE
    results=[]
    for symbol in MARKET_TICKERS:
        try:
            t = yf.Ticker(symbol)
            info = t.history(period="2d", interval="1d")

            if info.empty or len(info) < 2:
                continue

            last_row = info.iloc[-1]
            prev_row = info.iloc[-2]

            price = float(last_row['Close'])
            change_pct = ((last_row['Close'] - prev_row['Close']) / prev_row['Close'] * 100)

            results.append({
                "name": MARKET_NAMES.get(symbol, symbol),
                "price": price,
                "change": f"{change_pct:+.2f}"
            })
        except:
            continue

    MARKET_CACHE = results

async def background_collector():
    global CACHE, LAST_UPDATE
    while True:
        loop = asyncio.get_event_loop()

        news = await loop.run_in_executor(executor, collect_news)
        CACHE = news

        await loop.run_in_executor(executor, collect_markets)

        LAST_UPDATE = datetime.now().timestamp()
        await asyncio.sleep(10)

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

@app.get("/",response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>War News</title>
</head>
<body>
<script>
let html=[]
html.push(`<div class="card">TEST</div>`)
</script>
</body>
</html>
"""