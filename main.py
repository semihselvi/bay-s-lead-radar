import os, re, json, time, hashlib, warnings
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from google.cloud import firestore
from google.oauth2 import service_account

from config import (
    COLLECTION,
    SCAN_LOG_COLLECTION,
    MAX_RESULTS_PER_SOURCE,
    INTENT_PHRASES,
    ROUTES,
)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

UA = "BAY-S-Lead-Radar/4.2 (+https://github.com/semihselvi)"
REDDIT_URL = "https://www.reddit.com/search.rss"
NEWS_URL = "https://news.google.com/rss/search"
TIMEOUT = 15
MAX_RESULTS = max(10, min(int(MAX_RESULTS_PER_SOURCE), 25))
REDDIT_PER_RUN = 8
NEWS_PER_RUN = 8
MAX_TELEGRAM_LEADS = 5
REDDIT_DELAY = 2
NEWS_DELAY = 0.5

S = requests.Session()
S.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
})

MARKET_INFO = {
    "north_cyprus": (["north cyprus","northern cyprus","kuzey kıbrıs","iskele","long beach","kyrenia","girne","esentepe","famagusta","gazimağusa"], "Prime Kıbrıs"),
    "turkey": (["turkey","türkiye","antalya","alanya","mersin","istanbul","izmir","bodrum","fethiye"], "Turkey Partner"),
    "greece": (["greece","athens","thessaloniki","crete","rhodes","corfu","mykonos"], "Golden Visa Partner"),
    "germany": (["germany","berlin","munich","frankfurt","hamburg","cologne","deutschland"], "Germany Partner"),
    "netherlands": (["netherlands","amsterdam","rotterdam","the hague","utrecht","nederland"], "Netherlands Partner"),
    "belgium": (["belgium","brussels","antwerp","ghent"], "Partner Network"),
    "france": (["france","paris","nice","cannes","marseille","lyon"], "Partner Network"),
    "switzerland": (["switzerland","zurich","geneva","lausanne","basel","zug","lugano"], "Partner Network"),
    "lithuania": (["lithuania","vilnius","kaunas","klaipeda"], "Partner Network"),
    "russia": (["russia","россия","moscow","москва","st petersburg","санкт-петербург"], "Partner Network"),
    "kazakhstan": (["kazakhstan","казахстан","almaty","алматы","astana","астана"], "Partner Network"),
    "montenegro": (["montenegro","budva","kotor","tivat","podgorica","bar"], "Partner Network"),
    "uk": (["united kingdom","uk","london","manchester","birmingham","leeds","brighton"], "Partner Network"),
    "spain": (["spain","madrid","barcelona","valencia","malaga","alicante","marbella"], "Golden Visa Partner"),
    "portugal": (["portugal","lisbon","porto","algarve","cascais"], "Golden Visa Partner"),
    "italy": (["italy","rome","milan","florence","naples","sicily"], "Partner Network"),
    "poland": (["poland","warsaw","krakow","wroclaw","gdansk"], "Partner Network"),
    "austria": (["austria","vienna","salzburg","graz"], "Partner Network"),
    "ireland": (["ireland","dublin","cork","galway"], "Partner Network"),
    "uae": (["uae","united arab emirates","dubai","abu dhabi"], "Partner Network"),
    "qatar": (["qatar","doha"], "Partner Network"),
    "saudi_arabia": (["saudi arabia","riyadh","jeddah"], "Partner Network"),
}

PROPERTY = ["property","real estate","home","house","apartment","condo","flat","villa","townhouse","residence","residential","land","mortgage","down payment","deposit","rental income","rental yield","golden visa","residency by investment","konut","daire","gayrimenkul","mülk","arsa","квартира","дом","недвижимость","ипотека","аренда"]

BUY_INTENT = ["looking to buy","want to buy","wanting to buy","planning to buy","ready to buy","thinking of buying","buying a home","buying a house","buying property","buy an apartment","buy apartment","buy a villa","looking for a house","looking for an apartment","cash buyer","first time buyer","first-time buyer","first home buyer","property buyer","looking to purchase","purchase","how much can i afford","ev almak","ev arıyorum","ev almak istiyorum","satın almak","gayrimenkul almak","yatırım için ev","хочу купить","ищу квартиру","купить квартиру","купить дом","купить недвижимость","планирую купить","недвижимость за рубежом"]

