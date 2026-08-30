from __future__ import annotations

import os
import re
from typing import Any

import main as core
import main_v5_1 as gate
import main_v5_2 as v52


VERSION = "5.3-resilient-buyer-radar"
v52.VERSION = VERSION
gate.VERSION = VERSION
gate.v5.VERSION = VERSION

# Keep the web search budget focused. These queries are enough to cover the
# strongest EN/RU/DE/PL buyer-intent patterns without burning credits on broad
# world-property searches.
gate.v5.EXA_QUERIES = [
    ("North Cyprus looking to buy property apartment villa budget", ["reddit.com", "expat.com", "britishexpats.com"]),
    ("Northern Cyprus moving buying home property expat", ["reddit.com", "expat.com", "britishexpats.com"]),
    ("North Cyprus which area should I buy property", ["reddit.com", "expat.com", "britishexpats.com"]),
    ("North Cyprus forum property wanted budget", None),
    ("Северный Кипр хочу купить квартиру недвижимость бюджет", ["reddit.com", "expat.com"]),
    ("Северный Кипр ищу квартиру для покупки бюджет", None),
    ("Nordzypern suche Immobilie Wohnung zum Kauf", ["reddit.com", "expat.com"]),
    ("Nordzypern Wohnung kaufen Auswandern Forum", None),
    ("Cypr Północny chcę kupić nieruchomość mieszkanie", ["reddit.com", "expat.com"]),
    ("Cypr Północny mieszkanie kupić forum", None),
]

# Direct Reddit RSS is blocked in GitHub Actions. Reddit remains covered through
# indexed web search providers.
gate.v5.REDDIT_QUERIES = []


# ---------------------------------------------------------------------------
# WEB PROVIDER FALLBACK: Exa -> Serper
# ---------------------------------------------------------------------------

_EXA_DISABLED_FOR_RUN = False


def _site_query(query: str, domains: list[str] | None) -> str:
    if not domains:
        return query
    sites = " OR ".join(f"site:{d}" for d in domains)
    return f"{query} ({sites})"


def _serper_search(query: str, include_domains: list[str] | None = None) -> list[dict[str, Any]]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        print("SERPER_NOT_CONFIGURED")
        return []

    q = _site_query(query, include_domains)
    try:
        r = core.requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": key,
                "Content-Type": "application/json",
            },
            json={
                "q": q,
                "num": 10,
                "hl": "en",
            },
            timeout=30,
        )
        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:400]
            print(f"SERPER_HTTP_{r.status_code}: {detail}")
            return []

        data = r.json()
        out = []
        for row in (data.get("organic") or [])[:10]:
            out.append({
                "source": "Serper",
                "url": row.get("link", ""),
                "title": row.get("title", ""),
                "text": row.get("snippet", ""),
                "published": "",  # direct buyer language may pass without date
                "author": "",
            })
        print(f"SERPER_OK query={query} results={len(out)}")
        return out
    except Exception as exc:
        print(f"SERPER_ERROR query={query} error={type(exc).__name__}: {exc}")
        return []


