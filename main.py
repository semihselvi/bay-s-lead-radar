import requests
from bs4 import BeautifulSoup

URL = "https://www.reddit.com/search.rss"

HEADERS = {
    "User-Agent": "BAY-S-Lead-Radar/1.0 (buyer research)"
}

QUERY = '"looking to buy" property'


def main():
    print("BAY-S LEAD RADAR TEST")
    print("Query:", QUERY)

    response = requests.get(
        URL,
        params={
            "q": QUERY,
            "sort": "new",
            "t": "day",
            "limit": 10,
        },
        headers=HEADERS,
        timeout=15,
    )

    print("HTTP STATUS:", response.status_code)

    if response.status_code != 200:
        print("REDDIT RESPONSE:")
        print(response.text[:1000])
        raise SystemExit(1)

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    entries = soup.find_all("entry")

    print("RESULT COUNT:", len(entries))

    for entry in entries[:10]:
        title = entry.find("title")
        link = entry.find("link")

        print()
        print("TITLE:", title.get_text(" ", strip=True) if title else "")
        print("URL:", link.get("href", "") if link else "")


if __name__ == "__main__":
    main()