STRONG_INTENT = ["looking to buy","want to buy","planning to buy","ready to buy","looking to purchase","buying property","buy an apartment","property buyer","cash buyer","ev almak","satın almak","хочу купить","купить квартиру","купить недвижимость"]

CONCRETE = ["budget","$","€","£","aed","eur","gbp","usd","chf","try","kzt","rub","mortgage","down payment","deposit","bedroom","1br","2br","3br","1 bhk","2 bhk","3 bhk","rent","rental income","yield","first home","moving","relocating","next month","next year","this year","2026","2027","bütçe","kredi","kapora","kira","taşınmak","мой бюджет","ипотека","переезд"]

PERSONAL = [" i "," i'm"," i am "," we "," we're"," my "," our "," my family"," for myself"," for me","ben ","biz ","ailem","kendim için","я ","мы ","моя семья","для себя"]

AGENCY = ["for my client","for a client","my clients","client looking","buyer client","real estate agent","estate agent","realtor","broker","developer","property developer","property listing","listing page","our properties","our project","contact us","whatsapp us","call us","we sell","available units","new project","commission","lead generation","marketing agency","property management service","агентство недвижимости","риэлтор","застройщик","продам","продается","продаю"]

NOISE_SUBREDDITS = {"memes","funny","askreddit","offmychest","family","askchicago","whatshouldido","whatdoido","arknights"}

# V4.3 Reddit geographic targeting
TARGET_COUNTRY_TERMS = [
    "north cyprus","northern cyprus","kuzey kıbrıs","cyprus",
    "turkey","türkiye","greece","germany","netherlands","belgium","france",
    "switzerland","lithuania","russia","россия","kazakhstan","казахстан",
    "montenegro","united kingdom","uk","london","spain","portugal","italy",
    "poland","austria","ireland","estonia","latvia","finland","sweden","norway",
    "denmark","uae","united arab emirates","dubai","abu dhabi","qatar","doha",
    "saudi arabia","riyadh","jeddah",
]
EXCLUDED_COUNTRY_TERMS = [
    "usa","u.s.a.","u.s.","united states","united states of america","america",
    "new york","los angeles","california","texas","florida","miami","chicago",
    "houston","phoenix","seattle","boston","san francisco",
    "canada","toronto","vancouver","montreal",
    "australia","australian","sydney","melbourne","brisbane","perth",
    "adelaide","canberra","new zealand","auckland","wellington",
]

QUERIES = [
    '"looking to buy" ("North Cyprus" OR "Northern Cyprus" OR "Kuzey Kıbrıs" OR Iskele)',
    '"buy property" ("North Cyprus" OR "Northern Cyprus")',
    '"property investment" ("North Cyprus" OR Cyprus)',
    '"moving to Cyprus" property',
    '"looking to buy" ("Turkey" OR Türkiye) property',
    '"property investment" ("Turkey" OR Türkiye)',
    '"Golden Visa" (Greece OR Portugal OR Spain) property',
    '"residency by investment" property budget',
    '"looking to buy" property (Germany OR Netherlands OR France OR Belgium)',
    '"looking to buy" property (UK OR London)',
    '"looking to buy" property (Switzerland OR Austria)',
    '"buying property abroad" (Russia OR Kazakhstan OR UAE)',
    '"looking for an apartment" investment Europe',
    '"first time buyer" budget property Europe',
    '"хочу купить" недвижимость (Кипр OR Греция OR Турция)',
    '"ищу квартиру" недвижимость (Кипр OR Германия OR Греция)',
    '"недвижимость за рубежом" купить',
    '"ev almak istiyorum" (Kıbrıs OR Türkiye)',
    '"Kıbrıs" ev almak',
]
def db_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON missing")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    return firestore.Client(credentials=creds)

def text(item):
    return f"{item.get('title','')} {item.get('text','')}".strip()

def has(value, terms):
    value = value.lower()
    return any(term.lower() in value for term in terms)

def subreddit(url):
    m = re.search(r"/r/([^/]+)", url or "")
    return m.group(1).lower() if m else ""

def market_for(value):
    v = value.lower()
    for market, (terms, _) in MARKET_INFO.items():
        for term in terms:
            if term.lower() in v:
                return market
    return "unknown"

