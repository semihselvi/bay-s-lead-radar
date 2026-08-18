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
# BAY-S LEAD RADAR V4.1
# =========================================================

UA = "BAY-S-Lead-Radar/4.1 (+https://github.com/semihselvi)"

REDDIT_URL = "https://www.reddit.com/search.rss"
NEWS_URL = "https://news.google.com/rss/search"

TIMEOUT = 15

# Reddit daha az agresif taranacak.
REDDIT_DELAY = 3
NEWS_DELAY = 0.5

MAX_RESULTS = max(
    10,
    min(int(MAX_RESULTS_PER_SOURCE), 25),
)

# Her taramada tüm 93 sorgu değil,
# havuzdan dönen 12 sorgu kullanılacak.
REDDIT_PER_RUN = 12
NEWS_PER_RUN = 8

# Telegram'a bir taramada en fazla bu kadar lead.
MAX_TELEGRAM_LEADS = 5


S = requests.Session()

S.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
)


# =========================================================
# MARKETS
# =========================================================

EXTRA = {
    "spain": (
        [
            "Spain",
            "Madrid",
            "Barcelona",
            "Valencia",
            "Malaga",
            "Alicante",
            "Marbella",
        ],
        "Golden Visa Partner",
    ),
    "portugal": (
        [
            "Portugal",
            "Lisbon",
            "Porto",
            "Algarve",
            "Cascais",
        ],
        "Golden Visa Partner",
    ),
    "italy": (
        [
            "Italy",
            "Rome",
            "Milan",
            "Florence",
            "Naples",
            "Sicily",
        ],
        "Partner Network",
    ),
    "poland": (
        [
            "Poland",
            "Warsaw",
            "Krakow",
            "Wroclaw",
            "Gdansk",
        ],
        "Partner Network",
    ),
    "czechia": (
        [
            "Czech Republic",
            "Czechia",
            "Prague",
            "Brno",
        ],
        "Partner Network",
    ),
    "austria": (
        [
            "Austria",
            "Vienna",
            "Salzburg",
            "Graz",
        ],
        "Partner Network",
    ),
    "ireland": (
        [
            "Ireland",
            "Dublin",
            "Cork",
            "Galway",
        ],
        "Partner Network",
    ),
    "estonia": (
        [
            "Estonia",
            "Tallinn",
            "Tartu",
        ],
        "Partner Network",
    ),
    "latvia": (
        [
            "Latvia",
            "Riga",
            "Jurmala",
        ],
        "Partner Network",
    ),
    "finland": (
        [
            "Finland",
            "Helsinki",
            "Espoo",
            "Tampere",
        ],
        "Partner Network",
    ),
    "sweden": (
        [
            "Sweden",
            "Stockholm",
            "Gothenburg",
            "Malmo",
        ],
        "Partner Network",
    ),
    "norway": (
        [
            "Norway",
            "Oslo",
            "Bergen",
            "Stavanger",
        ],
        "Partner Network",
    ),
    "denmark": (
        [
            "Denmark",
            "Copenhagen",
            "Aarhus",
        ],
        "Partner Network",
    ),
    "hungary": (
        [
            "Hungary",
            "Budapest",
        ],
        "Partner Network",
    ),
    "romania": (
        [
            "Romania",
            "Bucharest",
            "Cluj",
        ],
        "Partner Network",
    ),
    "bulgaria": (
        [
            "Bulgaria",
            "Sofia",
            "Varna",
            "Burgas",
        ],
        "Partner Network",
    ),
    "luxembourg": (
        [
            "Luxembourg",
        ],
        "Partner Network",
    ),
    "malta": (
        [
            "Malta",
            "Valletta",
            "Sliema",
        ],
        "Partner Network",
    ),
    "uae": (
        [
            "UAE",
            "United Arab Emirates",
            "Dubai",
            "Abu Dhabi",
        ],
        "Partner Network",
    ),
    "qatar": (
        [
            "Qatar",
            "Doha",
        ],
        "Partner Network",
    ),
    "saudi_arabia": (
        [
            "Saudi Arabia",
            "Riyadh",
            "Jeddah",
        ],
        "Partner Network",
    ),
    "slovakia": (
        [
            "Slovakia",
            "Bratislava",
            "Kosice",
        ],
        "Partner Network",
    ),
    "slovenia": (
        [
            "Slovenia",
            "Ljubljana",
            "Koper",
        ],
        "Partner Network",
    ),
    "serbia": (
        [
            "Serbia",
            "Belgrade",
            "Novi Sad",
        ],
        "Partner Network",
    ),
}


