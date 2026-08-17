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


# =========================================================
# BAY-S LEAD RADAR
# Reddit-first buyer intent scanner
# =========================================================

USER_AGENT = (
    "BAY-S-Lead-Radar/2.0 "
    "(buyer intent research; +https://github.com/semihselvi)"
)

REDDIT_SEARCH_URL = "https://www.reddit.com/search.rss"

REQUEST_TIMEOUT = 15
REDDIT_DELAY = 2.5
MAX_RETRIES = 2
MAX_TELEGRAM_LEADS = 10


# BeautifulSoup XMLParsedAsHTMLWarning sadece uyarıdır.
# lxml gerektirmeden Reddit Atom/RSS verisini okuyacağız.
warnings.filterwarnings(
    "ignore",
    category=XMLParsedAsHTMLWarning,
)


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
# FIREBASE
# =========================================================

def firebase_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

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
# REDDIT
# =========================================================

def reddit_search(query):
    for attempt in range(MAX_RETRIES + 1):

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

                retry_after = (
                    response.headers.get("Retry-After")
                )

                try:
                    wait = int(retry_after)
                except (TypeError, ValueError):
                    wait = 5

                wait = max(3, min(wait, 20))

                print(
                    f"REDDIT_429 "
                    f"attempt={attempt + 1} "
                    f"wait={wait}s "
                    f"query={query}"
                )

                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                    continue

                return []

            response.raise_for_status()

            return parse_reddit(response.text)

        except requests.RequestException as exc:

            print(
                f"REDDIT_ERROR "
                f"attempt={attempt + 1} "
                f"query={query} "
                f"error={exc}"
            )

            if attempt < MAX_RETRIES:
                time.sleep(3 + attempt * 2)
            else:
                return []

        finally:
            time.sleep(REDDIT_DELAY)

    return []


def parse_reddit(xml_text):
    soup = BeautifulSoup(
        xml_text,
        "html.parser",
    )

    results = []

    for entry in soup.find_all("entry")[
        :MAX_RESULTS_PER_SOURCE
    ]:

        link = entry.find("link")
        title = entry.find("title")
        content = entry.find("content")
        published = entry.find("published")
        author = entry.find("name")

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
# QUERY BUILDER
# =========================================================

def build_queries():

    queries = [
        # Global English
        '"looking to buy" property',
        '"looking for" apartment',
        '"looking for" house',
        '"want to buy" property',
        '"want to buy" house',
        '"buying property" budget',
        '"buying a home" budget',
        '"property investment" budget',
        '"investment property" budget',
        '"cash buyer" property',
        '"ready to buy" property',
        '"planning to buy" property',
        '"looking to purchase" property',
        '"moving to" "buying a home"',
        '"relocating to" "buy property"',
        '"holiday home" "looking to buy"',
        '"Golden Visa" property',
        '"EU Golden Visa" property',
        '"residency by investment" property',

        # Turkish
        '"ev almak istiyorum"',
        '"ev arıyorum"',
        '"gayrimenkul almak"',
        '"satın almak istiyorum" ev',
        '"yatırım için ev"',
        '"gayrimenkul yatırımı"',
        '"Kıbrıs" ev almak',
        '"Kuzey Kıbrıs" ev almak',
        '"Kuzey Kıbrıs" gayrimenkul',

        # Russian
        '"хочу купить" недвижимость',
        '"ищу квартиру"',
        '"купить квартиру"',
        '"купить дом"',
        '"купить недвижимость"',
        '"недвижимость за рубежом"',
        '"инвестиции в недвижимость"',
        '"планирую купить" недвижимость',

        # Golden Visa
        '"Golden Visa" Greece property',
        '"Golden Visa" Portugal property',
        '"Golden Visa" Spain property',
        '"Golden Visa" Europe property',
        '"EU Golden Visa" buyer',

        # Partner markets
        '"Germany" "looking to buy property"',
        '"Netherlands" "looking to buy property"',
        '"Belgium" "looking to buy property"',
        '"France" "looking to buy property"',
        '"Lithuania" "looking to buy property"',
        '"Switzerland" "looking to buy property"',
        '"Russia" "buy property abroad"',
        '"Kazakhstan" "buy property abroad"',
        '"Montenegro" "looking to buy property"',
        '"UK" "looking to buy property"',
    ]

    # Config'deki tüm market ve şehirleri de sorgulara ekle.
    for market, places in MARKETS.items():

        selected = places[:4]

        for place in selected:

            queries.extend([
                f'"{place}" "looking to buy" property',
                f'"{place}" "looking for" apartment',
                f'"{place}" "looking for" house',
                f'"{place}" "property investment" budget',
            ])

            if market in ("russia", "kazakhstan"):

                queries.extend([
                    f'"{place}" "хочу купить" недвижимость',
                    f'"{place}" "ищу квартиру"',
                    f'"{place}" "купить недвижимость"',
                ])

    # Duplicate temizleme.
    unique = []
    seen = set()

    for query in queries:

        query = query.strip()

        if not query:
            continue

        if query in seen:
            continue

        seen.add(query)
        unique.append(query)

    return unique


# =========================================================
# HELPERS
# =========================================================

def fingerprint(item):

    raw = "|".join([
        item.get("url", ""),
        item.get("title", ""),
        item.get("author", ""),
    ])

    return hashlib.sha256(
        raw.lower().encode("utf-8")
    ).hexdigest()


