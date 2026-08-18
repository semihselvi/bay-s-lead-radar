import os
import re
import hashlib
import json
import time
import asyncio
import csv
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
 
from urllib.parse import quote_plus

import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account

from config import *


UA = (
    "Mozilla/5.0 (compatible; BAY-S-Web-Radar/2.0; "
    "+https://github.com/semihselvi/bay-s-web-radar)"
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
})

REQUEST_TIMEOUT = 12
REDDIT_DELAY = 1.5
NEWS_DELAY = 0.4
MAX_RETRIES = 2


def get(url, params=None, timeout=REQUEST_TIMEOUT):
    return SESSION.get(
        url,
        params=params,
        timeout=timeout,
        allow_redirects=True,
    )


# ---------------------------------------------------------
# REDDIT
# ---------------------------------------------------------

def reddit_search(query):
    """
    Reddit RSS.
    429 durumunda kısa backoff uygular.
    Reddit kapsamı korunur; sadece istekler kontrollü yapılır.
    """

    url = "https://www.reddit.com/search.rss"

    for attempt in range(MAX_RETRIES + 1):
        try:
            r = get(
                url,
                {
                    "q": query,
                    "sort": "new",
                    "t": "day",
                    "limit": MAX_RESULTS_PER_SOURCE,
                },
            )

            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")

                try:
                    wait = min(int(retry_after), 8) if retry_after else 4
                except Exception:
                    wait = 4

                print(
                    f"REDDIT_429 retry={attempt + 1} "
                    f"wait={wait}s query={query}"
                )

                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    continue

                return []

            r.raise_for_status()

            # XML parser problemi yaşamamak için lxml'e bağlı değiliz.
            soup = BeautifulSoup(r.text, "html.parser")

            out = []

            for entry in soup.find_all("entry")[:MAX_RESULTS_PER_SOURCE]:

                link = entry.find("link")

                title = entry.find("title")
                content = entry.find("content")
                published = entry.find("published")
                author = entry.find("name")

                out.append({
                    "source": "Reddit",
                    "url": link.get("href", "") if link else "",
                    "title": title.get_text(" ", strip=True)
                    if title else "",
                    "text": content.get_text(" ", strip=True)
                    if content else "",
                    "published": published.get_text(strip=True)
                    if published else "",
                    "author": author.get_text(strip=True)
                    if author else "",
                })

            return out

        except requests.exceptions.RequestException as e:
            print(
                f"REDDIT_ERROR attempt={attempt + 1} "
                f"query={query} error={e}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(2 + attempt * 2)
            else:
                return []

        except Exception as e:
            print(
                f"REDDIT_PARSE_ERROR query={query} error={e}"
            )
            return []

        finally:
            time.sleep(REDDIT_DELAY)


# ---------------------------------------------------------
# GOOGLE NEWS
# ---------------------------------------------------------

def google_news(query):
    """
    Google News RSS.
    when:1d ile son 24 saati hedefler.
    """

    url = "https://news.google.com/rss/search"

    try:
        r = get(
            url,
            {
                "q": f"{query} when:1d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
        )

        r.raise_for_status()

        # lxml gerektirmeden XML benzeri RSS'i parse ediyoruz.
        soup = BeautifulSoup(r.text, "html.parser")

        out = []

        for item in soup.find_all("item")[:MAX_RESULTS_PER_SOURCE]:

            link = item.find("link")
            title = item.find("title")
            description = item.find("description")
            pub_date = item.find("pubDate")

            out.append({
                "source": "Google News",
                "url": link.get_text(strip=True)
                if link else "",
                "title": title.get_text(" ", strip=True)
                if title else "",
                "text": description.get_text(" ", strip=True)
                if description else "",
                "published": pub_date.get_text(strip=True)
                if pub_date else "",
                "author": "",
            })

        return out

    except Exception as e:
        print(
            f"GOOGLE_NEWS_ERROR query={query} error={e}"
        )
        return []

    finally:
        time.sleep(NEWS_DELAY)


# ---------------------------------------------------------
# EXA WEB SEARCH
# ---------------------------------------------------------

FORUM_DOMAINS = {
    "expat.com",
    "britishexpats.com",
    "forum.donanimhaber.com",
    "technopat.net",
    "r10.net",
    "forums.moneysavingexpert.com",
    "reddit.com",
}

EXCLUDED_MARKETS = [
    "usa", "united states", "united states of america", "america",
    "canada", "toronto", "vancouver",
    "australia", "sydney", "melbourne", "brisbane", "perth",
    "new zealand", "auckland", "wellington",
]

LISTING_NOISE = [
    "for rent", "for sale", "property listing", "listing type",
    "property id", "get catalogue", "download brochure", "enquire now",
    "contact us", "leave your details", "one of our property consultants",
    "our properties", "our projects", "available units", "developer",
    "real estate agency", "estate agency", "property agency",
    "realtor", "broker", "we sell", "commission", "property management",
]

PERSONAL_BUYER = [
    "i am looking", "i'm looking", "i want to buy", "i want to purchase",
    "i'm looking to buy", "i am looking to buy", "i'm thinking of buying",
    "i am thinking of buying", "i'm planning to buy", "i am planning to buy",
    "we are looking", "we're looking", "we want to buy", "my budget",
    "our budget", "looking for an apartment", "looking for a house",
    "looking for property", "ev alacağım", "ev almak istiyorum",
    "ev almayı düşünüyorum", "bütçem", "yatırım için ev",
    "хочу купить", "ищу квартиру", "мой бюджет",
]

NEGATIVE_BUYER_STATUS = [
    "already bought", "we bought", "i bought", "bought elsewhere",
    "decided against", "decided not to buy", "not buying",
    "no longer looking", "not looking anymore", "renting instead",
    "found a property", "found another property", "purchase completed",
    "already purchased", "we decided not to", "karar verdik",
    "almaktan vazgeç", "satın aldım", "aldık", "artık aramıyorum",
    "artık düşünmüyorum", "купил", "купили", "передумал",
]

def looks_like_listing(item):
    t = (
        item.get("title", "")
        + " "
        + item.get("text", "")
    ).lower()
    hits = sum(p in t for p in LISTING_NOISE)
    return hits >= 2

def looks_like_personal_buyer(item):
    t = (
        item.get("title", "")
        + " "
        + item.get("text", "")
    ).lower()
    return any(p in t for p in PERSONAL_BUYER)

def looks_like_negative_buyer(item):
    t = (
        item.get("title", "")
        + " "
        + item.get("text", "")
    ).lower()
    return any(
        phrase in t
        for phrase in NEGATIVE_BUYER_STATUS
    )

def is_recent_enough(item, days=90):
    published = item.get("published", "")
    if not published:
        # Some forum results do not expose a publish date.
        # Keep them for the next semantic/negative filter rather than guessing.
        return True

    try:
        from datetime import datetime, timezone, timedelta
        value = published.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return dt >= cutoff
    except Exception:
        return True

def is_excluded_market(item):
    t = (
        item.get("title", "")
        + " "
        + item.get("text", "")
    ).lower()
    return any(term in t for term in EXCLUDED_MARKETS)

def exa_search(query, include_domains=None):
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("EXA_API_KEY missing")

    payload = {
        "query": query,
        "type": "auto",
        "numResults": 5,
        "contents": {"text": True},
    }

    if include_domains:
        payload["includeDomains"] = include_domains

    try:
        r = requests.post(
            "https://api.exa.ai/search",
            json=payload,
            headers={
                "x-api-key": api_key.strip(),
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:500]
            print(f"EXA_HTTP_{r.status_code}: {detail}")
            return []

        data = r.json()
        return [
            {
                "source": "Exa",
                "url": x.get("url", ""),
                "title": x.get("title", ""),
                "text": x.get("text", ""),
                "published": x.get("publishedDate", ""),
                "author": "",
            }
            for x in data.get("results", [])[:5]
        ]

    except Exception as e:
        print(f"EXA_ERROR query={query} error={e}")
        return []


# ---------------------------------------------------------
# QUERY BUILDER
# ---------------------------------------------------------

def build_queries():
    # Balanced international buyer radar.
    # Excludes USA, Canada, Australia, New Zealand.
    return [
        # NORTH CYPRUS / CYPRUS
        ("North Cyprus buying property personal buyer budget", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("North Cyprus looking to buy apartment personal budget", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("North Cyprus moving buying home personal experience", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("buying property Northern Cyprus personal budget", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("buying property Cyprus expat personal buyer", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("Cyprus holiday home personal buyer budget", ["britishexpats.com", "expat.com", "reddit.com"]),

        # TURKEY / TURKISH
        ("Türkiye ev alacağım bütçe konut kredisi", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye ev almayı düşünüyorum yatırım kira", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye hangi şehirden ev almalıyım yatırım", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye 1+1 2+1 ev alacağım bütçem", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("buying property in Turkey personal buyer budget", ["expat.com", "reddit.com", "britishexpats.com"]),

        # UK
        ("UK buyer looking to buy property abroad personal budget", ["britishexpats.com", "forums.moneysavingexpert.com", "reddit.com"]),
        ("British buyer looking to buy Cyprus property personal", ["britishexpats.com", "expat.com", "reddit.com"]),
        ("UK holiday home abroad buying personal budget", ["forums.moneysavingexpert.com", "britishexpats.com", "reddit.com"]),

        # GERMANY
        ("German buyer looking to buy property abroad personal budget", ["expat.com", "reddit.com"]),
        ("Germany moving buying property personal budget", ["expat.com", "reddit.com"]),
        ("German expat buying Cyprus Turkey property personal", ["expat.com", "reddit.com"]),

        # NETHERLANDS
        ("Dutch buyer looking to buy property abroad personal budget", ["expat.com", "reddit.com"]),
        ("Netherlands moving buying property personal budget", ["expat.com", "reddit.com"]),
        ("Dutch expat buying Cyprus Turkey property personal", ["expat.com", "reddit.com"]),

        # FRANCE
        ("French buyer looking to buy property abroad personal budget", ["expat.com", "reddit.com"]),
        ("France moving buying property personal budget", ["expat.com", "reddit.com"]),
        ("French expat buying Cyprus Turkey property personal", ["expat.com", "reddit.com"]),

        # RUSSIA / KAZAKHSTAN
        ("Russian buyer looking to buy property abroad personal budget", ["reddit.com", "expat.com"]),
        ("русский хочет купить недвижимость за рубежом бюджет", ["reddit.com", "expat.com"]),
        ("Russian buyer Cyprus Turkey property personal", ["reddit.com", "expat.com"]),
        ("Kazakh buyer looking to buy property abroad personal budget", ["reddit.com", "expat.com"]),
        ("казахстанец хочет купить недвижимость за рубежом бюджет", ["reddit.com", "expat.com"]),
        ("Kazakhstan buyer Cyprus Turkey property personal", ["reddit.com", "expat.com"]),

        # SOUTHERN EUROPE / GOLDEN VISA
        ("Greece property personal buyer budget relocation", ["expat.com", "reddit.com"]),
        ("Portugal property personal buyer budget relocation", ["expat.com", "reddit.com"]),
        ("Spain property personal buyer budget relocation", ["expat.com", "reddit.com"]),
        ("Golden Visa property personal buyer budget Greece Portugal Spain", ["expat.com", "reddit.com"]),
    ]


# ---------------------------------------------------------
# MARKET
# ---------------------------------------------------------

def market_for(text):

    t = text.lower()

    for market, places in MARKETS.items():

        for place in places:

            if place.lower() in t:
                return market

    return "unknown"


# ---------------------------------------------------------
# SCORING
# ---------------------------------------------------------

def score(item, market):

    t = (
        item.get("title", "")
        + " "
        + item.get("text", "")
    ).lower()

    intent_hits = sum(
        p.lower() in t
        for p in INTENT_PHRASES
    )

    exclude_hits = sum(
        p.lower() in t
        for p in EXCLUDE_PHRASES
    )

    budget = bool(
        re.search(
            r'[$€£₺]\s?[\d,.]+'
            r'|\b\d{2,3}\s?[kKmM]\b'
            r'|\b\d{4,}\b',
            t,
        )
    )

    timeframe = any(
        x in t
        for x in [
            "month",
            "months",
            "weeks",
            "year",
            "soon",
            "this year",
            "2026",
            "2027",
            "within",
            "next month",
            "next year",
        ]
    )

    personal = any(
        x in t
        for x in [
            "i ",
            "we ",
            "my ",
            "our ",
            "i'm ",
            "we're ",
            "ben ",
            "biz ",
            "я ",
            "мы ",
        ]
    )

    intent = min(
        100,
        35
        + intent_hits * 7
        + (12 if budget else 0)
        + (10 if timeframe else 0)
        + (8 if personal else 0)
        - exclude_hits * 20,
    )

    credibility = min(
        100,
        55
        + (12 if budget else 0)
        + (10 if timeframe else 0)
        + (10 if len(t) > 450 else 0)
        + (8 if personal else 0)
        - exclude_hits * 25,
    )

    fit = 55 if market != "unknown" else 35

    if budget:
        fit += 12

    if market in (
        "north_cyprus",
        "greece",
        "germany",
        "netherlands",
        "france",
        "switzerland",
    ):
        fit += 8

    fit = max(0, min(100, fit))

    if (
        intent >= 82
        and credibility >= 75
        and fit >= 60
    ):
        classification = "HOT"

    elif (
        intent >= 62
        and credibility >= 65
        and fit >= 45
    ):
        classification = "WARM"

    else:
        classification = "REVIEW"

    return (
        intent,
        credibility,
        fit,
        classification,
    )


# ---------------------------------------------------------
# FINGERPRINT
# ---------------------------------------------------------

def fp(item):

    raw = "|".join([
        item.get("url", ""),
        item.get("title", ""),
        item.get("author", ""),
    ])

    return hashlib.sha256(
        raw.lower().encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------
# FIRESTORE
# ---------------------------------------------------------

def db():

    raw = os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT_JSON"
    )

    if not raw:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON missing"
        )

    creds = (
        service_account
        .Credentials
        .from_service_account_info(
            json.loads(raw)
        )
    )

    return firestore.Client(
        credentials=creds
    )


# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------

def telegram(text):

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    chat = os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat:
        print("TELEGRAM_NOT_CONFIGURED")
        return

    try:

        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )

        r.raise_for_status()

    except Exception as e:

        print(
            f"TELEGRAM_ERROR {e}"
        )



# ---------------------------------------------------------
# TELEGRAM BUYER RADAR
# ---------------------------------------------------------

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "").strip()
TELEGRAM_HOURS = int(os.getenv("RADAR_TELEGRAM_HOURS", "24"))
TELEGRAM_PER_GROUP_LIMIT = int(
    os.getenv("RADAR_TELEGRAM_PER_GROUP_LIMIT", "500")
)
TELEGRAM_SESSION = Path(
    os.getenv(
        "TELEGRAM_SESSION_PATH",
        "telegram_radar_session",
    )
)

TG_BUY = [
    r"\balmak istiyorum\b", r"\bsatın almak istiyorum\b",
    r"\bev arıyorum\b", r"\bdaire arıyorum\b", r"\bvilla arıyorum\b",
    r"\barsa arıyorum\b", r"\byatırım için\b", r"\bbütçem\b",
    r"\balıcıyım\b", r"\blooking to buy\b", r"\bwant to buy\b",
    r"\bplanning to buy\b", r"\bready to buy\b", r"\bcash buyer\b",
    r"\bproperty wanted\b", r"\bhouse wanted\b", r"\bapartment wanted\b",
    r"\bvilla wanted\b", r"\bseeking to buy\b", r"\binterested in buying\b",
    r"\bwtb\b", r"\blooking for (?:an? )?(?:apartment|flat|house|villa|property|land)\b",
    r"\bхочу купить\b", r"\bхотим купить\b", r"\bкуплю\b",
    r"\bищу купить\b", r"\bищу квартиру\b", r"\bищу апартамент",
    r"\bищу виллу\b", r"\bищу дом\b", r"\bищу недвижимость\b",
    r"\bготов купить\b", r"\bготовы купить\b", r"\bпланирую купить\b",
    r"\bдля инвестиц", r"\bбюджет\b", r"\bсрочно нужна квартира\b",
    r"\bнужна квартира\b", r"\bкуплю квартиру\b", r"\bкуплю дом\b",
    r"\bкуплю недвижимость\b", r"\bищу жилье\b", r"\bищу жильё\b",
    r"\bкакую квартиру купить\b", r"\bгде купить квартиру\b",
    r"\bacil(?:en)? .*?daire\b", r"\bdaire lazım\b", r"\bkonut arıyorum\b",
]
TG_WEAK = [
    r"\bönerir misiniz\b", r"\bhangi bölge\b", r"\bmortgage\b",
    r"\bwhere should i buy\b", r"\bwhich area\b", r"\binvestment property\b",
    r"\bгде купить\b", r"\bкакой район\b", r"\bипотек",
]
TG_SELL = [
    r"\bsatılık\b", r"\bsatışta\b", r"\bportföy\b", r"\bkomisyon\b",
    r"\bkampanya\b", r"\bfor sale\b", r"\bavailable now\b",
    r"\bcontact us\b", r"\bagent\b", r"\bagency\b", r"\bcommission\b",
    r"\bdeveloper\b", r"\bпродам\b", r"\bпродается\b", r"\bпродаётся\b",
    r"\bагент\b", r"\bагентство\b", r"\bкомисси", r"\bзастройщик\b",
    r"\bсдам\b", r"\bсдается\b", r"\bсдаётся\b", r"\bаренда\b",
    r"\bобъявление\b", r"\bреклама\b", r"\bпишите в лс\b",
    r"\bwhatsapp\b", r"\bnew project\b",
]
TG_RENT = [
    r"\bkiralık\b", r"\bfor rent\b", r"\blooking to rent\b",
    r"\brental\b", r"\bсниму\b", r"\bаренд", r"\bснять квартиру\b",
    r"\bснять виллу\b",
]
TG_BUDGET_RE = re.compile(
    r"(?:£|€|\$|₺|₽)\s?\d[\d\s.,]*|"
    r"\b\d[\d\s.,]*\s?(?:gbp|eur|usd|try|tl|руб|млн|million|k)\b",
    re.I,
)

TG_MARKETS = {
    "north_cyprus": [
        "north cyprus", "northern cyprus", "kuzey kıbrıs",
        "северный кипр", "iskele", "girne", "kyrenia",
        "famagusta", "gazimağusa", "long beach", "esentepe",
        "caesar", "cesar",
    ],
    "turkey": [
        "turkey", "türkiye", "antalya", "alanya", "istanbul",
        "izmir", "ankara", "muratpaşa", "lara", "konyaaltı",
        "bodrum", "fethiye", "mersin",
    ],
    "montenegro": ["montenegro", "черногор", "karadağ", "budva", "kotor", "tivat"],
    "spain": ["spain", "испания", "ispanya", "alicante", "valencia", "marbella", "malaga"],
    "portugal": ["portugal", "португал", "portekiz", "lisbon", "lisboa", "porto", "algarve"],
    "uae": ["dubai", "дубай", "uae", "abu dhabi", "sharjah"],
    "uk": ["united kingdom", "england", "london", "manchester", "birmingham", "британи"],
    "germany": ["germany", "deutschland", "германи", "almanya", "berlin", "munich", "frankfurt", "hamburg"],
    "greece": ["greece", "yunanistan", "греци", "athens", "thessaloniki"],
    "italy": ["italy", "italia", "italya", "итал", "milan", "rome"],
    "france": ["france", "fransa", "франц", "paris", "nice", "cannes"],
    "kazakhstan": ["kazakhstan", "казахстан", "almaty", "алматы", "astana", "астана"],
    "russia": ["russia", "россия", "русские", "москва", "санкт-петербург"],
}

TG_HIGH_GROUPS = [
    "СЕВЕРНЫЙ КИПР | БАРАХОЛКА",
    "Русские на Северном Кипре",
    "Цезарь резорт",
    "Недвижимость Северный Кипр",
    "Iskele | Long Beach",
    "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
    "Северный Кипр Недвижимость",
    "Гирне | Кирения",
    "Северный Кипр: объявления, работа, недвижимость",
    "Северный Кипр. ЧАТ. БАЗА Недвижимости",
    "Недвижимость Турция и Северный Кипр",
    "Русские в Анталье",
    "Все русские в Турции",
    "Недвижимость Турция",
    "CourtYard Long Beach",
]

TG_MEDIUM_GROUPS = [
    "СЕВЕРНЫЙ КИПР (чат)",
    "Искеле Гирне Фамагуста Лефкоша Северный Кипр чат",
    "АНТАЛИЯ ЧАТ ТУРЦИЯ",
    "АНТАЛИЯ ЧАТ",
    "СТАМБУЛ ЧАТ",
    "Кипр | Чат | Объявления | Барахолка",
    "Кипр Объявления/Барахолка/Недвижимость №1",
    "Северный Кипр | ФОРУМ",
]

TG_NEGATIVE = [
    "already bought", "we bought", "i bought", "bought elsewhere",
    "decided against", "decided not to buy", "not buying",
    "no longer looking", "not looking anymore", "renting instead",
    "found a property", "found another property", "purchase completed",
    "already purchased", "almaktan vazgeç", "satın aldım", "aldık",
    "artık aramıyorum", "купил", "купили", "передумал",
]

def tg_norm(s):
    return (s or "").casefold()

def tg_matches(text, patterns):
    t = tg_norm(text)
    return [re.search(p, t, re.I).group(0) for p in patterns if re.search(p, t, re.I)]

def tg_market(text, group):
    blob = tg_norm((group or "") + " " + (text or ""))
    scores = {
        k: sum(term in blob for term in v)
        for k, v in TG_MARKETS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "unknown"

def tg_priority(group):
    t = tg_norm(group)
    if any(t == tg_norm(x) for x in TG_HIGH_GROUPS):
        return "HIGH"
    if any(t == tg_norm(x) for x in TG_MEDIUM_GROUPS):
        return "MEDIUM"
    return "NORMAL"

def tg_score(text, group):
    buy = tg_matches(text, TG_BUY)
    weak = tg_matches(text, TG_WEAK)
    sell = tg_matches(text, TG_SELL)
    rent = tg_matches(text, TG_RENT)
    budget = bool(TG_BUDGET_RE.search(text or ""))
    negative = any(p in tg_norm(text) for p in TG_NEGATIVE)
    priority = tg_priority(group)

    score = (
        min(70, 25 * len(buy))
        + min(16, 6 * len(weak))
        + (12 if budget else 0)
        + (12 if priority == "HIGH" else 6 if priority == "MEDIUM" else 0)
        - min(80, 30 * len(sell))
        - min(80, 40 * len(rent))
        - (50 if negative else 0)
    )
    score = max(0, min(100, score))

    if rent and not buy:
        label = "REJECT_RENT"
    elif sell and not buy:
        label = "REJECT_SELLER"
    elif negative:
        label = "REJECT_STATUS"
    elif score >= 70:
        label = "HOT"
    elif score >= 42:
        label = "WARM"
    elif score >= 20:
        label = "REVIEW"
    else:
        label = "LOW"

    return (
        score, label, buy, weak, sell, rent, budget,
        negative, tg_market(text, group), priority,
    )

def tg_sender(msg):
    sender = getattr(msg, "sender", None)
    if not sender:
        return ""
    username = getattr(sender, "username", None)
    if username:
        return "@" + username
    return (
        (getattr(sender, "first_name", "") or "")
        + " "
        + (getattr(sender, "last_name", "") or "")
    ).strip()

def tg_link(entity, mid):
    username = getattr(entity, "username", None)
    return (
        f"https://t.me/{username}/{mid}"
        if username
        else ""
    )

async def telegram_buyer_scan(db_client, started):
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("TELEGRAM_RADAR: API_ID/API_HASH yok — atlandı.")
        return {
            "status": "skipped",
            "groups": 0,
            "messages": 0,
            "hot_warm": 0,
            "errors": 0,
        }

    session = TELEGRAM_SESSION

    # On GitHub Actions, use a pre-authenticated .session file.
    # We never print credentials.
    if not session.exists():
        print(
            "TELEGRAM_RADAR: session dosyası yok — "
            "TELEGRAM_SESSION_PATH ile oturum dosyası sağlamalısın. Atlandı."
        )
        return {
            "status": "skipped_no_session",
            "groups": 0,
            "messages": 0,
            "hot_warm": 0,
            "errors": 0,
        }

    client = TelegramClient(
        str(session),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print(
                "TELEGRAM_RADAR: session yetkili değil — atlandı."
            )
            return {
                "status": "skipped_unauthorized",
                "groups": 0,
                "messages": 0,
                "hot_warm": 0,
                "errors": 0,
            }

        me = await client.get_me()
        print(
            "TELEGRAM_RADAR: giriş ok — "
            f"{getattr(me, 'username', None) or getattr(me, 'first_name', '')}"
        )

        dialogs = []
        async for dialog in client.iter_dialogs():
            if getattr(dialog, "is_group", False):
                dialogs.append(dialog)

        dialogs.sort(
            key=lambda d: (
                {"HIGH": 0, "MEDIUM": 1, "NORMAL": 2}.get(
                    tg_priority(
                        d.name
                        or getattr(d.entity, "username", None)
                        or ""
                    ),
                    2,
                ),
                tg_norm(d.name or ""),
            )
        )

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=TELEGRAM_HOURS)
        )

        results = []
        seen_msg_ids = set()
        errors = 0
        total_messages = 0

        print(
            f"TELEGRAM_RADAR: {len(dialogs)} grup taranacak | "
            f"son {TELEGRAM_HOURS} saat"
        )

        for i, dialog in enumerate(
            dialogs,
            start=1,
        ):
            entity = dialog.entity
            group = (
                dialog.name
                or getattr(entity, "username", None)
                or str(dialog.id)
            )
            priority = tg_priority(group)

            print(
                f"[TELEGRAM {i}/{len(dialogs)}] "
                f"{priority} | {group}"
            )

            try:
                async for msg in client.iter_messages(
                    entity,
                    limit=TELEGRAM_PER_GROUP_LIMIT,
                ):
                    text = getattr(msg, "message", None)
                    if not text:
                        continue

                    dt = getattr(msg, "date", None)
                    if not dt:
                        continue

                    if dt.tzinfo is None:
                        dt = dt.replace(
                            tzinfo=timezone.utc
                        )

                    if dt < cutoff:
                        break

                    total_messages += 1

                    (
                        score,
                        label,
                        buy,
                        weak,
                        sell,
                        rent,
                        budget,
                        negative,
                        market,
                        priority,
                    ) = tg_score(text, group)

                    if label not in {"HOT", "WARM"}:
                        continue

                    stable_id = (
                        f"telegram|{dialog.id}|{msg.id}"
                    )
                    if stable_id in seen_msg_ids:
                        continue
                    seen_msg_ids.add(stable_id)

                    ref = (
                        db_client
                        .collection(COLLECTION)
                        .document(
                            hashlib.sha256(
                                stable_id.encode(
                                    "utf-8"
                                )
                            ).hexdigest()
                        )
                    )

                    if ref.get().exists:
                        continue

                    lead = {
                        "lead_id": ref.id,
                        "source": "Telegram",
                        "source_type": "joined_group",
                        "group": group,
                        "group_priority": priority,
                        "group_username": (
                            getattr(
                                entity,
                                "username",
                                None,
                            )
                            or ""
                        ),
                        "message_id": msg.id,
                        "message_time": dt.isoformat(
                            timespec="seconds"
                        ),
                        "author": tg_sender(msg),
                        "message": text.strip(),
                        "url": tg_link(entity, msg.id),
                        "market": market,
                        "budget_detected": bool(budget),
                        "buyer_matches": buy,
                        "weak_matches": weak,
                        "seller_matches": sell,
                        "rent_matches": rent,
                        "telegram_score": score,
                        "classification": label,
                        "negative_status": negative,
                        "found_at": started.isoformat(),
                    }

                    ref.set(lead)
                    results.append(lead)

            except FloodWaitError as exc:
                errors += 1
                print(
                    f"TELEGRAM_FLOOD_WAIT "
                    f"{exc.seconds}s"
                )
            except Exception as exc:
                errors += 1
                print(
                    f"TELEGRAM_GROUP_ERROR "
                    f"{group}: "
                    f"{type(exc).__name__}: {exc}"
                )

            await asyncio.sleep(0.35)

        return {
            "status": "completed",
            "groups": len(dialogs),
            "messages": total_messages,
            "hot_warm": len(results),
            "errors": errors,
        "telegram_groups": telegram_scan.get("groups", 0),
        "telegram_messages_scanned": telegram_scan.get("messages", 0),
        "telegram_new_hot_warm": telegram_scan.get("hot_warm", 0),
        "telegram_status": telegram_scan.get("status", ""),
            "new_leads": results,
        }

    except Exception as exc:
        print(
            f"TELEGRAM_RADAR_ERROR "
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "status": "error",
            "groups": 0,
            "messages": 0,
            "hot_warm": 0,
            "errors": 1,
            "new_leads": [],
        }
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    started = datetime.now(
        timezone.utc
    )

    queries = build_queries()

    print(
        f"BAY-S RADAR V4.5.4.1-UNIFIED STARTED | "
        f"queries={len(queries)}"
    )

    client = db()

    seen = set()
    candidates = []

    errors = 0

    source_counts = {
        "Reddit": 0,
        "Google News": 0,
    }

    source_errors = {
        "Reddit": 0,
        "Google News": 0,
    }

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    source_counts = {
        "Exa": 0,
        "Google News": 0,
    }

    source_errors = {
        "Exa": 0,
        "Google News": 0,
    }

    for index, spec in enumerate(
        queries,
        start=1,
    ):
        q, domains = spec

        print(
            f"[EXA {index}/{len(queries)}] "
            f"{q}"
        )

        try:
            results = exa_search(q, domains)
            source_counts["Exa"] += len(results)

            for item in results:
                if not item.get("url"):
                    continue

                key = fp(item)
                if key in seen:
                    continue
                seen.add(key)

                market = market_for(
                    item.get("title", "")
                    + " "
                    + item.get("text", "")
                )

                if looks_like_listing(item):
                    continue

                if not looks_like_personal_buyer(item):
                    continue

                if is_excluded_market(item):
                    continue

                if looks_like_negative_buyer(item):
                    continue

                if not is_recent_enough(item, 90):
                    continue

                intent, credibility, fit, classification = score(
                    item,
                    market,
                )

                if classification not in ("HOT", "WARM"):
                    continue

                ref = (
                    client
                    .collection(COLLECTION)
                    .document(key)
                )

                if ref.get().exists:
                    continue

                lead = {
                    **item,
                    "lead_id": key,
                    "market": market,
                    "route_to": ROUTES.get(
                        market,
                        "Direct Review",
                    ),
                    "intent_score": intent,
                    "credibility_score": credibility,
                    "market_fit_score": fit,
                    "classification": classification,
                    "found_at": started.isoformat(),
                }

                ref.set(lead)
                candidates.append(lead)

        except Exception as e:
            errors += 1
            source_errors["Exa"] += 1
            print(f"EXA_LOOP_ERROR {e}")

        time.sleep(0.25)

        # Google News remains as an auxiliary source.
        if index % 10 == 0:
            print(f"[GOOGLE NEWS BRIDGE] after_exa={index}")

            for bridge_spec in queries[max(0, index - 4):index]:
                bridge_query = bridge_spec[0]
                try:
                    results = google_news(bridge_query)
                    source_counts["Google News"] += len(results)

                    for item in results:
                        if not item.get("url"):
                            continue

                        key = fp(item)
                        if key in seen:
                            continue
                        seen.add(key)

                        market = market_for(
                            item.get("title", "")
                            + " "
                            + item.get("text", "")
                        )

                        intent, credibility, fit, classification = score(
                            item,
                            market,
                        )

                        if classification not in ("HOT", "WARM"):
                            continue

                        ref = (
                            client
                            .collection(COLLECTION)
                            .document(key)
                        )

                        if ref.get().exists:
                            continue

                        lead = {
                            **item,
                            "lead_id": key,
                            "market": market,
                            "route_to": ROUTES.get(
                                market,
                                "Direct Review",
                            ),
                            "intent_score": intent,
                            "credibility_score": credibility,
                            "market_fit_score": fit,
                            "classification": classification,
                            "found_at": started.isoformat(),
                        }

                        ref.set(lead)
                        candidates.append(lead)

                except Exception as e:
                    errors += 1
                    source_errors["Google News"] += 1

    # -----------------------------------------------------
    # TELEGRAM BUYER RADAR
    # -----------------------------------------------------

    telegram_scan = {
        "status": "not_started",
        "groups": 0,
        "messages": 0,
        "hot_warm": 0,
        "errors": 0,
        "new_leads": [],
    }

    telegram_new = []

    try:
        telegram_scan = asyncio.run(
            telegram_buyer_scan(
                client,
                started,
            )
        )

        telegram_new = telegram_scan.get(
            "new_leads",
            [],
        )

    except Exception as exc:
        errors += 1
        print(
            f"TELEGRAM_RADAR_ERROR "
            f"{type(exc).__name__}: {exc}"
        )

    # -----------------------------------------------------
    # SCAN LOG
    # -----------------------------------------------------

    completed = datetime.now(
        timezone.utc
    )

    scan = {
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "status": "completed",
        "queries": len(queries),
        "exa_results_per_query": 5,
        "quality_gate": "balanced_markets_personal_buyer_excluded_markets_no_listing_negative_status_90d",
        "unique_results": len(seen),
        "new_hot_warm": len(candidates),
        "source_counts": source_counts,
        "source_errors": source_errors,
        "errors": errors,
    }

    scan_id = started.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    (
        client
        .collection(SCAN_LOG_COLLECTION)
        .document(scan_id)
        .set(scan)
    )

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    if candidates:

        for x in candidates[:10]:

            emoji = (
                "🔥"
                if x["classification"] == "HOT"
                else "🟡"
            )

            msg = (
                f"{emoji} BAY-S RADAR — "
                f"{x['classification']}\n\n"
                f"{x.get('source', '')}\n"
                f"{x.get('market', '')} | "
                f"{x.get('route_to', '')}\n\n"
                f"{x.get('title', '')}\n\n"
                f"Intent: "
                f"{x['intent_score']}/100\n"
                f"Credibility: "
                f"{x['credibility_score']}/100\n"
                f"Market Fit: "
                f"{x['market_fit_score']}/100\n\n"
                f"🔗 {x.get('url', '')}"
            )

            telegram(msg)

    else:

        telegram(
            "ℹ️ BAY-S RADAR\n\n"
            "Tarama tamamlandı.\n"
            "Son taramadan beri yeni "
            "HOT/WARM buyer lead bulunamadı.\n\n"
            f"Tarama: {len(queries)} sorgu\n"
            f"Exa sonuçları: "
            f"{source_counts['Exa']}\n"
            f"Google News sonuçları: "
            f"{source_counts['Google News']}\n"
            f"Hata: {errors}"
        )

    print(
        json.dumps(
            {
                "scan": scan,
                "new_leads": candidates,
            "telegram_new_leads": telegram_new,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
