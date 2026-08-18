import os, re, json, time, hashlib, warnings
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from google.cloud import firestore
from google.oauth2 import service_account
from config import COLLECTION, SCAN_LOG_COLLECTION, MAX_RESULTS_PER_SOURCE, INTENT_PHRASES, ROUTES

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

UA = "BAY-S-Lead-Radar/4.6 (+https://github.com/semihselvi)"
TIMEOUT = 20
MAX_RESULTS = max(10, min(int(MAX_RESULTS_PER_SOURCE), 20))
MAX_TELEGRAM_LEADS = 5
SERPER_URL = "https://google.serper.dev/search"

S = requests.Session()
S.headers.update({
    "User-Agent": UA,
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
})

MARKETS = {
    "north_cyprus": (["north cyprus","northern cyprus","kuzey kıbrıs","iskele","long beach","kyrenia","girne","esentepe","famagusta","gazimağusa"], "Prime Kıbrıs"),
    "turkey": (["turkey","türkiye","antalya","alanya","mersin","istanbul","izmir","bodrum","fethiye","ankara","bursa","muğla"], "Turkey Partner"),
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
    "uk": (["united kingdom","uk","britain","london","manchester","birmingham","leeds","brighton"], "Partner Network"),
    "spain": (["spain","madrid","barcelona","valencia","malaga","alicante","marbella"], "Golden Visa Partner"),
    "portugal": (["portugal","lisbon","porto","algarve","cascais"], "Golden Visa Partner"),
    "italy": (["italy","rome","milan","florence","naples","sicily"], "Partner Network"),
    "poland": (["poland","warsaw","krakow","wroclaw","gdańsk"], "Partner Network"),
    "austria": (["austria","vienna","salzburg","graz"], "Partner Network"),
    "ireland": (["ireland","dublin","cork","galway"], "Partner Network"),
    "uae": (["uae","united arab emirates","dubai","abu dhabi"], "Partner Network"),
    "qatar": (["qatar","doha"], "Partner Network"),
    "saudi_arabia": (["saudi arabia","riyadh","jeddah"], "Partner Network"),
}

EXCLUDED_GEOGRAPHY = [
    "usa","u.s.a.","united states","united states of america","america",
    "new york","los angeles","california","texas","florida","miami","chicago",
    "houston","phoenix","seattle","boston","san francisco",
    "canada","toronto","vancouver","montreal",
    "australia","australian","sydney","melbourne","brisbane","perth","adelaide","canberra",
    "new zealand","auckland","wellington",
]

PROPERTY = [
    "property","real estate","home","house","apartment","condo","flat","villa",
    "townhouse","residence","residential","land","mortgage","down payment","deposit",
    "rental income","rental yield","golden visa","residency by investment","ev",
    "konut","daire","gayrimenkul","mülk","arsa","kira","квартира","дом",
    "недвижимость","ипотека","аренда"
]

BUY_INTENT = [
    "looking to buy","want to buy","wanting to buy","planning to buy","ready to buy",
    "thinking of buying","buying a home","buying a house","buying property",
    "buy an apartment","buy apartment","looking for an apartment","looking for a house",
    "cash buyer","first time buyer","first-time buyer","first home buyer","property buyer",
    "looking to purchase","purchase","how much can i afford","ev almak","ev arıyorum",
    "ev almak istiyorum","satın almak","gayrimenkul almak","yatırım için ev","хочу купить",
    "ищу квартиру","купить квартиру","купить дом","купить недвижимость","планирую купить",
    "недвижимость за рубежом","ev sahibi olmak","ev almayı düşünüyorum","ev alacağım",
    "ev almayı planlıyorum","konut kredisi"
]

STRONG_INTENT = [
    "looking to buy","want to buy","planning to buy","ready to buy","looking to purchase",
    "buying property","buy an apartment","property buyer","cash buyer","ev almak",
    "satın almak","хочу купить","купить квартиру","купить недвижимость","ev sahibi olmak",
    "ev almayı düşünüyorum","ev alacağım","ev almayı planlıyorum"
]

CONCRETE = [
    "budget","$","€","£","aed","eur","gbp","usd","chf","try","kzt","rub","tl","milyon",
    "million","mortgage","down payment","deposit","bedroom","1br","2br","3br","1+1",
    "2+1","3+1","1 bhk","2 bhk","3 bhk","rent","rental income","yield","first home",
    "moving","relocating","next month","next year","this year","2026","2027","bütçe",
    "kredi","kapora","kira","taşınmak","peşinat","taksit","konut kredisi","мой бюджет",
    "ипотека","переезд"
]

PERSONAL = [
    " i "," i'm"," i am "," we "," we're"," my "," our "," my family"," for myself",
    " for me","ben ","biz ","ailem","kendim için","я ","мы ","моя семья","для себя"
]