SAFE = {
    "north_cyprus": [
        "North Cyprus",
        "Northern Cyprus",
        "Kuzey Kıbrıs",
        "Iskele",
        "Long Beach",
        "Kyrenia",
        "Girne",
        "Esentepe",
        "Famagusta",
        "Gazimağusa",
    ],
    "turkey": [
        "Turkey",
        "Türkiye",
        "Antalya",
        "Alanya",
        "Mersin",
        "Istanbul",
        "İstanbul",
        "Izmir",
        "İzmir",
        "Bodrum",
        "Fethiye",
    ],
    "greece": [
        "Greece",
        "Athens",
        "Thessaloniki",
        "Crete",
        "Rhodes",
        "Corfu",
        "Mykonos",
    ],
    "germany": [
        "Germany",
        "Berlin",
        "Munich",
        "Frankfurt",
        "Hamburg",
        "Cologne",
        "Deutschland",
    ],
    "netherlands": [
        "Netherlands",
        "Amsterdam",
        "Rotterdam",
        "The Hague",
        "Utrecht",
        "Nederland",
    ],
    "belgium": [
        "Belgium",
        "Brussels",
        "Antwerp",
        "Ghent",
    ],
    "france": [
        "France",
        "Paris",
        "Nice",
        "Cannes",
        "Marseille",
        "Lyon",
    ],
    "lithuania": [
        "Lithuania",
        "Vilnius",
        "Kaunas",
        "Klaipeda",
    ],
    "switzerland": [
        "Switzerland",
        "Zurich",
        "Geneva",
        "Lausanne",
        "Basel",
        "Zug",
        "Lugano",
    ],
    "russia": [
        "Russia",
        "Россия",
        "Moscow",
        "Москва",
        "St Petersburg",
        "Санкт-Петербург",
    ],
    "kazakhstan": [
        "Kazakhstan",
        "Казахстан",
        "Almaty",
        "Алматы",
        "Astana",
        "Астана",
    ],
    "montenegro": [
        "Montenegro",
        "Budva",
        "Kotor",
        "Tivat",
        "Podgorica",
        "Bar",
    ],
    "uk": [
        "United Kingdom",
        "UK",
        "London",
        "Manchester",
        "Birmingham",
        "Leeds",
        "Brighton",
    ],
}


MARKET_INFO = {
    key: (
        value,
        ROUTES.get(key, "Partner Network"),
    )
    for key, value in SAFE.items()
}

MARKET_INFO.update(EXTRA)


# =========================================================
# KEYWORDS
# =========================================================

PROP = [
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
    "mortgage",
    "down payment",
    "deposit",
    "rental income",
    "rental yield",
    "golden visa",
    "residency by investment",
    "ev",
    "konut",
    "daire",
    "gayrimenkul",
    "mülk",
    "arsa",
    "квартира",
    "дом",
    "недвижимость",
    "ипотека",
    "аренда",
]

BUY = [
    "looking to buy",
    "want to buy",
    "wanting to buy",
    "planning to buy",
    "ready to buy",
    "thinking of buying",
    "buying a home",
    "buying a house",
    "buying property",
    "buy an apartment",
    "buy apartment",
    "buy a villa",
    "looking for a house",
    "looking for an apartment",
    "cash buyer",
    "first time buyer",
    "first-time buyer",
    "first home buyer",
    "property buyer",
    "looking to purchase",
    "relocating and buying",
    "moving and buying",
    "purchase",
    "how much can i afford",
    "ev almak",
    "ev arıyorum",
    "ev almak istiyorum",
    "satın almak",
    "gayrimenkul almak",
    "yatırım için ev",
    "хочу купить",
    "ищу квартиру",
    "купить квартиру",
    "купить дом",
    "купить недвижимость",
    "нужна квартира",
    "планирую купить",
    "недвижимость за рубежом",
]

