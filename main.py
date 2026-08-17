import os, re, hashlib, json, html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, urlparse
import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
from config import *

UA = "BAYS-Web-Radar/1.0 (+https://github.com/)"

def get(url, params=None, timeout=30):
    return requests.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout)

def reddit_search(query):
    url="https://www.reddit.com/search.rss"
    r=get(url, {"q":query, "sort":"new", "t":"day"})
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"xml")
    out=[]
    for e in soup.find_all("entry")[:MAX_RESULTS_PER_SOURCE]:
        link=e.find("link")
        out.append({
            "source":"Reddit",
            "url": link.get("href","") if link else "",
            "title": e.find("title").get_text(" ",strip=True) if e.find("title") else "",
            "text": e.find("content").get_text(" ",strip=True) if e.find("content") else "",
            "published": e.find("published").get_text(strip=True) if e.find("published") else "",
            "author": e.find("name").get_text(strip=True) if e.find("name") else "",
        })
    return out

def google_news(query):
    url="https://news.google.com/rss/search"
    r=get(url, {"q":query+" when:1d", "hl":"en-US","gl":"US","ceid":"US:en"})
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"xml")
    out=[]
    for e in soup.find_all("item")[:MAX_RESULTS_PER_SOURCE]:
        out.append({
            "source":"Google News RSS",
            "url": e.find("link").get_text(strip=True) if e.find("link") else "",
            "title": e.find("title").get_text(" ",strip=True) if e.find("title") else "",
            "text": e.find("description").get_text(" ",strip=True) if e.find("description") else "",
            "published": e.find("pubDate").get_text(strip=True) if e.find("pubDate") else "",
            "author": "",
        })
    return out

def ddg_search(query):
    r=get("https://html.duckduckgo.com/html/", {"q":query, "df":"d"}, timeout=30)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    out=[]
    for a in soup.select("a.result__a")[:MAX_RESULTS_PER_SOURCE]:
        href=a.get("href","")
        parent=a.find_parent("div", class_="result")
        snippet=parent.select_one(".result__snippet") if parent else None
        out.append({
            "source":"Public Web",
            "url":href,
            "title":a.get_text(" ",strip=True),
            "text":snippet.get_text(" ",strip=True) if snippet else "",
            "published":"",
            "author":"",
        })
    return out

def build_queries():
    intents=[
        "looking to buy property","looking for apartment","looking for house",
        "property investment budget","moving and buying property",
        "relocating and buying a home","Golden Visa property","residency by investment property",
    ]
    queries=[]
    for market, places in MARKETS.items():
        for place in places[:3]:
            for intent in intents[:4]:
                queries.append(f'"{place}" "{intent}"')
        # Russian-specific searches
        if market in ("russia","kazakhstan"):
            queries += [
                f'"{places[0]}" "хочу купить" недвижимость',
                f'"{places[0]}" "ищу квартиру"',
                f'"{places[0]}" "недвижимость за рубежом"',
            ]
    queries += [
        '"Golden Visa" property buyer Greece',
        '"EU Golden Visa" property budget',
        '"residency by investment" property Europe',
        '"Switzerland" "looking to buy" property',
        '"Germany" "looking to buy" property',
        '"Netherlands" "looking to buy" property',
        '"France" "looking to buy" property',
    ]
    return list(dict.fromkeys(queries))

def market_for(text):
    t=text.lower()
    for m, places in MARKETS.items():
        if any(p.lower() in t for p in places):
            return m
    return "unknown"

def score(item, market):
    t=(item["title"]+" "+item["text"]).lower()
    intent_hits=sum(p.lower() in t for p in INTENT_PHRASES)
    exclude_hits=sum(p.lower() in t for p in EXCLUDE_PHRASES)
    budget=bool(re.search(r'[$€£₺]\s?[\d,.]+|\b\d{2,3}\s?[kKmM]\b|\b\d{4,}\b',t))
    timeframe=any(x in t for x in ["month","months","weeks","year","soon","this year","2026","2027","within"])
    personal=any(x in t for x in ["i ","we ","my ","our ","i'm ","we're ","ben ","biz ","я ","мы "])
    intent=min(100,35+intent_hits*7+(12 if budget else 0)+(10 if timeframe else 0)+(8 if personal else 0)-exclude_hits*20)
    credibility=min(100,55+(12 if budget else 0)+(10 if timeframe else 0)+(10 if len(t)>450 else 0)+(8 if personal else 0)-exclude_hits*25)
    fit=55 if market!="unknown" else 35
    if budget: fit+=12
    if market in ("north_cyprus","greece","germany","netherlands","france","switzerland"): fit+=8
    fit=max(0,min(100,fit))
    if intent>=82 and credibility>=75 and fit>=60: cls="HOT"
    elif intent>=62 and credibility>=65 and fit>=45: cls="WARM"
    else: cls="REVIEW"
    return intent,credibility,fit,cls

def fp(item):
    raw="|".join([item.get("url",""),item.get("title",""),item.get("author","")])
    return hashlib.sha256(raw.lower().encode()).hexdigest()

def db():
    raw=os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON missing")
    creds=service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)

def telegram(text):
    token=os.environ.get("TELEGRAM_BOT_TOKEN")
    chat=os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat: return
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id":chat,"text":text,"disable_web_page_preview":False},timeout=20)

def main():
    started=datetime.now(timezone.utc)
    queries=build_queries()
    client=db()
    seen=set(); candidates=[]; errors=0
    source_counts={}
    for q in queries:
        for fn in (reddit_search, google_news, ddg_search):
            try:
                results=fn(q)
                source_counts[fn.__name__]=source_counts.get(fn.__name__,0)+len(results)
            except Exception as e:
                errors+=1
                print("SOURCE_ERROR",fn.__name__,str(e))
                continue
            for item in results:
                if not item.get("url"): continue
                key=fp(item)
                if key in seen: continue
                seen.add(key)
                m=market_for(item["title"]+" "+item["text"])
                i,c,f,cls=score(item,m)
                if cls not in ("HOT","WARM"): continue
                ref=client.collection(COLLECTION).document(key)
                if ref.get().exists: continue
                lead={
                    **item,"lead_id":key,"market":m,"route_to":ROUTES.get(m,"Direct Review"),
                    "intent_score":i,"credibility_score":c,"market_fit_score":f,
                    "classification":cls,"found_at":started.isoformat()
                }
                ref.set(lead)
                candidates.append(lead)
    completed=datetime.now(timezone.utc)
    scan={
        "started_at":started.isoformat(),"completed_at":completed.isoformat(),
        "status":"completed","queries":len(queries),"unique_results":len(seen),
        "new_hot_warm":len(candidates),"source_counts":source_counts,"errors":errors
    }
    client.collection(SCAN_LOG_COLLECTION).document(started.strftime("%Y%m%dT%H%M%SZ")).set(scan)
    if candidates:
        for x in candidates[:10]:
            msg=(f"{'🔥' if x['classification']=='HOT' else '🟡'} BAY-S RADAR — {x['classification']}\n"
                 f"{x['market']} | {x['route_to']}\n{x['title']}\n"
                 f"Intent {x['intent_score']} | Credibility {x['credibility_score']} | Market Fit {x['market_fit_score']}\n"
                 f"{x['url']}")
            telegram(msg)
    else:
        telegram("ℹ️ BAY-S RADAR — Tarama tamamlandı.\nSon taramadan beri yeni HOT/WARM lead bulunamadı.")
    print(json.dumps({"scan":scan,"new_leads":candidates},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
