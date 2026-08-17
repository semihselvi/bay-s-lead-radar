import os
import re
import json
import time
import hashlib
import warnings
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from google.cloud import firestore
from google.oauth2 import service_account

from config import (
    COLLECTION,
    SCAN_LOG_COLLECTION,
    MAX_RESULTS_PER_SOURCE,
    MARKETS,
    INTENT_PHRASES,
    EXCLUDE_PHRASES,
    ROUTES,
)

warnings.filterwarnings(
    "ignore",
    category=XMLParsedAsHTMLWarning,
)


# =========================================================
# SETTINGS
# =========================================================

USER_AGENT = (
    "BAY-S-Lead-Radar/3.0 "
    "(buyer research; +https://github.com/semihselvi)"
)

REDDIT_SEARCH_URL = "https://www.reddit.com/search.rss"

REQUEST_TIMEOUT = 15

# Reddit'i zorlamıyoruz.
REDDIT_DELAY = 8

# 429 geldiğinde uzun retry döngüsüne girmiyoruz.
MAX_RETRIES = 1

MAX_TELEGRAM_LEADS = 10

session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": (
        "application/atom+xml,"
        "application/rss+xml,"
        "application/xml,"
        "text/xml,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


# =========================================================
# REAL ESTATE SIGNALS
# =========================================================

PROPERTY_TERMS = [
    "property",
    "real estate",
    "home",
    "house",
    "apartment",
    "condo",
    "flat",
    "villa",
    "townhouse",
    "residence",
    "residential",
    "land",
    "rental property",
    "investment property",
    "first home",
    "first house",
    "bedroom",
    "mortgage",
    "down payment",
    "deposit",
    "closing cost",
    "rental income",
    "rental yield",
    "golden visa",
    "residency by investment",

    # Turkish
    "ev",
    "konut",
    "daire",
    "villa",
    "gayrimenkul",
    "mülk",
    "arsa",
    "kira",
    "yatırım",

    # Russian
    "недвижимость",
    "квартира",
    "дом",
    "вилла",
    "ипотека",
    "инвестиции",
    "аренда",
    "золотая виза",
]


BUYER_TERMS = [
    "looking to buy",
    "looking for",
    "want to buy",
    "wanting to buy",
    "planning to buy",
    "ready to buy",
    "buying",
    "buy property",
    "buy a house",
    "buy an apartment",
    "buy apartment",
    "buy a home",
    "purchase",
    "first time buyer",
    "first-time buyer",
    "first home buyer",
    "cash buyer",
    "budget",
    "how much can i afford",
    "should i buy",
    "thinking of buying",
    "moving and buying",
    "relocating and buying",
    "relocation",

    # Turkish
    "ev almak",
    "ev arıyorum",
    "ev almak istiyorum",
    "satın almak",
    "gayrimenkul almak",
    "mülk almak",
    "yatırım yapmak",
    "yatırım için",

    # Russian
    "хочу купить",
    "ищу квартиру",
    "купить квартиру",
    "купить дом",
    "купить недвижимость",
    "нужна квартира",
    "планирую купить",
    "переезд",
]


HARD_EXCLUDES = [
    "real estate agent",
    "estate agent",
    "realtor",
    "broker",
    "brokerage",
    "property developer",
    "property developer",
    "developer selling",
    "property listing",
    "listing page",
    "for sale by owner",
    "our properties",
    "our project",
    "contact our agent",
    "contact us",
    "whatsapp us",
    "call us",
    "commission",
    "lead generation",
    "marketing agency",
    "property management service",
    "we sell",
    "available units",
    "new project",
    "open house event",

    "агентство недвижимости",
    "риэлтор",
    "застройщик",
    "продам квартиру",
    "продаю квартиру",
]


# =========================================================
# FIREBASE
# =========================================================

def firebase_client():
    raw = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON"
    )

    if not raw:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON missing"
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON"
        ) from exc

    credentials = (
        service_account
        .Credentials
        .from_service_account_info(info)
    )

    return firestore.Client(
        credentials=credentials
    )


# =========================================================
# QUERY BUILDER
# =========================================================