AGENCY = [
    "for my client","for a client","my clients","client looking","buyer client",
    "real estate agent","estate agent","realtor","broker","developer","property developer",
    "property listing","listing page","our properties","our project","contact us",
    "whatsapp us","call us","we sell","available units","new project","commission",
    "lead generation","marketing agency","property management service",
    "агентство недвижимости","риэлтор","застройщик","продам","продается","продаю"
]

SEARCH_QUERIES = [
    'site:forum.donanimhaber.com "ev alacağım" konut',
    'site:forum.donanimhaber.com "konut kredisi" "ev al"',
    'site:forum.donanimhaber.com "ev almayı düşünüyorum"',
    'site:forum.donanimhaber.com "kira getirisi" ev yatırım',
    'site:technopat.net/sosyal "ev almak" emlak',
    'site:technopat.net/sosyal "konut kredisi" ev',
    'site:technopat.net/sosyal "yatırım için" daire',
    'site:r10.net "ev satın almak" gayrimenkul',
    'site:r10.net "ev almak istiyorum"',
    'site:r10.net "yatırım için ev"',
    'site:expat.com/en/forum "property in Northern Cyprus"',
    'site:expat.com/en/forum "buying property in Cyprus"',
    'site:expat.com/en/forum "buying property in Turkey"',
    'site:britishexpats.com/forum "property" Cyprus',
    'site:britishexpats.com/forum "buying" "North Cyprus"',
    'site:britishexpats.com/forum "holiday home" Cyprus',
    'site:forums.moneysavingexpert.com "property abroad" buying',
    'site:forums.moneysavingexpert.com "buying property abroad" budget',
    'site:forums.moneysavingexpert.com "mortgage" "property abroad"',
    'site:forums.moneysavingexpert.com "buying property" overseas',
    '"Kıbrıs" "ev almak" bütçe',
    '"Kuzey Kıbrıs" "ev almak"',
    '"Türkiye" "ev almak istiyorum" bütçe',
    '"gayrimenkul yatırımı" "bütçe"',
]

NEWS_QUERIES = [
    '"Kuzey Kıbrıs" "ev almak"',
    '"Kuzey Kıbrıs" gayrimenkul yatırım',
    '"Kıbrıs" property buyer',
    '"Türkiye" "ev almak" bütçe',
    '"konut kredisi" "ev alacağım"',
    '"gayrimenkul yatırımı" Türkiye',
    '"Golden Visa" property Greece',
    '"buying property abroad" budget',
]

def db_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON missing")
    creds = service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)

def has(value, terms):
    v = value.lower()
    return any(t.lower() in v for t in terms)

def text(item):
    return f"{item.get('title','')} {item.get('text','')}".strip()

def market_for(value):
    v = value.lower()
    for market, (terms, _) in MARKETS.items():
        for term in terms:
            if term.lower() in v:
                return market
    return "unknown"

def budget(value):
    for pattern in [
        r"[$€£₺]\s?[\d,.]+(?:\s?[kKmM])?",
        r"\b(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB|TL)\s?[\d,.]+(?:\s?[kKmM])?\b",
        r"\b\d{1,3}(?:[.,]\d{3})+(?:\s?(?:TL|tl))?\b",
        r"\b\d+(?:[.,]\d+)?\s?(?:milyon|million|M|K|bin)\b",
    ]:
        m = re.search(pattern, value, re.I)
        if m:
            return m.group(0)
    return "Not stated"

def timeframe(value):
    for pattern in [
        r"\b(?:within|in|next)\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
        r"\b(?:\d+)\s+(?:ay|months?)\b",
        r"\bthis year\b", r"\bnext year\b", r"\bsoon\b", r"\bimmediately\b", r"\b2026\b", r"\b2027\b",
    ]:
        m = re.search(pattern, value, re.I)
        if m:
            return m.group(0)
    return "Not stated"

def language(value):
    if re.search(r"[а-яё]", value.lower()):
        return "Russian"
    if has(value, ["ev almak","ev arıyorum","gayrimenkul","kıbrıs","satın almak","konut kredisi"]):
        return "Turkish"
    return "English"

def city(value, market):
    if market == "unknown":
        return "Not stated"
    v = value.lower()
    country_terms = {"turkey","türkiye","greece","germany","netherlands","belgium","france","lithuania","switzerland","russia","kazakhstan","montenegro","uk","united kingdom","north cyprus","northern cyprus"}
    for term in MARKETS[market][0]:
        if term.lower() in v and term.lower() not in country_terms:
            return term
    return "Not stated"

