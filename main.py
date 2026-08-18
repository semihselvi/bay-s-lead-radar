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
GOOGLE_BATCH_SIZE = 10
GOOGLE_BATCH_PAUSE = 12


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
# GOOGLE WEB SEARCH
# ---------------------------------------------------------

def google_web_search(query):
    url = "https://www.google.com/search"
    try:
        r = get(
            url,
            {
                "q": query,
                "num": 10,
                "hl": "en",
            },
        )
        if r.status_code == 429:
            print(
                f"GOOGLE_429 query={query}"
            )
            return [], True

        r.raise_for_status()
        soup = BeautifulSoup(
            r.text,
            "html.parser",
        )

        out = []
        seen_urls = set()

        for container in soup.select("div.g, div.MjjYud"):
            a = container.find(
                "a",
                href=True,
            )
            h = container.find("h3")

            if not a or not h:
                continue

            href = a.get("href", "")
            title = h.get_text(
                " ",
                strip=True,
            )

            if not href.startswith("http"):
                continue

            if href in seen_urls:
                continue

            seen_urls.add(href)

            text = container.get_text(
                " ",
                strip=True,
            )

            out.append(
                {
                    "source": "Google Search",
                    "url": href,
                    "title": title,
                    "text": text,
                    "published": "",
                    "author": "",
                }
            )

        return out, False

    except Exception as e:
        print(
            f"GOOGLE_SEARCH_ERROR "
            f"query={query} error={e}"
        )
        return [], False

# ---------------------------------------------------------
# QUERY BUILDER
# ---------------------------------------------------------

def build_queries():

    queries = []

    # Ana buyer intent kümeleri.
    intent_groups = [
        '"looking to buy" property',
        '"looking for" apartment house',
        '"want to buy" property',
        '"buying a home" budget',
        '"property investment" budget',
        '"moving" "buying a home"',
        '"relocating" "buying property"',
        '"Golden Visa" property',
        '"residency by investment" property',
    ]

    # Her market için geniş ama tek tek patlamayan sorgular.
    for market, places in MARKETS.items():

        if not places:
            continue

        selected_places = places[:6]

        place_query = " OR ".join(
            f'"{p}"'
            for p in selected_places
        )

        for intent in intent_groups:
            queries.append(
                f"({place_query}) {intent}"
            )

        # Rusça pazar
        if market in ("russia", "kazakhstan"):

            queries.extend([
                f"({place_query}) "
                f'"хочу купить" недвижимость',

                f"({place_query}) "
                f'"ищу квартиру"',

                f"({place_query}) "
                f'"купить недвижимость за рубежом"',
            ])

    # Global buyer / Golden Visa taraması.
    queries.extend([
        '"EU Golden Visa" property buyer',
        '"Golden Visa" Greece property buyer',
        '"Greece" "looking to buy" property',
        '"Germany" "looking to buy" property',
        '"Netherlands" "looking to buy" property',
        '"Belgium" "looking to buy" property',
        '"France" "looking to buy" property',
        '"Lithuania" "looking to buy" property',
        '"Switzerland" "looking to buy" property',
        '"Russia" "buy property abroad"',
        '"Kazakhstan" "buy property abroad"',
        '"Turkey" "buy property" budget',
        '"North Cyprus" "buy property"',
    ])

    # Aynı sorgular varsa temizle.
    return list(dict.fromkeys(queries))


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
        f"BAY-S RADAR V4.5-BATCH STARTED | "
        f"queries={len(queries)}"
    )

    client = db()

    seen = set()
    candidates = []

    errors = 0

    source_counts = {
        "Reddit": 0,
        "Google News": 0,
        "Google Search": 0,
        "Google Search": 0,
    }

    source_errors = {
        "Reddit": 0,
        "Google News": 0,
        "Google Search": 0,
    }

    # -----------------------------------------------------
    # SEARCH
    # -----------------------------------------------------

    google_queries = list(queries)
    google_stopped = False
    google_429_count = 0
    google_results = 0

    # Google is tested in batches. After each batch we run
    # Google News and pause before the next Google batch.
    for batch_start in range(
        0,
        len(google_queries),
        GOOGLE_BATCH_SIZE,
    ):
        batch = google_queries[
            batch_start:
            batch_start + GOOGLE_BATCH_SIZE
        ]

        batch_no = (
            batch_start // GOOGLE_BATCH_SIZE
        ) + 1

        total_batches = (
            (len(google_queries)
             + GOOGLE_BATCH_SIZE - 1)
            // GOOGLE_BATCH_SIZE
        )

        print(
            f"GOOGLE_BATCH "
            f"{batch_no}/{total_batches} "
            f"size={len(batch)}"
        )

        for index, q in enumerate(
            batch,
            start=batch_start + 1,
        ):
            print(
                f"[GOOGLE "
                f"{index}/{len(google_queries)}] "
                f"{q}"
            )

            try:
                results, limited = (
                    google_web_search(q)
                )

                google_results += len(
                    results
                )

                if limited:
                    google_429_count += 1
                    google_stopped = True
                    print(
                        "GOOGLE_STOPPED_AFTER_429"
                    )
                    break

                source_counts[
                    "Google Search"
                ] = google_results

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

                    if classification not in (
                        "HOT",
                        "WARM",
                    ):
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
                source_errors[
                    "Google Search"
                ] += 1
                print(
                    f"GOOGLE_LOOP_ERROR "
                    f"{e}"
                )

        # Google News between Google batches.
        if google_stopped:
            break

        print(
            f"[GOOGLE NEWS BRIDGE] "
            f"batch={batch_no}"
        )

        bridge_queries = (
            queries[
                batch_start:
                batch_start + 4
            ]
        )

        for q in bridge_queries:
            try:
                results = google_news(q)

                source_counts[
                    "Google News"
                ] += len(results)

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

                    if classification not in (
                        "HOT",
                        "WARM",
                    ):
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
                source_errors[
                    "Google News"
                ] += 1

        if (
            batch_start
            + GOOGLE_BATCH_SIZE
            < len(google_queries)
        ):
            print(
                f"GOOGLE_BATCH_PAUSE "
                f"{GOOGLE_BATCH_PAUSE}s"
            )
            time.sleep(
                GOOGLE_BATCH_PAUSE
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
        "unique_results": len(seen),
        "new_hot_warm": len(candidates),
        "google_results": google_results,
        "google_429_count": google_429_count,
        "google_stopped": google_stopped,
        "google_batch_size": GOOGLE_BATCH_SIZE,
        "google_batch_pause": GOOGLE_BATCH_PAUSE,
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
            f"Reddit sonuçları: "
            f"{source_counts['Reddit']}\n"
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