def resilient_web_search(query: str, include_domains: list[str] | None = None):
    global _EXA_DISABLED_FOR_RUN

    exa_key = os.getenv("EXA_API_KEY", "").strip()
    if exa_key and not _EXA_DISABLED_FOR_RUN:
        payload = {
            "query": query,
            "type": "auto",
            "numResults": 5,
            "contents": {"text": True},
        }
        if include_domains:
            payload["includeDomains"] = include_domains

        try:
            r = core.requests.post(
                "https://api.exa.ai/search",
                json=payload,
                headers={
                    "x-api-key": exa_key,
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                rows = [
                    {
                        "source": "Exa",
                        "url": x.get("url", ""),
                        "title": x.get("title", ""),
                        "text": x.get("text", ""),
                        "published": x.get("publishedDate", ""),
                        "author": "",
                    }
                    for x in (data.get("results") or [])[:5]
                ]
                print(f"EXA_OK query={query} results={len(rows)}")
                return rows

            if r.status_code == 402:
                _EXA_DISABLED_FOR_RUN = True
                print("WEB_PROVIDER_SWITCH: Exa credits exhausted -> Serper")
            else:
                print(f"EXA_HTTP_{r.status_code}: fallback_to_serper")
        except Exception as exc:
            print(f"EXA_ERROR query={query} error={type(exc).__name__}: {exc} -> Serper")

    return _serper_search(query, include_domains)


core.exa_search = resilient_web_search


# ---------------------------------------------------------------------------
# TELEGRAM: terse buyer-demand recovery
# ---------------------------------------------------------------------------

# Real buyers often write short posts such as "ищу 1+1 в Искеле до £90,000"
# without the word "купить". Treat this as purchase demand only when there is a
# purchase-scale budget and no rent signal. This keeps rent/vehicle/flea-market
# noise out while recovering high-value terse buyer posts.
TG_TERSE_DEMAND_RE = re.compile(
    r"(?:"
    r"\b(?:looking\s+for|seeking)\b.{0,120}\b(?:property|apartment|flat|house|villa|studio|land)\b|"
    r"\b(?:ищу|ищем|нужна|нужен|нужно|рассматриваю|рассматриваем|подбираю|подбираем|интересует)\b"
    r".{0,140}\b(?:недвижимост\w*|квартир\w*|апартамент\w*|вилл\w*|дом\w*|участ\w*|земл\w*)\b|"
    r"\b(?:suche|suchen)\b.{0,120}\b(?:immobilie|wohnung|haus|villa|apartment|grundst(?:u|ü)ck)\b|"
    r"\b(?:szukam|szukamy)\b.{0,120}\b(?:nieruchomość|nieruchomosci|mieszkanie|apartament|willa|dom|działk\w*|dzialk\w*)\b|"
    r"\b(?:arıyorum|ariyorum|bakıyorum|bakiyorum)\b.{0,120}\b(?:daire|ev|villa|arsa|konut|gayrimenkul)\b"
    r")",
    re.I | re.S,
)

_AMOUNT_RE = re.compile(
    r"(?P<sym1>[£€$])?\s*(?P<num>\d{1,3}(?:[\s.,]\d{3})+|\d+(?:[.,]\d+)?)\s*(?P<k>[kK])?\s*(?P<sym2>[£€$])?",
    re.I,
)


def _purchase_scale_budget(text: str) -> bool:
    for m in _AMOUNT_RE.finditer(text or ""):
        if not (m.group("sym1") or m.group("sym2") or m.group("k")):
            continue
        raw = m.group("num").replace(" ", "")
        # thousands separators are far more likely than decimals for property budgets
        if raw.count(",") + raw.count(".") > 0:
            chunks = re.split(r"[.,]", raw)
            if len(chunks[-1]) == 3:
                raw = "".join(chunks)
            else:
                raw = raw.replace(",", ".")
        try:
            value = float(raw)
        except Exception:
            continue
        if m.group("k"):
            value *= 1000
        if value >= 10000:
            return True
    return False


_original_refine = gate.refine_telegram_property_buyer


def refine_with_budgeted_demand(lead: dict[str, Any]):
    result = _original_refine(lead)
    if result is not None:
        return result

    if str(lead.get("market") or "") != "north_cyprus":
        return None

    text = str(lead.get("message") or "")
    if not gate.TG_PROPERTY_RE.search(text):
        return None
    if gate.TG_RENT_RE.search(text):
        return None
    if gate.TG_SUPPLY_RE.search(text):
        return None
    if not TG_TERSE_DEMAND_RE.search(text):
        return None
    if not _purchase_scale_budget(text):
        return None

    out = dict(lead)
    out["classification"] = "HOT"
    out["buyer_signal"] = "budgeted_property_demand"
    out["telegram_score"] = max(int(out.get("telegram_score") or 0), 74)
    out["budget_detected"] = True
    out["radar_version"] = VERSION
    return out


gate.refine_telegram_property_buyer = refine_with_budgeted_demand

# V5.2's candidate-first prefilter reads TG_SELF_BUY_RE before refine(). Extend it
# with the terse-demand pattern so those messages reach the strict final gate.
gate.TG_SELF_BUY_RE = re.compile(
    f"(?:{gate.TG_SELF_BUY_RE.pattern})|(?:{TG_TERSE_DEMAND_RE.pattern})",
    re.I | re.S,
)


def main() -> None:
    gate.v5.main()


if __name__ == "__main__":
    main()