def build_queries():

    # Daha az HTTP isteği,
    # daha geniş buyer kapsamı.
    #
    # Reddit'i azaltmıyoruz;
    # tek istekte daha geniş alan tarıyoruz.

    queries = [
        # General English buyer radar
        '"looking to buy" (property OR house OR apartment)',
        '"want to buy" (property OR house OR apartment)',
        '"planning to buy" (property OR house OR apartment)',
        '"first time buyer" (house OR home OR apartment)',
        '"cash buyer" (property OR house)',
        '"property investment" budget',
        '"investment property" budget',
        '"rental income" property',
        '"rental yield" property',
        '"moving" "buying a home"',
        '"relocating" "buying property"',
        '"holiday home" property',

        # Golden Visa / Europe
        '"Golden Visa" property',
        '"EU Golden Visa" property',
        '"residency by investment" property',
        '"Golden Visa" Greece',
        '"Golden Visa" Portugal',
        '"Golden Visa" Spain',

        # North Cyprus / Cyprus
        '"North Cyprus" property buyer',
        '"Northern Cyprus" property buyer',
        '"Kuzey Kıbrıs" ev',
        '"Iskele" property buyer',
        '"Long Beach" Cyprus property',

        # Turkey
        '"Turkey" property buyer',
        '"Turkey" buying property',
        '"Antalya" buying property',
        '"Alanya" buying property',
        '"Istanbul" buying property',
        '"Bodrum" buying property',

        # Partner markets
        '"Germany" property buyer',
        '"Netherlands" property buyer',
        '"Belgium" property buyer',
        '"France" property buyer',
        '"Lithuania" property buyer',
        '"Switzerland" property buyer',

        # Russia / Kazakhstan
        '"Russia" "buy property abroad"',
        '"Kazakhstan" "buy property abroad"',
        '"хочу купить" недвижимость',
        '"ищу квартиру" недвижимость',
        '"недвижимость за рубежом"',

        # UK / Montenegro / UAE
        '"UK" property buyer',
        '"United Kingdom" buying property',
        '"Montenegro" property buyer',
        '"Dubai" property buyer',
    ]

    # Config'deki marketleri de coverage olarak ekle.
    # Her marketten maksimum bir güçlü genel query.
    market_queries = set()

    for market, places in MARKETS.items():

        if not places:
            continue

        # İlk 2-3 önemli terimi kullan.
        selected = places[:3]

        joined = " OR ".join(
            f'"{x}"'
            for x in selected
        )

        market_queries.add(
            f"({joined}) "
            f'("looking to buy" OR "want to buy" OR '
            f'"property investment")'
        )

    queries.extend(
        sorted(market_queries)
    )

    # Duplicate temizliği.
    unique = []
    seen = set()

    for query in queries:

        query = query.strip()

        if not query:
            continue

        normalized = query.lower()

        if normalized in seen:
            continue

        seen.add(normalized)
        unique.append(query)

    return unique


# =========================================================
# REDDIT
# =========================================================