def extract_budget(value):
    for pattern in [
        r"[$€£₺]\s?[\d,.]+(?:\s?[kKmM])?",
        r"(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB)\s?[\d,.]+(?:\s?[kKmM])?",
        r"\d{2,3}\s?[kKmM]",
    ]:
        m = re.search(pattern, value, re.I)
        if m:
            return m.group(0)
    return "Not stated"

def extract_timeframe(value):
    for pattern in [
        r"(?:within|in|next)\s+\d+\s+(?:days?|weeks?|months?|years?)",
        r"this year", r"next year", r"soon",
        r"immediately", r"2026", r"2027",
    ]:
        m = re.search(pattern, value, re.I)
        if m:
            return m.group(0)
    return "Not stated"

def language(value):
    if re.search(r"[а-яё]", value.lower()):
        return "Russian"
    if has(value, ["ev almak","ev arıyorum","gayrimenkul","kıbrıs","satın almak"]):
        return "Turkish"
    return "English"

def city(value, market):
    if market == "unknown":
        return "Not stated"
    v = value.lower()
    country_terms = {"turkey","türkiye","greece","germany","netherlands","belgium","france","lithuania","switzerland","russia","kazakhstan","montenegro","uk","united kingdom","north cyprus","northern cyprus"}
    for term in MARKET_INFO[market][0]:
        if term.lower() in v and term.lower() not in country_terms:
            return term
    return "Not stated"

def excluded_geography(value):
    v = value.lower()
    return any(term in v for term in EXCLUDED_COUNTRY_TERMS)

def has_target_geography(value):
    v = value.lower()
    return any(term in v for term in TARGET_COUNTRY_TERMS)

def valid(item):
    value = text(item)
    if len(value) < 90:
        return False, "too_short"
    if not has(value, PROPERTY):
        return False, "no_property"
    if not has(value, BUY_INTENT):
        return False, "no_buyer"
    if has(value, AGENCY):
        return False, "agency_or_listing"
    if subreddit(item.get("url","")) in NOISE_SUBREDDITS:
        return False, "noisy_subreddit"
    if not has(value, CONCRETE) and not has(value, PERSONAL):
        return False, "no_concrete_or_personal"

    if excluded_geography(value):
        return False, "excluded_geography"

    strong = has(value, STRONG_INTENT)
    personal = has(value, PERSONAL)
    concrete = has(value, CONCRETE)
    market = market_for(value)
    overseas = has(value, ["abroad","overseas","relocat","moving to","cyprus","north cyprus","northern cyprus","greece","portugal","spain","turkey","golden visa","residency by investment","недвижимость за рубежом"])

    if not strong:
        return False, "weak_intent"
    if not personal and not concrete:
        return False, "weak_buyer_context"
    if market == "unknown" and not has_target_geography(value) and not overseas:
        return False, "no_target_market"
    if market == "unknown" and not overseas and not has(value, ["property investment","investment property","rental income","rental yield","golden visa","residency by investment","buying property abroad"]):
        return False, "no_target_market"
    return True, "ok"

def score(item, market):
    value = text(item).lower()
    strong_hits = sum(1 for p in STRONG_INTENT if p.lower() in value)
    intent_hits = sum(1 for p in INTENT_PHRASES if p.lower() in value)
    has_budget = extract_budget(value) != "Not stated"
    has_timeframe = extract_timeframe(value) != "Not stated"
    concrete = has(value, CONCRETE)
    personal = has(value, PERSONAL)
    target = market != "unknown"
    overseas = has(value, ["abroad","overseas","relocat","moving to","golden visa","residency by investment","north cyprus","northern cyprus"])

    intent = min(100, 42 + strong_hits*8 + min(intent_hits*3,12) + (12 if has_budget else 0) + (10 if has_timeframe else 0) + (8 if personal else 0) + (8 if overseas else 0))
    credibility = min(100, 52 + (18 if personal else 0) + (14 if has_budget else 0) + (8 if has_timeframe else 0) + (8 if concrete else 0) + (5 if len(value) >= 400 else 0))

    fit = 35
    if target:
        fit += 30
    if market == "north_cyprus":
        fit += 25
    elif market in {"turkey","greece","portugal","spain"}:
        fit += 15
    elif overseas:
        fit += 10
    if has_budget:
        fit += 10
    fit = min(100, fit)

    if market == "north_cyprus" and intent >= 82 and credibility >= 78:
        classification = "HOT"
    elif intent >= 76 and credibility >= 72 and fit >= 55:
        classification = "WARM"
    else:
        classification = "REVIEW"
    return intent, credibility, fit, classification