def fingerprint(item):
    raw = "|".join([item.get("url",""), item.get("title",""), item.get("author","")]).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def excluded_geo(value):
    v = value.lower()
    return any(t in v for t in EXCLUDED_GEOGRAPHY)

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
    if excluded_geo(value):
        return False, "excluded_geography"
    if not has(value, CONCRETE) and not has(value, PERSONAL):
        return False, "no_concrete_or_personal"
    market = market_for(value)
    overseas = has(value, [
        "abroad","overseas","relocat","moving to","cyprus","north cyprus",
        "northern cyprus","greece","portugal","spain","turkey","golden visa",
        "residency by investment","недвижимость за рубежом"
    ])
    strong = has(value, STRONG_INTENT)
    if not strong:
        return False, "weak_intent"
    if market == "unknown" and not overseas and not has(value, [
        "property investment","investment property","rental income","rental yield",
        "golden visa","residency by investment","buying property abroad",
        "konut kredisi","ev almak","ev almayı düşünüyorum"
    ]):
        return False, "no_target_market"
    return True, "ok"

def score(item, market):
    value = text(item).lower()
    strong_hits = sum(1 for p in STRONG_INTENT if p.lower() in value)
    intent_hits = sum(1 for p in INTENT_PHRASES if p.lower() in value)
    has_budget = budget(value) != "Not stated"
    has_time = timeframe(value) != "Not stated"
    concrete = has(value, CONCRETE)
    personal = has(value, PERSONAL)
    target = market != "unknown"
    abroad = has(value, [
        "abroad","overseas","relocat","moving to","golden visa",
        "residency by investment","north cyprus","northern cyprus","cyprus"
    ])

    intent = min(100, 40 + strong_hits*8 + min(intent_hits*3,12) +
                 (12 if has_budget else 0) + (10 if has_time else 0) +
                 (8 if personal else 0) + (10 if abroad else 0))

    credibility = min(100, 50 + (18 if personal else 0) +
                      (14 if has_budget else 0) + (8 if has_time else 0) +
                      (8 if concrete else 0) + (7 if len(value) >= 400 else 0))

    fit = 35 + (30 if target else 0) + (25 if market == "north_cyprus" else 0) + \
          (15 if market in {"turkey","greece","portugal","spain"} else 0) + \
          (10 if abroad else 0) + (10 if has_budget else 0)
    fit = min(100, fit)

    if market == "north_cyprus" and intent >= 80 and credibility >= 75:
        cls = "HOT"
    elif intent >= 72 and credibility >= 68 and fit >= 50:
        cls = "WARM"
    else:
        cls = "REVIEW"

    return intent, credibility, fit, cls

