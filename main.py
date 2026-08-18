import os
import re
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
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
    return [
        ("North Cyprus buying property personal buyer", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("North Cyprus looking to buy apartment personal budget", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("North Cyprus moving buying home personal experience", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("Kuzey Kıbrıs ev almak istiyorum bütçe", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Kuzey Kıbrıs gayrimenkul yatırım düşünüyorum", ["expat.com", "reddit.com"]),
        ("North Cyprus property buyer question lawyer title", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("Türkiye ev alacağım bütçe konut kredisi", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye ev almayı düşünüyorum yatırım kira", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye hangi şehirden ev almalıyım yatırım", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye 1+1 2+1 ev alacağım bütçem", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye taşınacağım ev satın almak istiyorum", ["forum.donanimhaber.com", "technopat.net", "r10.net"]),
        ("Türkiye yurtdışından ev alma expat personal", ["expat.com", "reddit.com"]),
        ("buying property in Cyprus personal budget question", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("buying property in Turkey personal budget question", ["expat.com", "reddit.com"]),
        ("buying property abroad personal budget mortgage", ["forums.moneysavingexpert.com", "expat.com", "reddit.com"]),
        ("holiday home Cyprus personal buyer question", ["britishexpats.com", "expat.com", "reddit.com"]),
        ("moving to Cyprus buying a home personal experience", ["expat.com", "britishexpats.com", "reddit.com"]),
        ("Greece property personal buyer budget relocation", ["expat.com", "reddit.com"]),
        ("Portugal property personal buyer budget relocation", ["expat.com", "reddit.com"]),
        ("Golden Visa property personal buyer budget Greece Portugal", ["expat.com", "reddit.com"]),
        ("Germany property personal buyer moving budget", ["expat.com", "reddit.com"]),
        ("Netherlands property personal buyer moving budget", ["expat.com", "reddit.com"]),
        ("France property personal buyer moving budget", ["expat.com", "reddit.com"]),
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
# MAIN
# ---------------------------------------------------------

def main():

    started = datetime.now(
        timezone.utc
    )

    queries = build_queries()

    print(
        f"BAY-S RADAR V4.5.1-QUALITY STARTED | "
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
        "quality_gate": "personal_buyer_and_no_listing_noise",
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
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
