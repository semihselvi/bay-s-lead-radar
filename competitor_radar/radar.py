"""Prime Kibris competitor pilot. Public pages only; no login, CAPTCHA bypass or Facebook scraping."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ALLOWED = {"101evler.com", "www.101evler.com", "hangiev.com", "www.hangiev.com"}
HEADERS = {"User-Agent": "PrimeKibrisCompetitorPilot/0.1 (+https://primekibris.com)"}
TIMEOUT = 15
SLEEP = 1.3
GBP_RE = re.compile(r"(?:£|GBP|STG)\\s*([0-9][0-9,. ]{3,})|([0-9][0-9,. ]{3,})\\s*(?:£|GBP|STG)", re.I)
SQM_RE = re.compile(r"(?<!\\d)(\\d{2,4})\\s*(?:m²|m2|sq\\.?\\s?m)", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def canonical_url(url):
    p = urlparse(url)
    host = p.netloc.lower().split(":")[0]
    if p.scheme != "https" or host not in ALLOWED:
        return None
    return urlunparse(("https", host, p.path.rstrip("/") or "/", "", "", ""))


def gbp_number(s):
    digits = re.sub(r"[^0-9]", "", str(s).split(".")[0] if re.search(r"\\.\\d{2}$", str(s)) else str(s))
    try:
        value = int(digits)
        return value if 10000 <= value <= 10000000 else None
    except ValueError:
        return None


def extract_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
    title = title or (soup.title.get_text(" ", strip=True) if soup.title else "")
    main = soup.find("main") or soup.find("article") or soup
    for node in main.select("script,style,footer,nav,aside"):
        node.decompose()
    content = main.get_text(" ", strip=True)[:13000]
    price, area = None, None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            entries = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        nodes = entries if isinstance(entries, list) else [entries]
        for obj in nodes:
            if not isinstance(obj, dict):
                continue
            nodes2 = obj.get("@graph", [obj])
            for item in nodes2 if isinstance(nodes2, list) else [obj]:
                if not isinstance(item, dict):
                    continue
                offers = item.get("offers", {})
                offers = offers[0] if isinstance(offers, list) and offers else offers
                if isinstance(offers, dict) and str(offers.get("priceCurrency", "")).upper() in ("GBP", "STG", ""):
                    price = price or gbp_number(offers.get("price", ""))
                size = item.get("floorSize") or item.get("area") or {}
                if isinstance(size, dict):
                    area = area or gbp_number_for_area(size.get("value"))
    if price is None:
        for key in ("product:price:amount", "og:price:amount"):
            tag = soup.find("meta", attrs={"property": key})
            if tag:
                price = gbp_number(tag.get("content", ""))
                if price:
                    break
    if price is None:
        # Price fallback is deliberately constrained to the page title and first 900 characters.
        m = GBP_RE.search(title + " " + content[:900])
        price = gbp_number(m.group(1) or m.group(2)) if m else None
    if area is None:
        m = SQM_RE.search(title + " " + content[:1200])
        area = int(m.group(1)) if m else None
    return {"url": url, "title": title[:240], "snippet": content[:750], "price_gbp": price, "area_m2": area}


def gbp_number_for_area(s):
    try:
        n = int(float(str(s).replace(",", ".")))
        return n if 15 <= n <= 10000 else None
    except (ValueError, TypeError):
        return None


def classify(prop, listing):
    """Never certify same unit from text; require independently checked photos/unit number."""
    corpus = norm(listing["title"] + " " + listing["snippet"])
    aliases = [norm(a) for a in prop["aliases"]]
    project_match = any(a in corpus for a in aliases)
    if not project_match:
        return "unrelated", 0, ["project_not_confirmed"]
    score, reasons = 45, ["project_match"]
    beds = prop.get("beds")
    if beds is not None:
        bed_patterns = [rf"\\b{beds}\\s*\\+\\s*1\\b", rf"\\b{beds}\\s*(?:bed|yatak|zimmer)"]
        if any(re.search(p, corpus) for p in bed_patterns):
            score += 16
            reasons.append("bedrooms_match")
    area = listing.get("area_m2")
    if area:
        expected = [prop["area_m2"]]
        if prop.get("extra_area_m2"):
            expected.append(prop["area_m2"] + prop["extra_area_m2"])
        if any(abs(area - v) <= 3 for v in expected):
            score += 21
            reasons.append("area_match")
        elif min(abs(area - v) for v in expected) >= 20:
            score -= 18
            reasons.append("area_differs")
    floor = prop.get("floor")
    if floor is not None and re.search(rf"\\b{floor}\\s*(?:kat|floor|etage)\\b", corpus):
        score += 12
        reasons.append("floor_match")
    if prop.get("land_m2") and str(prop["land_m2"]) in corpus:
        score += 10
        reasons.append("land_match")
    return ("possible_same_needs_photos" if score >= 76 else "same_project_competitor"), max(0, min(score, 99)), reasons


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.robots = {}

    def allowed(self, url):
        p = urlparse(url)
        if p.netloc not in self.robots:
            rp = RobotFileParser()
            robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
            try:
                r = self.session.get(robots_url, timeout=TIMEOUT)
                if r.status_code != 200:
                    self.robots[p.netloc] = None
                else:
                    rp.parse(r.text.splitlines())
                    self.robots[p.netloc] = rp
            except requests.RequestException:
                self.robots[p.netloc] = None
        rp = self.robots[p.netloc]
        return None if rp is None else rp.can_fetch(HEADERS["User-Agent"], url)

    def get_listing(self, url):
        url = canonical_url(url)
        if not url:
            return {"url": str(url), "status": "invalid_url"}
        permission = self.allowed(url)
        if permission is not True:
            return {"url": url, "status": "robots_blocked" if permission is False else "robots_unavailable"}
        try:
            r = self.session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if canonical_url(r.url) is None:
                return {"url": url, "status": "redirect_not_allowed"}
            if r.status_code == 404 or r.status_code == 410:
                return {"url": url, "status": "gone_candidate"}
            if r.status_code != 200:
                return {"url": url, "status": "http_error", "http_status": r.status_code}
            content_type = r.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                return {"url": url, "status": "unexpected_content"}
            obj = extract_page(r.text, canonical_url(r.url))
            obj["status"] = "ok" if obj["title"] and obj["price_gbp"] else "unverified_html"
            return obj
        except requests.RequestException as e:
            return {"url": url, "status": "request_failed", "error": type(e).__name__}


def discover(prop, session):
    """Bing public RSS discovery. If unavailable, keep seeds and report discovery errors."""
    outcome = []
    errors = []
    queries = []
    variants = prop.get("aliases", [prop["project"]])
    for site in ("101evler.com", "hangiev.com"):
        queries.append(f'site:{site} "{variants[0]}" {prop["beds"]}+1 satilik')
    for query in queries:
        try:
            r = session.get("https://www.bing.com/search", params={"q": query, "format": "rss"},
                            timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0 (compatible; PrimeKibrisResearch/0.1)"})
            r.raise_for_status()
            xml = ET.fromstring(r.content)
            hits = 0
            for item in xml.findall(".//item"):
                link = item.findtext("link", "")
                clean = canonical_url(link)
                if clean and clean not in outcome:
                    outcome.append(clean)
                    hits += 1
            if not xml.findall(".//channel"):
                errors.append({"query": query, "error": "invalid_rss"})
        except (requests.RequestException, ET.ParseError) as e:
            errors.append({"query": query, "error": type(e).__name__})
        time.sleep(SLEEP)
    return outcome[:16], errors


def run(catalog, state_path, out, live=True):
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    had_previous = bool(previous.get("checked_at"))
    fetcher = Fetcher()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "mode": "live" if live else "fixture",
              "had_previous": had_previous, "properties": [], "alerts": []}
    next_state = {"checked_at": report["checked_at"], "listings": dict(previous.get("listings", {}))}
    for prop in catalog["properties"]:
        urls = list(prop.get("seed_urls", []))
        discovery_errors = []
        if live:
            found, discovery_errors = discover(prop, fetcher.session)
            urls.extend(found)
        seen = set()
        results = []
        for raw_url in urls:
            url = canonical_url(raw_url)
            if not url or url in seen:
                continue
            seen.add(url)
            obj = fetcher.get_listing(url) if live else {"url": url, "status": "not_checked"}
            if obj["status"] in ("ok", "unverified_html"):
                category, score, reasons = classify(prop, obj)
                obj.update(category=category, match_score=score, match_reasons=reasons)
                if category != "unrelated":
                    baseline = previous.get("listings", {}).get(f'{prop["ref"]}|{url}', {})
                    old = baseline.get("price_gbp")
                    new = obj.get("price_gbp")
                    if had_previous and old and new and old != new:
                        report["alerts"].append({"ref": prop["ref"], "type": "price_change",
                          "old": old, "new": new, "url": url, "category": category})
                    elif had_previous and not baseline and new:
                        report["alerts"].append({"ref": prop["ref"], "type": "new_competitor",
                          "new": new, "url": url, "category": category})
                    if obj["status"] == "ok":
                        next_state["listings"][f'{prop["ref"]}|{url}'] = {
                            "price_gbp": new, "last_seen": report["checked_at"], "category": category}
            results.append(obj)
            if live:
                time.sleep(SLEEP)
        report["properties"].append({"ref": prop["ref"], "name": prop["name"],
            "our_price_gbp": prop["our_price_gbp"],
            "our_known_total_gbp": prop["our_price_gbp"] + prop["our_extra_gbp"],
            "competitors": results, "discovery_errors": discovery_errors})
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "report.md").write_text(render_md(report))
    (out / "state.json").write_text(json.dumps(next_state, ensure_ascii=False, indent=2) + "\n")
    return report


def render_md(report):
    lines = [f'# Prime Kıbrıs Rakip Radar — {report["checked_at"]}', "",
             "İlk tarama referans oluşturur; takip eden çalışmalarda fiyat değişimleri raporlanır.",
             "Eşleşme yalnızca adaydır; aynı konut tespiti için fotoğraf/birim numarası kontrolü gerekir.", ""]
    for p in report["properties"]:
        lines.extend([f'## {p["name"]} ({p["ref"]})',
            f'Bizim ilan £{p["our_price_gbp"]:,} · bilinen ek ücretlerle £{p["our_known_total_gbp"]:,}', ""])
        for x in p["competitors"]:
            if x["status"] not in ("ok", "unverified_html"):
                lines.append(f'- Erişim: {x["status"]} — {x["url"]}')
            elif x.get("category") == "unrelated":
                continue
            else:
                price = f'£{x["price_gbp"]:,}' if x.get("price_gbp") else "fiyat doğrulanamadı"
                lines.append(f'- {x["category"]} ({x["match_score"]}/99): {price} — {x["url"]}')
        if p["discovery_errors"]:
            lines.append(f'- Arama erişim hatası: {len(p["discovery_errors"])} sorgu; rakip yok anlamına gelmez.')
        lines.append("")
    lines.append("## Değişiklikler")
    if not report["alerts"]:
        lines.append("İlk tarama veya doğrulanmış değişiklik yok.")
    for a in report["alerts"]:
        lines.append(f'- {a["ref"]}: {a["type"]} {a.get("old", "")} → {a.get("new", "")} — {a["url"]}')
    return "\n".join(lines) + "\n"


def telegram(report):
    if not report["alerts"]:
        return
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram secrets not configured; report artifact still available")
        return
    lines = ["🏘 PRIME KIBRIS | RAKIP RADAR", ""]
    for a in report["alerts"][:12]:
        lines.append(f'{a["ref"]} {a["type"]}: £{a.get("old", 0):,} → £{a.get("new", 0):,}\n{a["url"]}')
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": "\n\n".join(lines)[:4000],
                  "disable_web_page_preview": "true"}, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"Telegram delivery failed: {type(e).__name__}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=HERE / "listings.json")
    parser.add_argument("--state", type=Path, default=Path("competitor_radar_state.json"))
    parser.add_argument("--out", type=Path, default=Path("competitor-radar-report"))
    parser.add_argument("--dry-run", action="store_true", help="No outbound requests; structural test only")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    result = run(catalog, args.state, args.out, live=not args.dry_run)
    if not args.dry_run:
        telegram(result)
    print(json.dumps({"properties": len(result["properties"]),
                      "alerts": len(result["alerts"]), "report": str(args.out / "report.md")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