def fingerprint(item):
    raw = "|".join([item.get("url",""),item.get("title",""),item.get("author","")]).lower()
    return hashlib.sha256(raw.encode()).hexdigest()

def parse_reddit(xml_text):
    soup = BeautifulSoup(xml_text, "html.parser")
    rows = []
    for e in soup.find_all("entry")[:MAX_RESULTS]:
        link = e.find("link")
        title = e.find("title")
        content = e.find("content")
        published = e.find("published")
        author = e.find("name")
        rows.append({
            "source":"Reddit",
            "url":link.get("href","").strip() if link else "",
            "title":title.get_text(" ",strip=True) if title else "",
            "text":content.get_text(" ",strip=True) if content else "",
            "published":published.get_text(strip=True) if published else "",
            "author":author.get_text(strip=True) if author else "",
        })
    return rows

def reddit_search(query):
    try:
        r = S.get(REDDIT_URL, params={"q":query,"sort":"new","t":"day","limit":MAX_RESULTS}, timeout=TIMEOUT)
        if r.status_code == 429:
            print(f"REDDIT_429 query={query}")
            return [], True
        r.raise_for_status()
        return parse_reddit(r.text), False
    except requests.RequestException as exc:
        print(f"REDDIT_ERROR {exc}")
        return [], False