def serper_search(query):
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY missing")

    try:
        r = S.post(
            SERPER_URL,
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={
                "q": query,
                "gl": "tr",
                "hl": "tr",
                "num": MAX_RESULTS,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        rows = []

        for result in data.get("organic", [])[:MAX_RESULTS]:
            rows.append({
                "source": "Serper",
                "url": result.get("link",""),
                "title": result.get("title",""),
                "text": result.get("snippet",""),
                "published": result.get("date",""),
                "author": "",
            })

        return rows, 0

    except requests.RequestException as exc:
        print(f"SERPER_ERROR: {exc}")
        return [], 1

def google_news_search(query):
    try:
        r = S.get(
            "https://news.google.com/rss/search",
            params={"q":query+" when:1d","hl":"en-US","gl":"US","ceid":"US:en"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        for e in soup.find_all("item")[:MAX_RESULTS]:
            link=e.find("link"); title=e.find("title"); desc=e.find("description"); pub=e.find("pubDate")
            rows.append({
                "source":"Google News",
                "url":link.get_text(strip=True) if link else "",
                "title":title.get_text(" ",strip=True) if title else "",
                "text":desc.get_text(" ",strip=True) if desc else "",
                "published":pub.get_text(strip=True) if pub else "",
                "author":"",
            })
        return rows, 0
    except requests.RequestException as exc:
        print(f"GOOGLE_NEWS_ERROR: {exc}")
        return [], 1

def telegram(message):
    token=os.getenv("TELEGRAM_BOT_TOKEN")
    chat=os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_NOT_CONFIGURED")
        return
    try:
        r=S.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id":chat,"text":message,"disable_web_page_preview":False},
            timeout=10,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"TELEGRAM_ERROR: {exc}")

def format_lead(x):
    emoji = "🔥" if x["classification"]=="HOT" else "🟠"
    return (
        f"{emoji} BAY-S RADAR — {x['classification']}\n\n"
        f"Source: {x['source']}\n"
        f"Market: {x['market']}\n"
        f"City/Region: {x['city_region']}\n"
        f"Budget: {x['budget']}\n"
        f"Timeframe: {x['timeframe']}\n"
        f"Intent: {x['intent_score']}/100\n"
        f"Credibility: {x['credibility_score']}/100\n"
        f"Market Fit: {x['market_fit_score']}/100\n\n"
        f"{x['title']}\n\n"
        f"🔗 {x['url']}"
    )

def process_rows(rows, db, seen, leads, rejected, errors, started):
    for item in rows:
        if not item.get("url"):
            continue
        key=fingerprint(item)
        if key in seen:
            continue
        seen.add(key)

        ok, reason = valid(item)
        if not ok:
            rejected[reason]=rejected.get(reason,0)+1
            continue

        value=text(item)
        market=market_for(value)
        intent,cred,fit,classification=score(item, market)

        if classification not in {"HOT","WARM"}:
            rejected["low_score"]=rejected.get("low_score",0)+1
            continue

        ref=db.collection(COLLECTION).document(key)

        try:
            if ref.get().exists:
                print(f"EXISTING_LEAD: {key}")
                continue

            lead={
                **item,
                "lead_id":key,
                "language":language(value),
                "market":market,
                "city_region":city(value,market),
                "budget":budget(value),
                "timeframe":timeframe(value),
                "intent_score":intent,
                "credibility_score":cred,
                "market_fit_score":fit,
                "classification":classification,
                "route_to":MARKETS.get(
                    market,
                    ("", ROUTES.get(market,"Direct Review"))
                )[1],
                "found_at":started.isoformat(),
            }

            ref.set(lead)
            leads.append(lead)

            print(
                f"NEW_LEAD: {classification} | "
                f"{item.get('source')} | "
                f"{market} | {item['url']}"
            )

        except Exception as exc:
            errors["Firestore"]+=1
            print(f"FIRESTORE_ERROR: {exc}")

def main():
    started=datetime.now(timezone.utc)
    print("BAY-S LEAD RADAR V4.6 STARTED")

    db=db_client()
    seen=set()
    leads=[]
    rejected={}

    errors={
        "Serper":0,
        "Google News":0,
        "Firestore":0,
    }

    counts={
        "Serper":0,
        "Google News":0,
    }

    print(f"SERPER_QUERY_COUNT: {len(SEARCH_QUERIES)}")

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"[SERPER {i}/{len(SEARCH_QUERIES)}] {query}")

        rows, err = serper_search(query)

        counts["Serper"] += len(rows)
        errors["Serper"] += err

        process_rows(
            rows,
            db,
            seen,
            leads,
            rejected,
            errors,
            started,
        )

        time.sleep(0.25)

    print(f"NEWS_QUERY_COUNT: {len(NEWS_QUERIES)}")

    for i, query in enumerate(NEWS_QUERIES, 1):
        print(f"[NEWS {i}/{len(NEWS_QUERIES)}] {query}")

        rows, err = google_news_search(query)

        counts["Google News"] += len(rows)
        errors["Google News"] += err

        process_rows(
            rows,
            db,
            seen,
            leads,
            rejected,
            errors,
            started,
        )

        time.sleep(0.5)

    finished=datetime.now(timezone.utc)

    scan={
        "started_at":started.isoformat(),
        "completed_at":finished.isoformat(),
        "status":"completed",
        "source_results":counts,
        "unique_results":len(seen),
        "new_hot_warm":len(leads),
        "source_errors":errors,
        "rejected":rejected,
        "search_queries":len(SEARCH_QUERIES),
        "news_queries":len(NEWS_QUERIES),
        "mode":"serper_web_search",
    }

    try:
        db.collection(
            SCAN_LOG_COLLECTION
        ).document(
            started.strftime("%Y%m%dT%H%M%SZ")
        ).set(scan)
    except Exception as exc:
        print(f"SCAN_LOG_ERROR: {exc}")

    print(
        json.dumps(
            scan,
            ensure_ascii=False,
            indent=2,
        )
    )

    leads.sort(
        key=lambda x: (
            0 if x["classification"]=="HOT" else 1,
            -x["intent_score"],
            -x["credibility_score"],
            -x["market_fit_score"],
        )
    )

    if leads:
        for lead in leads[:MAX_TELEGRAM_LEADS]:
            telegram(format_lead(lead))
    else:
        telegram(
            "ℹ️ BAY-S RADAR V4.6\n\n"
            "Tarama tamamlandı.\n"
            "Yeni HOT/WARM buyer lead bulunamadı.\n\n"
            f"Serper sonuçları: {counts['Serper']}\n"
            f"Google News sonuçları: {counts['Google News']}\n"
            "Yeni lead: 0"
        )

    print("BAY-S LEAD RADAR V4.6 FINISHED")

if __name__=="__main__":
    main()