def reddit_search(query):

    for attempt in range(
        MAX_RETRIES + 1
    ):

        try:

            response = session.get(
                REDDIT_SEARCH_URL,
                params={
                    "q": query,
                    "sort": "new",
                    "t": "day",
                    "limit": MAX_RESULTS_PER_SOURCE,
                },
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:

                print(
                    f"REDDIT_429 "
                    f"query={query}"
                )

                # Retry bekleyerek 10 dakikayı öldürme.
                return []

            response.raise_for_status()

            return parse_reddit(
                response.text
            )

        except requests.RequestException as exc:

            print(
                f"REDDIT_ERROR "
                f"query={query} "
                f"error={exc}"
            )

            return []

        finally:
            time.sleep(
                REDDIT_DELAY
            )

    return []


def parse_reddit(xml_text):

    soup = BeautifulSoup(
        xml_text,
        "html.parser",
    )

    results = []

    for entry in soup.find_all(
        "entry"
    )[:MAX_RESULTS_PER_SOURCE]:

        link = entry.find(
            "link"
        )

        title = entry.find(
            "title"
        )

        content = entry.find(
            "content"
        )

        published = entry.find(
            "published"
        )

        author = entry.find(
            "name"
        )

        results.append({
            "source": "Reddit",

            "url": (
                link.get("href", "").strip()
                if link
                else ""
            ),

            "title": (
                title.get_text(
                    " ",
                    strip=True,
                )
                if title
                else ""
            ),

            "text": (
                content.get_text(
                    " ",
                    strip=True,
                )
                if content
                else ""
            ),

            "published": (
                published.get_text(
                    strip=True,
                )
                if published
                else ""
            ),

            "author": (
                author.get_text(
                    strip=True,
                )
                if author
                else ""
            ),
        })

    return results


# =========================================================
# TEXT / MARKET
# =========================================================

def combined_text(item):

    return (
        f"{item.get('title', '')} "
        f"{item.get('text', '')}"
    )


def detect_market(text):

    value = text.lower()

    for market, places in MARKETS.items():

        for place in places:

            if place.lower() in value:
                return market

    return "unknown"


def detect_city_region(
    text,
    market,
):

    if market not in MARKETS:
        return "Not stated"

    value = text.lower()

    country_names = {
        "turkey",
        "türkiye",
        "greece",
        "germany",
        "netherlands",
        "belgium",
        "france",
        "lithuania",
        "switzerland",
        "russia",
        "kazakhstan",
        "montenegro",
        "united kingdom",
        "uk",
    }

    for place in MARKETS[market]:

        if (
            place.lower() in value
            and place.lower()
            not in country_names
        ):
            return place

    return "Not stated"


def detect_language(text):

    value = text.lower()

    if re.search(
        r"[а-яё]",
        value,
    ):
        return "Russian"

    if any(
        x in value
        for x in [
            "ev almak",
            "ev arıyorum",
            "gayrimenkul",
            "kıbrıs",
            "satın almak",
        ]
    ):
        return "Turkish"

    return "English"


def extract_budget(text):

    patterns = [

        r"[$€£₺]\s?[\d,.]+"
        r"(?:\s?[kKmM])?",

        r"\b(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB)"
        r"\s?[\d,.]+"
        r"(?:\s?[kKmM])?",

        r"\b\d{2,3}\s?[kKmM]\b",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if match:
            return match.group(0)

    return "Not stated"


def extract_timeframe(text):

    patterns = [

        r"\b(?:within|in|next)\s+"
        r"\d+\s+"
        r"(?:days?|weeks?|months?|years?)\b",

        r"\bthis year\b",
        r"\bnext year\b",
        r"\bsoon\b",
        r"\bimmediately\b",
        r"\bas soon as possible\b",
        r"\b2026\b",
        r"\b2027\b",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if match:
            return match.group(0)

    return "Not stated"


# =========================================================
# FILTERS
# =========================================================

def has_property_signal(text):

    value = text.lower()

    return any(
        term.lower() in value
        for term in PROPERTY_TERMS
    )


def has_buyer_signal(text):

    value = text.lower()

    return any(
        term.lower() in value
        for term in BUYER_TERMS
    )


def has_hard_exclude(text):

    value = text.lower()

    return any(
        term.lower() in value
        for term in HARD_EXCLUDES
    )


def valid_buyer_signal(item):

    text = combined_text(
        item
    )

    # Gayrimenkul kelimesi şart.
    if not has_property_signal(
        text
    ):
        return False

    # Buyer niyeti şart.
    if not has_buyer_signal(
        text
    ):
        return False

    # Bariz satış/agent içeriklerini çıkar.
    if has_hard_exclude(
        text
    ):
        return False

    # Çok kısa içerikler genelde gerçek buyer lead değildir.
    if len(text.strip()) < 80:
        return False

    return True


# =========================================================
# SCORING
# =========================================================

def score(item, market):

    text = combined_text(
        item
    ).lower()

    intent_hits = sum(
        phrase.lower() in text
        for phrase in INTENT_PHRASES
    )

    exclude_hits = sum(
        phrase.lower() in text
        for phrase in EXCLUDE_PHRASES
    )

    budget = (
        extract_budget(text)
        != "Not stated"
    )

    timeframe = (
        extract_timeframe(text)
        != "Not stated"
    )

    personal = any(
        x in text
        for x in [
            " i ",
            " i'm ",
            " we ",
            " my ",
            " our ",
            "ben ",
            "biz ",
            "я ",
            "мы ",
        ]
    )

    detailed = len(text) >= 400

    intent = min(
        100,
        45
        + intent_hits * 7
        + (12 if budget else 0)
        + (10 if timeframe else 0)
        + (8 if personal else 0)
        - exclude_hits * 15,
    )

    credibility = min(
        100,
        55
        + (15 if budget else 0)
        + (10 if timeframe else 0)
        + (10 if personal else 0)
        + (10 if detailed else 0)
        - exclude_hits * 20,
    )

    fit = (
        65
        if market != "unknown"
        else 35
    )

    if budget:
        fit += 12

    if market in {
        "north_cyprus",
        "turkey",
        "greece",
        "germany",
        "netherlands",
        "belgium",
        "france",
        "lithuania",
        "switzerland",
    }:
        fit += 8

    fit = max(
        0,
        min(
            100,
            fit,
        ),
    )

    if (
        intent >= 82
        and credibility >= 75
    ):
        classification = "HOT"

    elif (
        intent >= 65
        and credibility >= 65
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


# =========================================================
# FINGERPRINT
# =========================================================

def fingerprint(item):

    raw = "|".join([
        item.get(
            "url",
            "",
        ),

        item.get(
            "title",
            "",
        ),

        item.get(
            "author",
            "",
        ),
    ])

    return hashlib.sha256(
        raw.lower().encode(
            "utf-8"
        )
    ).hexdigest()


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(text):

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:

        print(
            "TELEGRAM_NOT_CONFIGURED"
        )

        return

    try:

        response = requests.post(
            (
                "https://api.telegram.org/"
                f"bot{token}/sendMessage"
            ),

            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            },

            timeout=10,
        )

        response.raise_for_status()

    except requests.RequestException as exc:

        print(
            f"TELEGRAM_ERROR: {exc}"
        )


def reply_suggestion(
    market
):

    suggestions = {

        "north_cyprus":
            "Before looking at specific projects, "
            "I’d compare location, total acquisition "
            "cost, ownership structure and realistic "
            "rental potential.",

        "turkey":
            "I’d compare total purchase cost, "
            "location, financing and rental demand "
            "before choosing a property.",

        "greece":
            "For Greece, I’d compare purchase costs, "
            "taxes and Golden Visa requirements "
            "before selecting a property.",

        "germany":
            "I’d compare purchase price, financing, "
            "taxes and ongoing ownership costs first.",

        "netherlands":
            "I’d separate purchase budget from closing "
            "and ongoing ownership costs before comparing "
            "neighborhoods.",

        "france":
            "I’d compare the property budget, "
            "acquisition costs and the actual "
            "living or investment objective first.",
    }

    return suggestions.get(
        market,
        "Before choosing a property, I’d compare "
        "the total acquisition cost, location, "
        "legal considerations and the investment "
        "or living goal.",
    )


def format_lead(
    lead
):

    emoji = (
        "🔥"
        if lead[
            "classification"
        ] == "HOT"

        else "🟠"
    )

    return (
        f"{emoji} BAY-S RADAR — "
        f"{lead['classification']}\n\n"

        f"Source: "
        f"{lead['source']}\n"

        f"Author: "
        f"{lead.get('author') or 'Not stated'}\n"

        f"Language: "
        f"{lead['language']}\n"

        f"Market: "
        f"{lead['market']}\n"

        f"City/Region: "
        f"{lead['city_region']}\n\n"

        f"What they want:\n"
        f"{lead['title']}\n\n"

        f"Budget: "
        f"{lead['budget']}\n"

        f"Timeframe: "
        f"{lead['timeframe']}\n\n"

        f"Intent: "
        f"{lead['intent_score']}/100\n"

        f"Credibility: "
        f"{lead['credibility_score']}/100\n"

        f"Market Fit: "
        f"{lead['market_fit_score']}/100\n\n"

        f"Route To: "
        f"{lead['route_to']}\n\n"

        f"Reply suggestion:\n"
        f"{lead['reply_suggestion']}\n\n"

        f"🔗 "
        f"{lead['url']}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    started = datetime.now(
        timezone.utc
    )

    print(
        "BAY-S LEAD RADAR V3 STARTED"
    )

    queries = build_queries()

    print(
        f"QUERY_COUNT: "
        f"{len(queries)}"
    )

    db = firebase_client()

    seen = set()

    new_leads = []

    source_results = 0

    source_errors = 0

    reddit_429_count = 0

    for index, query in enumerate(
        queries,
        start=1,
    ):

        print(
            f"[{index}/{len(queries)}] "
            f"{query}"
        )

        results = reddit_search(
            query
        )

        if not results:

            # Empty result does NOT necessarily mean
            # source error. Continue safely.
            continue

        source_results += len(
            results
        )

        for item in results:

            if not item.get(
                "url"
            ):
                continue

            key = fingerprint(
                item
            )

            if key in seen:
                continue

            seen.add(key)

            # Strong filtering BEFORE scoring.
            if not valid_buyer_signal(
                item
            ):
                continue

            text = combined_text(
                item
            )

            market = detect_market(
                text
            )

            (
                intent,
                credibility,
                fit,
                classification,
            ) = score(
                item,
                market,
            )

            if classification not in {
                "HOT",
                "WARM",
            }:
                continue

            reference = (
                db
                .collection(
                    COLLECTION
                )
                .document(
                    key
                )
            )

            try:

                exists = (
                    reference
                    .get()
                    .exists
                )

            except Exception as exc:

                source_errors += 1

                print(
                    "FIRESTORE_READ_ERROR:",
                    exc,
                )

                continue

            if exists:

                print(
                    "EXISTING_LEAD:",
                    key,
                )

                continue

            lead = {

                **item,

                "lead_id":
                    key,

                "language":
                    detect_language(
                        text
                    ),

                "market":
                    market,

                "city_region":
                    detect_city_region(
                        text,
                        market,
                    ),

                "budget":
                    extract_budget(
                        text
                    ),

                "timeframe":
                    extract_timeframe(
                        text
                    ),

                "intent_score":
                    intent,

                "credibility_score":
                    credibility,

                "market_fit_score":
                    fit,

                "classification":
                    classification,

                "route_to":
                    ROUTES.get(
                        market,
                        "Direct Review",
                    ),

                "reply_suggestion":
                    reply_suggestion(
                        market
                    ),

                "found_at":
                    started.isoformat(),
            }

            try:

                reference.set(
                    lead
                )

            except Exception as exc:

                source_errors += 1

                print(
                    "FIRESTORE_WRITE_ERROR:",
                    exc,
                )

                continue

            new_leads.append(
                lead
            )

            print(
                "NEW_LEAD:",
                classification,
                "|",
                market,
                "|",
                item["url"],
            )

    completed = datetime.now(
        timezone.utc
    )

    scan = {

        "started_at":
            started.isoformat(),

        "completed_at":
            completed.isoformat(),

        "status":
            "completed",

        "source":
            "Reddit",

        "queries":
            len(queries),

        "source_results":
            source_results,

        "unique_results":
            len(seen),

        "new_hot_warm":
            len(new_leads),

        "source_errors":
            source_errors,

        "reddit_429_count":
            reddit_429_count,
    }

    try:

        (
            db
            .collection(
                SCAN_LOG_COLLECTION
            )
            .document(
                started.strftime(
                    "%Y%m%dT%H%M%SZ"
                )
            )
            .set(
                scan
            )
        )

    except Exception as exc:

        print(
            "SCAN_LOG_ERROR:",
            exc,
        )

    print(
        json.dumps(
            scan,
            ensure_ascii=False,
            indent=2,
        )
    )

    # =====================================================
    # TELEGRAM
    # =====================================================

    if new_leads:

        for lead in new_leads[
            :MAX_TELEGRAM_LEADS
        ]:

            send_telegram(
                format_lead(
                    lead
                )
            )

    else:

        send_telegram(
            "ℹ️ BAY-S RADAR\n\n"
            "Tarama tamamlandı.\n"
            "Son taramadan beri yeni "
            "HOT/WARM buyer lead bulunamadı.\n\n"
            f"Reddit sorguları: "
            f"{len(queries)}\n"
            f"Toplam sonuç: "
            f"{source_results}\n"
            f"Yeni lead: 0\n"
            f"Kaynak hatası: "
            f"{source_errors}"
        )

    print(
        "BAY-S LEAD RADAR V3 FINISHED"
    )


if __name__ == "__main__":
    main()