def text_of(item):

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

    value = text.lower()

    if market not in MARKETS:
        return "Not stated"

    places = MARKETS[market]

    for place in places:

        if place.lower() in value:

            # Ülke adını şehir yerine yazma.
            country_terms = {
                "Turkey",
                "Türkiye",
                "Greece",
                "Germany",
                "Netherlands",
                "Belgium",
                "France",
                "Lithuania",
                "Switzerland",
                "Russia",
                "Kazakhstan",
                "Montenegro",
                "United Kingdom",
                "UK",
                "North Cyprus",
                "Northern Cyprus",
            }

            if place in country_terms:
                continue

            return place

    return "Not stated"


def detect_language(text):

    value = text.lower()

    if re.search(r"[а-яё]", value):
        return "Russian"

    if any(
        term in value
        for term in [
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
# SCORING
# =========================================================

def score(item, market):

    text = text_of(item).lower()

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
        phrase in text
        for phrase in [
            " i ",
            " i'm ",
            " we ",
            " we're ",
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
        35
        + intent_hits * 8
        + (12 if budget else 0)
        + (10 if timeframe else 0)
        + (8 if personal else 0)
        - exclude_hits * 20,
    )

    credibility = min(
        100,
        55
        + (15 if budget else 0)
        + (10 if timeframe else 0)
        + (8 if personal else 0)
        + (10 if detailed else 0)
        - exclude_hits * 25,
    )

    fit = (
        70
        if market != "unknown"
        else 40
    )

    if budget:
        fit += 10

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
            "https://api.telegram.org/"
            f"bot{token}/sendMessage",
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


def reply_suggestion(market):

    suggestions = {

        "north_cyprus":
            "Before looking at specific projects, "
            "I’d compare location, total acquisition "
            "cost, title/ownership structure and "
            "realistic rental potential.",

        "turkey":
            "I’d compare the total purchase cost, "
            "location, financing and rental demand "
            "before choosing a property.",

        "greece":
            "For Greece, I’d compare purchase costs, "
            "taxes and the Golden Visa requirements "
            "before selecting a property.",

        "germany":
            "I’d compare the purchase price, financing, "
            "taxes and ongoing ownership costs first.",

        "netherlands":
            "I’d separate the purchase budget from "
            "closing and ongoing ownership costs before "
            "comparing neighborhoods.",

        "france":
            "I’d compare the property budget, "
            "acquisition costs and the actual living "
            "or investment objective first.",
    }

    return suggestions.get(
        market,
        "Before choosing a property, I’d compare "
        "the total acquisition cost, location, legal "
        "considerations and the investment or living goal.",
    )


def format_lead(lead):

    emoji = (
        "🔥"
        if lead["classification"] == "HOT"
        else "🟠"
    )

    return (
        f"{emoji} BAY-S RADAR — "
        f"{lead['classification']}\n\n"

        f"Source: {lead['source']}\n"
        f"Author: "
        f"{lead.get('author') or 'Not stated'}\n"
        f"Language: {lead['language']}\n"

        f"Target: {lead['market']}\n"
        f"City/Region: "
        f"{lead['city_region']}\n"

        f"What they want:\n"
        f"{lead['title']}\n\n"

        f"Budget: {lead['budget']}\n"
        f"Timeframe: {lead['timeframe']}\n\n"

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

        f"🔗 {lead['url']}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    started = datetime.now(
        timezone.utc
    )

    print(
        "BAY-S LEAD RADAR V2 STARTED"
    )

    queries = build_queries()

    print(
        f"QUERY_COUNT: {len(queries)}"
    )

    db = firebase_client()

    seen = set()
    new_leads = []

    source_results = 0
    source_errors = 0

    for index, query in enumerate(
        queries,
        start=1,
    ):

        print(
            f"[{index}/{len(queries)}] "
            f"{query}"
        )

        try:

            results = reddit_search(
                query
            )

        except Exception as exc:

            source_errors += 1

            print(
                f"QUERY_ERROR: {exc}"
            )

            continue

        source_results += len(
            results
        )

        for item in results:

            url = item.get(
                "url",
                "",
            ).strip()

            if not url:
                continue

            key = fingerprint(
                item
            )

            if key in seen:
                continue

            seen.add(key)

            text = text_of(
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
                .collection(COLLECTION)
                .document(key)
            )

            if reference.get().exists:

                print(
                    f"EXISTING_LEAD: {key}"
                )

                continue

            lead = {
                **item,

                "lead_id": key,

                "language":
                    detect_language(
                        text
                    ),

                "market": market,

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

            reference.set(
                lead
            )

            new_leads.append(
                lead
            )

            print(
                f"NEW_LEAD: "
                f"{classification} | "
                f"{market} | "
                f"{url}"
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

    }

    scan_id = started.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    (
        db
        .collection(
            SCAN_LOG_COLLECTION
        )
        .document(
            scan_id
        )
        .set(scan)
    )

    print(
        json.dumps(
            scan,
            ensure_ascii=False,
            indent=2,
        )
    )

    # =====================================================
    # TELEGRAM NOTIFICATION
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
        "BAY-S LEAD RADAR V2 FINISHED"
    )


if __name__ == "__main__":
    main()