CONCRETE = [
    "budget",
    "$",
    "€",
    "£",
    "aed",
    "eur",
    "gbp",
    "usd",
    "chf",
    "try",
    "kzt",
    "rub",
    "mortgage",
    "down payment",
    "deposit",
    "bedroom",
    "1br",
    "2br",
    "3br",
    "1 bhk",
    "2 bhk",
    "3 bhk",
    "rent",
    "rental income",
    "yield",
    "first home",
    "moving",
    "relocating",
    "next month",
    "next year",
    "this year",
    "2026",
    "2027",
    "bütçe",
    "kredi",
    "kapora",
    "oda",
    "kira",
    "taşınmak",
    "я ищу",
    "мой бюджет",
    "ипотека",
    "переезд",
]

PERSONAL = [
    " i ",
    " i'm",
    " i am ",
    " we ",
    " we're",
    " my ",
    " our ",
    " my family",
    " for myself",
    " for me",
    "ben ",
    "biz ",
    "ailem",
    "kendim için",
    "я ",
    "мы ",
    "моя семья",
    "для себя",
]

AGENCY = [
    "for my client",
    "for a client",
    "my clients",
    "client looking",
    "buyer client",
    "customer",
    "real estate agent",
    "estate agent",
    "realtor",
    "broker",
    "developer",
    "property developer",
    "property listing",
    "listing page",
    "our properties",
    "our project",
    "contact us",
    "whatsapp us",
    "call us",
    "we sell",
    "available units",
    "new project",
    "commission",
    "lead generation",
    "marketing agency",
    "property management service",
    "агентство недвижимости",
    "риэлтор",
    "застройщик",
    "продам",
    "продается",
    "продаю",
]

NOISE = {
    "memes",
    "funny",
    "askreddit",
    "offmychest",
    "family",
    "askchicago",
    "whatshouldido",
    "whatdoido",
    "arknights",
}


# =========================================================
# QUERIES
# =========================================================

GLOBAL_Q = [
    '"looking to buy" (property OR house OR apartment)',
    '"want to buy" (property OR house OR apartment)',
    '"first time buyer" (house OR home OR apartment)',
    '"cash buyer" (property OR house)',
    '"property investment" budget',
    '"investment property" budget',
    '"rental income" property',
    '"moving" "buying a home"',
    '"relocating" "buying property"',
    '"holiday home" property',
    '"Golden Visa" property',
    '"EU Golden Visa" property',
    '"residency by investment" property',
    '"хочу купить" недвижимость',
    '"ищу квартиру" недвижимость',
    '"недвижимость за рубежом"',
    '"ev almak istiyorum" gayrimenkul',
    '"Kıbrıs" ev almak',
]

GOLDEN = [
    '"Golden Visa" Greece property',
    '"Golden Visa" Portugal property',
    '"Golden Visa" Spain property',
    '"Golden Visa" Europe buyer',
    '"residency by investment" Greece',
    '"residency by investment" Europe',
]

FIXED = [
    '"North Cyprus" property buyer',
    '"Turkey" property buyer',
    '"Greece" property buyer',
    '"Germany" property buyer',
    '"Netherlands" property buyer',
    '"Belgium" property buyer',
    '"France" property buyer',
    '"Lithuania" property buyer',
    '"Switzerland" property buyer',
    '"Russia" "buy property abroad"',
    '"Kazakhstan" "buy property abroad"',
    '"Montenegro" property buyer',
    '"UK" property buyer',
    '"Spain" property buyer',
    '"Portugal" property buyer',
    '"Italy" property buyer',
    '"Poland" property buyer',
    '"Czech Republic" property buyer',
    '"Austria" property buyer',
    '"Ireland" property buyer',
    '"Estonia" property buyer',
    '"Latvia" property buyer',
    '"Finland" property buyer',
    '"Sweden" property buyer',
    '"Norway" property buyer',
    '"Denmark" property buyer',
    '"UAE" property buyer',
    '"Dubai" property buyer',
    '"Qatar" property buyer',
    '"Saudi Arabia" property buyer',
]


# =========================================================
# FIRESTORE
# =========================================================

def client():
    raw = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON"
    )

    if not raw:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON missing"
        )

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON"
        ) from e

    cred = (
        service_account.Credentials
        .from_service_account_info(info)
    )

    return firestore.Client(
        credentials=cred
    )


# =========================================================
# HELPERS
# =========================================================

def text(item):
    return (
        f"{item.get('title', '')} "
        f"{item.get('text', '')}"
    ).strip()


def has(value, terms):
    value = value.lower()

    return any(
        term.lower() in value
        for term in terms
    )