def google_news_search(query):
    try:
        r = S.get(NEWS_URL, params={"q":query+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"}, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        for e in soup.find_all("item")[:MAX_RESULTS]:
            link = e.find("link")
            title = e.find("title")
            desc = e.find("description")
            pub = e.find("pubDate")
            rows.append({
                "source":"Google News",
                "url":link.get_text(strip=True) if link else "",
                "title":title.get_text(" ",strip=True) if title else "",
                "text":desc.get_text(" ",strip=True) if desc else "",
                "published":pub.get_text(strip=True) if pub else "",
                "author":"",
            })
        return rows
    except requests.RequestException as exc:
        print(f"GOOGLE_NEWS_ERROR {exc}")
        return []

def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_NOT_CONFIGURED")
        return
    try:
        r = S.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id":chat,"text":message,"disable_web_page_preview":False}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"TELEGRAM_ERROR {exc}")

def format_lead(lead):
    emoji = "🔥" if lead["classification"] == "HOT" else "🟠"
    return (
        f"{emoji} BAY-S RADAR — {lead['classification']}\n\n"
        f"Source: {lead['source']}\n"
        f"Author: {lead.get('author') or 'Not stated'}\n"
        f"Language: {lead['language']}\n"
        f"Market: {lead['market']}\n"
        f"City/Region: {lead['city_region']}\n\n"
        f"What they want:\n{lead['title']}\n\n"
        f"Budget: {lead['budget']}\n"
        f"Timeframe: {lead['timeframe']}\n"
        f"Intent: {lead['intent_score']}/100\n"
        f"Credibility: {lead['credibility_score']}/100\n"
        f"Market Fit: {lead['market_fit_score']}/100\n"
        f"Route To: {lead['route_to']}\n\n"
        f"🔗 {lead['url']}"
    )
def process_rows(rows, db, seen, leads, rejected, errors, started):
    for item in rows:
        if not item.get("url"):
            continue
        key = fingerprint(item)
        if key in seen:
            continue
        seen.add(key)

        ok, reason = valid(item)
        if not ok:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue

        value = text(item)
        market = market_for(value)
        intent, credibility, fit, classification = score(item, market)

        if classification not in {"HOT","WARM"}:
            rejected["low_score"] = rejected.get("low_score", 0) + 1
            continue

        ref = db.collection(COLLECTION).document(key)
        try:
            if ref.get().exists:
                print(f"EXISTING_LEAD: {key}")
                continue
            lead = {
                **item,
                "lead_id": key,
                "language": language(value),
                "market": market,
                "city_region": city(value, market),
                "budget": extract_budget(value),
                "timeframe": extract_timeframe(value),
                "intent_score": intent,
                "credibility_score": credibility,
                "market_fit_score": fit,
                "classification": classification,
                "route_to": MARKET_INFO.get(market, ("", ROUTES.get(market, "Direct Review")))[1],
                "found_at": started.isoformat(),
            }
            ref.set(lead)
            leads.append(lead)
            print(f"NEW_LEAD: {classification} | {market} | {item['url']}")
        except Exception as exc:
            errors["Firestore"] += 1
            print(f"FIRESTORE_ERROR: {exc}")

def main():
    started = datetime.now(timezone.utc)
    print("BAY-S LEAD RADAR V4.3 STARTED")

    db = db_client()
    pool = QUERIES

    state_ref = db.collection(SCAN_LOG_COLLECTION).document("_v42_state")
    snap = state_ref.get()
    offset = int((snap.to_dict() or {}).get("offset", 0)) if snap.exists else 0

    selected = [pool[(offset+i) % len(pool)] for i in range(min(REDDIT_PER_RUN, len(pool)))]
    state_ref.set({
        "offset": (offset + len(selected)) % max(1, len(pool)),
        "pool_size": len(pool),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    print(f"TARGET_QUERY_POOL: {len(pool)}")
    print(f"QUERY_COUNT_THIS_SCAN: {len(selected)}")

    seen, leads = set(), []
    source = {"Reddit":0,"Google News":0}
    errors = {"Reddit":0,"Google News":0,"Firestore":0}
    rejected = {}
    reddit_429 = 0
    reddit_stopped = False

    for idx, query in enumerate(selected, 1):
        print(f"[REDDIT {idx}/{len(selected)}] {query}")
        rows, limited = reddit_search(query)

        if limited:
            reddit_429 += 1
            reddit_stopped = True
            print("REDDIT_STOPPED_EARLY_AFTER_429")
            break

        source["Reddit"] += len(rows)
        process_rows(rows, db, seen, leads, rejected, errors, started)

        if idx < len(selected):
            time.sleep(REDDIT_DELAY)

    news_queries = QUERIES[:NEWS_PER_RUN]
    for idx, query in enumerate(news_queries, 1):
        print(f"[NEWS {idx}/{len(news_queries)}] {query}")
        rows = google_news_search(query)
        source["Google News"] += len(rows)
        process_rows(rows, db, seen, leads, rejected, errors, started)
        if idx < len(news_queries):
            time.sleep(NEWS_DELAY)

    finished = datetime.now(timezone.utc)
    scan = {
        "started_at": started.isoformat(),
        "completed_at": finished.isoformat(),
        "status":"completed",
        "source_results":source,
        "unique_results":len(seen),
        "new_hot_warm":len(leads),
        "source_errors":errors,
        "rejected":rejected,
        "total_query_pool":len(pool),
        "queries_this_scan":len(selected),
        "news_queries_this_scan":len(news_queries),
        "reddit_429_count":reddit_429,
        "reddit_stopped_early":reddit_stopped,
    }

    try:
        db.collection(SCAN_LOG_COLLECTION).document(started.strftime("%Y%m%dT%H%M%SZ")).set(scan)
    except Exception as exc:
        print(f"SCAN_LOG_ERROR: {exc}")

    print(json.dumps(scan, ensure_ascii=False, indent=2))

    leads.sort(key=lambda x: (0 if x["classification"] == "HOT" else 1, -x["intent_score"], -x["credibility_score"], -x["market_fit_score"]))

    if leads:
        for lead in leads[:MAX_TELEGRAM_LEADS]:
            send_telegram(format_lead(lead))
    else:
        send_telegram(
            "ℹ️ BAY-S RADAR\n\n"
            "Tarama tamamlandı.\n"
            "Yeni HOT/WARM buyer lead bulunamadı.\n\n"
            f"Reddit sonuçları: {source['Reddit']}\n"
            f"Google News sonuçları: {source['Google News']}\n"
            "Yeni lead: 0\n"
            f"Reddit 429: {reddit_429}"
        )
    print("BAY-S LEAD RADAR V4.3 FINISHED")

if __name__ == "__main__":
    main()
