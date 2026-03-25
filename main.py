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

# THREADPOOL
executor = ThreadPoolExecutor(max_workers=10)

# 메모리 캐시
CACHE = []
LAST_UPDATE = 0
MARKET_CACHE = []

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

MARKET_TICKERS = ["^GSPC","^NDX","CL=F","GC=F","DX-Y.NYB","BTC-USD"]

MARKET_NAMES = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq-100",
    "KRW=X": "USD",
    "EURKRW=X": "EUR",
    "JPYKRW=X": "JPY",
    "CL=F": "WTI",
    "GC=F": "Gold",
    "SI=F": "Silver",
    "BTC-USD": "BTC",
    "ETH-USD": "ETC"
}

def translate_to_korean(text):
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
        return r.json()[0][0][0]
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
        for entry in feed.entries[:10]:
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
        futures.append(
            executor.submit(fetch_feed,publisher,url)
        )
    for f in futures:
        all_results.extend(f.result())
    all_results.sort(
        key=lambda x: x["raw_time"] or 0,
        reverse=True
    )
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
    global CACHE,LAST_UPDATE
    while True:
        loop=asyncio.get_event_loop()
        news=await loop.run_in_executor(
            executor,
            collect_news
        )
        CACHE=news
        await loop.run_in_executor(executor, collect_markets)
        LAST_UPDATE=datetime.now().timestamp()
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup():
    asyncio.create_task(background_collector())

@app.get("/api/news")
async def get_news():
    return JSONResponse(content={"news":CACHE})

@app.get("/api/markets")
async def get_markets():
    return JSONResponse(content={"markets":MARKET_CACHE})

@app.get("/",response_class=HTMLResponse)
async def index():
    return """

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>War News</title>
<style>
body{
background:#000;
margin:0;
font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
color:white;
}
.topbar{
position:sticky;
top:0;
background:#000;
z-index:1000;
border-bottom:1px solid #222;
padding-bottom:0;
}
.topbar .container{
padding-bottom:0;
margin-bottom:0;
}
.container{
max-width:1100px;
margin:auto;
padding:0 20px 40px 20px;
}
.header{
padding:20px 0 10px 0;
font-size:28px;
font-weight:600;
}
.ticker{
width:100%;
overflow:hidden;
border-top:1px solid #111;
border-bottom:1px solid #111;
background:#050505;
}
.ticker-track{
white-space:nowrap;
display:inline-block;
padding:8px 0;
animation:tickerMove 35s linear infinite;
font-size:13px;
}
.ticker-item{
margin-right:40px;
}
.up{ color:#22c55e; }
.down{ color:#ef4444; }
@keyframes tickerMove{
0%{transform:translateX(100%)}
100%{transform:translateX(-100%)}
}
.buttons{
padding:14px 0 16px 0;
}
button{
padding:8px 16px;
margin-right:10px;
border:none;
border-radius:6px;
background:#1f1f1f;
color:white;
cursor:pointer;
font-size:14px;
}
button.active{ background:#2563eb; }
#btn-BREAKING{
background:#2a0f0f;
border:1px solid #ef4444;
}
#btn-BREAKING.active{
background:#3a1414;
border:1px solid #ff4d4d;
box-shadow:0 0 6px rgba(239,68,68,0.4);
}
#news{
width:100%;
margin-top:10px;
}
.card{
background:#1a1a1a;
padding:12px 18px;
border-radius:10px;
margin-bottom:8px;
border:1px solid #2a2a2a;
}
.breaking-card{
background:#2a0f0f;
border:1px solid #ef4444;
box-shadow:0 0 6px rgba(239,68,68,0.35);
}
.meta{
font-size:12px;
color:#9ca3af;
margin-bottom:4px;
}
.title{
font-size:14px;
line-height:1.35;
font-weight:500;
}
.breaking{ color:#ef4444; font-weight:600; }
a{ text-decoration:none; color:white; }
a:hover{ opacity:0.85; }
</style>
</head>

<body>

<div class="topbar">
<div class="container">
<div class="header">War News</div>

<div class="ticker">
<div class="ticker-track" id="ticker"></div>
</div>

<div class="buttons">
<button onclick="setFilter('ALL')" id="btn-ALL" class="active">전체 뉴스</button>
<button onclick="setFilter('BREAKING')" id="btn-BREAKING">주요 속보</button>
</div>

</div>
</div>

<div class="container">
<div id="news"></div>
</div>

<script>
let allNews=[]
let currentFilter="ALL"

function setFilter(type){
currentFilter=type
document.querySelectorAll("button").forEach(b=>b.classList.remove("active"))
document.getElementById("btn-"+type).classList.add("active")
render()
}

function render(){
const container=document.getElementById("news")
container.innerHTML=""
const filtered=currentFilter==="ALL"? allNews : allNews.filter(n=>n.breaking)
if(filtered.length===0){ container.innerHTML="<p>관련 뉴스가 없습니다.</p>"; return }
let html=[]
filtered.forEach(n=>{
const cardClass = n.breaking ? "card breaking-card" : "card"
html.push(`<div class="${cardClass}"><div class="meta">${n.publisher} | ${n.time}</div><div class="title ${n.breaking ? "breaking":""}"><a href="${n.link}" target="_blank">${n.breaking ? "[속보] ":""}${n.title}</a></div></div>`)
})
container.innerHTML = html.join("")
}

async function loadNews(){
try{
const res=await fetch("/api/news")
const data=await res.json()
allNews=data.news
render()
}catch(e){
document.getElementById("news").innerHTML="서버 연결 오류"
}
}
loadNews()
setInterval(loadNews,30000)

// MARKET TICKER
async function loadMarkets(){
try{
const res=await fetch("/api/markets")
const data=await res.json()
const ticker=document.getElementById("ticker")
let tickerHtml=[]
data.markets.forEach(m=>{
const cls = parseFloat(m.change) < 0 ? "down" : "up"
const priceFormatted = Number(m.price).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:2})
const changeFormatted = `(${m.change}%)`
tickerHtml.push(`<span class="ticker-item"><span class="ticker-name" style="color:#ffffff">${m.name}</span> <span class="ticker-price ${cls}" style="color:${cls==='up'?'#22c55e':'#ef4444'}">${priceFormatted} ${changeFormatted}</span></span>`)
})
ticker.innerHTML = tickerHtml.join("")
}catch(e){console.log("Market API error",e)}
}
loadMarkets()
setInterval(loadMarkets,10000)
</script>

</body>
</html>
"""