def subreddit(url):
    match = re.search(
        r"/r/([^/]+)",
        url or "",
    )

    return (
        match.group(1).lower()
        if match
        else ""
    )


def market_for(value):
    value = value.lower()

    order = [
        "north_cyprus",
        "greece",
        "germany",
        "netherlands",
        "belgium",
        "france",
        "switzerland",
        "lithuania",
        "kazakhstan",
        "russia",
        "turkey",
        "montenegro",
        "uk",
    ] + list(EXTRA.keys())

    for key in order:
        for term in MARKET_INFO[key][0]:
            if term.lower() in value:
                return key

    return "unknown"


def budget(value):
    patterns = [
        r"[$€£₺]\s?[\d,.]+(?:\s?[kKmM])?",
        r"\b(?:USD|EUR|GBP|AED|CHF|TRY|KZT|RUB)\s?[\d,.]+(?:\s?[kKmM])?\b",
        r"\b\d{2,3}\s?[kKmM]\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            re.I,
        )

        if match:
            return match.group(0)

    return "Not stated"


def timeframe(value):
    patterns = [
        r"\b(?:within|in|next)\s+\d+\s+(?:days?|weeks?|months?|years?)\b",
        r"\bthis year\b",
        r"\bnext year\b",
        r"\bsoon\b",
        r"\bimmediately\b",
        r"\b2026\b",
        r"\b2027\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            value,
            re.I,
        )

        if match:
            return match.group(0)

    return "Not stated"


def city(value, market):
    if market == "unknown":
        return "Not stated"

    value = value.lower()

    countries = {
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
        "uk",
        "united kingdom",
    }

    for term in MARKET_INFO[market][0]:
        if (
            term.lower() in value
            and term.lower() not in countries
        ):
            return term

    return "Not stated"


def lang(value):
    value = value.lower()

    if re.search(
        r"[а-яё]",
        value,
    ):
        return "Russian"

    if has(
        value,
        [
            "ev almak",
            "ev arıyorum",
            "gayrimenkul",
            "kıbrıs",
            "satın almak",
        ],
    ):
        return "Turkish"

    return "English"


# =========================================================
# VALIDATION
# =========================================================

def valid(item):
    value = text(item)

    if len(value) < 80:
        return False, "too_short"

    if not has(value, PROP):
        return False, "no_property"

    if not has(value, BUY):
        return False, "no_buyer"

    if has(value, AGENCY):
        return False, "agency_or_listing"

    if (
        subreddit(
            item.get("url", "")
        )
        in NOISE
    ):
        return False, "noisy_subreddit"

    if (
        not has(value, CONCRETE)
        and not has(value, PERSONAL)
    ):
        return False, "no_concrete_or_personal"

    return True, "ok"


def score(item, market):
    value = text(item).lower()

    hits = sum(
        1
        for phrase in INTENT_PHRASES
        if phrase.lower() in value
    )

    has_budget = budget(value) != "Not stated"
    has_timeframe = (
        timeframe(value) != "Not stated"
    )
    has_concrete = has(
        value,
        CONCRETE,
    )
    has_personal = has(
        value,
        PERSONAL,
    )
    detailed = len(value) >= 450

    intent = min(
        100,
        45
        + hits * 7
        + (12 if has_budget else 0)
        + (10 if has_timeframe else 0)
        + (10 if has_personal else 0)
        + (5 if has_concrete else 0),
    )

    credibility = min(
        100,
        55
        + (15 if has_budget else 0)
        + (10 if has_timeframe else 0)
        + (10 if has_personal else 0)
        + (10 if detailed else 0)
        + (5 if has_concrete else 0),
    )

    fit = (
        45
        if market == "unknown"
        else 70
    )

    if has_budget:
        fit += 10

    if market in {
        "north_cyprus",
        "turkey",
        "greece",
        "germany",
        "netherlands",
        "belgium",
        "france",
        "switzerland",
        "lithuania",
        "spain",
        "portugal",
        "italy",
    }:
        fit += 8

    fit = max(
        0,
        min(100, fit),
    )

    if (
        intent >= 88
        and credibility >= 80
        and has_concrete
    ):
        classification = "HOT"

    elif (
        intent >= 72
        and credibility >= 70
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


def fp(item):
    raw = "|".join(
        [
            item.get("url", ""),
            item.get("title", ""),
            item.get("author", ""),
        ]
    ).lower()

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()


# =========================================================
# SOURCES
# =========================================================

def reddit(query):
    """
    Returns:
        rows, rate_limited
    """

    try:
        response = S.get(
            REDDIT_URL,
            params={
                "q": query,
                "sort": "new",
                "t": "day",
                "limit": MAX_RESULTS,
            },
            timeout=TIMEOUT,
        )

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After",
                "unknown",
            )

            print(
                "REDDIT_429 "
                f"query={query} "
                f"retry_after={retry_after}"
            )

            return [], True

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        output = []

        for entry in soup.find_all(
            "entry"
        )[:MAX_RESULTS]:

            link = entry.find("link")
            title = entry.find("title")
            content = entry.find("content")
            published = entry.find("published")
            author = entry.find("name")

            output.append(
                {
                    "source": "Reddit",
                    "url": (
                        link.get(
                            "href",
                            "",
                        ).strip()
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
                            strip=True
                        )
                        if published
                        else ""
                    ),
                    "author": (
                        author.get_text(
                            strip=True
                        )
                        if author
                        else ""
                    ),
                }
            )

        return output, False

    except requests.RequestException as e:
        print(
            "REDDIT_ERROR",
            e,
        )

        return [], False


