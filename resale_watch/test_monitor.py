import unittest
from unittest.mock import AsyncMock

from resale_watch.monitor import (gbp, description, parse_site, sale_message,
                                  possible_site_matches, compare)

CARD = """
<div class="listing">
  <a href="/tr/ikinci-el/caesar-blue-terra-2-1">
  <h2>Caesar Blue Terra 2+1 Daire | 5. Kat | 2. El</h2></a>
  <p>86 m²</p><p>130,000 GBP</p><p>PK-2E-000006</p>
</div>
"""


class ResaleWatchTests(unittest.TestCase):
    def test_currency_both_orders(self):
        self.assertEqual(gbp("125.000£ devir dahil"), 125000)
        self.assertEqual(gbp("£130,000"), 130000)
        self.assertEqual(gbp("160,000 GBP"), 160000)

    def test_russian_turkish_sale_posts(self):
        self.assertTrue(sale_message("Вилла 3+1, 170 кв м, 305.000£"))
        self.assertTrue(sale_message("Panorama Long Beach 1+1 68 m² 160.000£"))
        self.assertFalse(sale_message("Merhaba! Kıbrıs yatırım haberleri."))

    def test_listing_parse(self):
        item, empty = parse_site("<html><body>" + CARD + "</body></html>")
        self.assertFalse(empty)
        self.assertEqual(len(item), 1)
        self.assertEqual(item["PK-2E-000006"]["price_gbp"], 130000)
        self.assertEqual(item["PK-2E-000006"]["beds"], 2)

    def test_pagination_empty(self):
        self.assertEqual(parse_site("<h2>Sonuç bulunamadı</h2>"), ({}, True))

    def test_project_must_match(self):
        site = {"PK-2E-000006": {"ref": "PK-2E-000006",
                "title": "Caesar Blue Terra 2+1 Daire | 5. Kat | 2. El",
                "beds": 2, "area_m2": 86, "floor": 5}}
        rec = {"excerpt": "Caesar Blue Terra 2+1 5 kat 86 m2 £125,000",
               "beds": 2, "area_m2": 86, "floor": 5}
        self.assertEqual(possible_site_matches(rec, site), ["PK-2E-000006"])
        rec["excerpt"] = "Caesar Blue Iona 2+1 5 kat 86 m2 £125,000"
        self.assertEqual(possible_site_matches(rec, site), [])

    def test_no_edit_label_for_source_margin(self):
        # A commission difference is not a source-price change.
        self.assertEqual(description("2+1 5. Kat 86 m²")["beds"], 2)


class ResaleAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_deletion_requires_exact_id_lookup(self):
        old = {"checked_at": "2026-10-13", "telegram": {
            "33": {"id": 33, "link": "https://t.me/h0t_real_estate/33",
                   "hash": "abc", "excerpt": "Caesar Blue Terra 2+1 £125000",
                   "beds": 2, "area_m2": None, "floor": None,
                   "price_gbp": 125000}}, "site": {}}
        client = type("FakeClient", (), {})()
        client.get_messages = AsyncMock(return_value=[None])
        report = await compare(old, {}, {}, client, object())
        self.assertEqual(len(report["telegram_deleted_verified"]), 1)
        self.assertEqual(len(report["telegram_new"]), 0)
        client.get_messages.assert_awaited_once()

    async def test_first_baseline_never_says_new(self):
        report = await compare({}, {}, {"21": {"id": 21, "hash": "x",
              "excerpt": "Panorama 1+1 £160000", "beds": 1, "area_m2": None,
              "floor": None, "price_gbp": 160000}}, object(), object())
        self.assertEqual(report["telegram_new"], [])
        self.assertTrue(report["first_run_baseline"])

    async def test_reposted_identical_listing_is_not_new_or_deleted(self):
        old = {"checked_at": "2026-10-16T00:00:00+00:00", "telegram": {
            "12216": {"id": 12216, "link": "https://t.me/h0t_real_estate/12216",
                      "hash": "samehash", "excerpt": "Caesar Resort-1 Julius 1+1 65 кв м 7 этаж 78.000£",
                      "published": "2026-10-15T10:00:00+00:00",
                      "beds": 1, "area_m2": 65, "floor": 7, "price_gbp": 78000}
        }, "site": {}, "oct13_catchup_complete": True}
        current = {
            "17070": {"id": 17070, "link": "https://t.me/h0t_real_estate/17070",
                      "hash": "samehash", "excerpt": "Caesar Resort-1 Julius 1+1 65 кв м 7 этаж 78.000£",
                      "published": "2026-10-17T10:00:00+00:00",
                      "beds": 1, "area_m2": 65, "floor": 7, "price_gbp": 78000}
        }
        client = type("FakeClient", (), {})()
        client.get_messages = AsyncMock(return_value=[None])
        report = await compare(old, {}, current, client, object())
        self.assertEqual(report["telegram_new"], [])
        self.assertEqual(report["telegram_deleted_verified"], [])
        self.assertEqual(len(report["telegram_reposts_suppressed"]), 1)


if __name__ == "__main__":
    unittest.main()