def news(query):
    try:
        response = S.get(
            NEWS_URL,
            params={
                "q": query + " when:1d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        output = []

        for item in soup.find_all(
            "item"
        )[:MAX_RESULTS]:

            link = item.find("link")
            title = item.find("title")
            description = item.find(
                "description"
            )
            published = item.find(
                "pubDate"
            )

            output.append(
                {
                    "source": "Google News",
                    "url": (
                        link.get_text(
                            strip=True
                        )
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
                        description.get_text(
                            " ",
                            strip=True,
                        )
                        if description
                        else ""
                    ),
                    "published": (
                        published.get_text(
                            strip=True
                        )
                        if published
                        else ""
                    ),
                    "author": "",
                }
            )

        return output

    except requests.RequestException as e:
        print(
            "GOOGLE_NEWS_ERROR",
            e,
        )

        return []


# =========================================================
# QUERY POOL
# =========================================================

def market_queries():
    pool = []

    for key, (
        terms,
        _,
    ) in MARKET_INFO.items():

        joined = " OR ".join(
            f'"{term}"'
            for term in terms[:3]
        )

        query = (
            f"({joined}) "
            '("looking to buy" '
            'OR "want to buy" '
            'OR "property buyer" '
            'OR "property investment")'
        )

        pool.append(query)

        if key in {
            "russia",
            "kazakhstan",
        }:
            pool.append(
                f"({joined}) "
                '("хочу купить" '
                'OR "ищу квартиру" '
                'OR "недвижимость за рубежом")'
            )

    return pool


def build_pool():
    pool = []
    seen = set()

    for query in (
        GLOBAL_Q
        + GOLDEN
        + FIXED
        + market_queries()
    ):
        normalized = (
            query.lower()
            .strip()
        )

        if (
            normalized
            and normalized not in seen
        ):
            seen.add(normalized)
            pool.append(query)

    return pool


def select_queries(db):
    """
    V4.1:
    Her çalıştırmada aynı ilk 8 sorgu
    tekrar tekrar çalışmaz.

    Tüm havuz Firestore offset ile döner.
    """

    pool = build_pool()

    state_ref = (
        db.collection(
            SCAN_LOG_COLLECTION
        )
        .document("_query_state")
    )

    snap = state_ref.get()

    data = (
        snap.to_dict()
        if snap.exists
        else {}
    )

    offset = int(
        data.get(
            "offset",
            0,
        )
    )

    selected = []

    if pool:
        for i in range(
            min(
                REDDIT_PER_RUN,
                len(pool),
            )
        ):
            selected.append(
                pool[
                    (offset + i)
                    % len(pool)
                ]
            )

    next_offset = (
        offset + len(selected)
    ) % max(
        1,
        len(pool),
    )

    state_ref.set(
        {
            "offset": next_offset,
            "pool_size": len(pool),
            "updated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }
    )

    return selected, pool


# =========================================================
# LEAD DETAILS
# =========================================================

def route(market):
    return MARKET_INFO.get(
        market,
        (
            "",
            ROUTES.get(
                market,
                "Direct Review",
            ),
        ),
    )[1]


def reply(market):
    replies = {
        "north_cyprus": (
            "Compare location, total acquisition cost, "
            "ownership structure and realistic rental "
            "potential before selecting a project."
        ),
        "greece": (
            "Compare purchase cost, taxes and Golden Visa "
            "requirements before selecting a property."
        ),
        "germany": (
            "Compare purchase price, financing, taxes and "
            "ongoing ownership costs before choosing an area."
        ),
        "netherlands": (
            "Separate purchase budget from closing and "
            "ownership costs before comparing neighborhoods."
        ),
        "france": (
            "Compare purchase budget, acquisition costs and "
            "the living or investment objective first."
        ),
    }

    return replies.get(
        market,
        (
            "Compare total acquisition cost, location, "
            "legal considerations and the investment or "
            "living goal before choosing a property."
        ),
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    chat = os.getenv(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat:
        print(
            "TELEGRAM_NOT_CONFIGURED"
        )
        return

    try:
        response = S.post(
            (
                f"https://api.telegram.org/"
                f"bot{token}/sendMessage"
            ),
            json={
                "chat_id": chat,
                "text": message,
                "disable_web_page_preview": False,
            },
            timeout=10,
        )

        response.raise_for_status()

    except requests.RequestException as e:
        print(
            "TELEGRAM_ERROR",
            e,
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
        f"Market: {lead['market']}\n"
        f"City/Region: "
        f"{lead['city_region']}\n\n"

        f"What they want:\n"
        f"{lead['title']}\n\n"

        f"Budget: {lead['budget']}\n"
        f"Timeframe: {lead['timeframe']}\n"
        f"Intent: "
        f"{lead['intent_score']}/100\n"
        f"Credibility: "
        f"{lead['credibility_score']}/100\n"
        f"Market Fit: "
        f"{lead['market_fit_score']}/100\n"
        f"Route To: {lead['route_to']}\n\n"

        f"Reply suggestion:\n"
        f"{lead['reply_suggestion']}\n\n"

        f"🔗 {lead['url']}"
    )


# =========================================================
# PROCESS RESULT
# =========================================================

def process_rows(
    rows,
    db,
    seen,
    leads,
    rejected,
    errors,
    started,
):
    for item in rows:

        if not item.get("url"):
            continue

        key = fp(item)

        if key in seen:
            continue

        seen.add(key)

        ok, reason = valid(item)

        if not ok:
            rejected[reason] = (
                rejected.get(reason, 0)
                + 1
            )
            continue

        value = text(item)

        market = market_for(value)

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
            rejected["low_score"] = (
                rejected.get(
                    "low_score",
                    0,
                )
                + 1
            )
            continue

        ref = (
            db.collection(
                COLLECTION
            )
            .document(key)
        )

        try:
            if ref.get().exists:
                print(
                    "EXISTING_LEAD:",
                    key,
                )
                continue

        except Exception as e:
            errors["Firestore"] += 1

            print(
                "FIRESTORE_READ_ERROR",
                e,
            )

            continue

        lead = {
            **item,
            "lead_id": key,
            "language": lang(value),
            "market": market,
            "city_region": city(
                value,
                market,
            ),
            "budget": budget(value),
            "timeframe": timeframe(value),
            "intent_score": intent,
            "credibility_score": credibility,
            "market_fit_score": fit,
            "classification": classification,
            "route_to": route(market),
            "reply_suggestion": reply(market),
            "found_at": started.isoformat(),
        }

        try:
            ref.set(lead)

        except Exception as e:
            errors["Firestore"] += 1

            print(
                "FIRESTORE_WRITE_ERROR",
                e,
            )

            continue

        leads.append(lead)

        print(
            f"NEW_LEAD: "
            f"{classification} | "
            f"{market} | "
            f"{item['url']}"
        )


# =========================================================
# MAIN
# =========================================================

def main():
    started = datetime.now(
        timezone.utc
    )

    print(
        "BAY-S LEAD RADAR V4.1 STARTED"
    )

    db = client()

    queries, pool = select_queries(db)

    print(
        f"TOTAL_QUERY_POOL: "
        f"{len(pool)}"
    )

    print(
        f"QUERY_COUNT_THIS_SCAN: "
        f"{len(queries)}"
    )

    seen = set()
    leads = []

    source = {
        "Reddit": 0,
        "Google News": 0,
    }

    errors = {
        "Reddit": 0,
        "Google News": 0,
        "Firestore": 0,
    }

    rejected = {}

    reddit_429_count = 0
    reddit_stopped_early = False

    # -----------------------------------------------------
    # REDDIT
    # -----------------------------------------------------

    for index, query in enumerate(
        queries,
        1,
    ):
        print(
            f"[REDDIT {index}/{len(queries)}] "
            f"{query}"
        )

        try:
            rows, rate_limited = reddit(
                query
            )

        except Exception as e:
            errors["Reddit"] += 1

            print(
                "REDDIT_QUERY_ERROR",
                e,
            )

            rows = []
            rate_limited = False

        # V4.1 ANA DEĞİŞİKLİK:
        # 429 gelirse diğer 11 sorguyu boşuna
        # çalıştırma. Reddit kısmını bitir,
        # Google News'e geç.
        if rate_limited:
            reddit_429_count += 1
            reddit_stopped_early = True

            print(
                "REDDIT_STOPPED_EARLY_AFTER_429"
            )

            break

        source["Reddit"] += len(rows)

        process_rows(
            rows,
            db,
            seen,
            leads,
            rejected,
            errors,
            started,
        )

        if index < len(queries):
            time.sleep(
                REDDIT_DELAY
            )

    # -----------------------------------------------------
    # GOOGLE NEWS
    # -----------------------------------------------------

    news_queries = (
        GLOBAL_Q[:4]
        + GOLDEN[:2]
        + FIXED[:2]
    )[:NEWS_PER_RUN]

    for index, query in enumerate(
        news_queries,
        1,
    ):
        print(
            f"[NEWS {index}/{len(news_queries)}] "
            f"{query}"
        )

        try:
            rows = news(query)

            source[
                "Google News"
            ] += len(rows)

        except Exception as e:
            errors[
                "Google News"
            ] += 1

            print(
                "GOOGLE_NEWS_QUERY_ERROR",
                e,
            )

            rows = []

        process_rows(
            rows,
            db,
            seen,
            leads,
            rejected,
            errors,
            started,
        )

        if index < len(news_queries):
            time.sleep(
                NEWS_DELAY
            )

    # -----------------------------------------------------
    # SCAN LOG
    # -----------------------------------------------------

    finished = datetime.now(
        timezone.utc
    )

    scan = {
        "started_at": started.isoformat(),
        "completed_at": finished.isoformat(),
        "status": "completed",
        "source_results": source,
        "unique_results": len(seen),
        "new_hot_warm": len(leads),
        "source_errors": errors,
        "rejected": rejected,
        "total_query_pool": len(pool),
        "queries_this_scan": len(queries),
        "news_queries_this_scan": len(
            news_queries
        ),
        "reddit_429_count": reddit_429_count,
        "reddit_stopped_early": (
            reddit_stopped_early
        ),
    }

    try:
        (
            db.collection(
                SCAN_LOG_COLLECTION
            )
            .document(
                started.strftime(
                    "%Y%m%dT%H%M%SZ"
                )
            )
            .set(scan)
        )

    except Exception as e:
        print(
            "SCAN_LOG_ERROR",
            e,
        )

    print(
        json.dumps(
            scan,
            ensure_ascii=False,
            indent=2,
        )
    )

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

    if leads:

        # HOT önce, sonra WARM
        leads.sort(
            key=lambda x: (
                0
                if x["classification"]
                == "HOT"
                else 1,
                -x["intent_score"],
                -x["credibility_score"],
                -x["market_fit_score"],
            )
        )

        for lead in leads[
            :MAX_TELEGRAM_LEADS
        ]:
            telegram(
                format_lead(lead)
            )

    else:
        telegram(
            "ℹ️ BAY-S RADAR\n\n"
            "Tarama tamamlandı.\n"
            "Son taramadan beri yeni HOT/WARM "
            "buyer lead bulunamadı.\n\n"
            f"Reddit sonuçları: "
            f"{source['Reddit']}\n"
            f"Google News sonuçları: "
            f"{source['Google News']}\n"
            f"Yeni lead: 0\n"
            f"Elgenen aday: "
            f"{sum(rejected.values())}\n"
            f"Reddit 429: "
            f"{reddit_429_count}\n"
            f"Reddit erken durdu: "
            f"{reddit_stopped_early}"
        )

    print(
        "BAY-S LEAD RADAR V4.1 FINISHED"
    )


if __name__ == "__main__":
    main()
