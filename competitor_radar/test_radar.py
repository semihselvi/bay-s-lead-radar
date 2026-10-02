import unittest
from competitor_radar.radar import canonical_url, classify, extract_page, gbp_number


class RadarTests(unittest.TestCase):
    def test_allowlist(self):
        self.assertIsNone(canonical_url("http://127.0.0.1/admin"))
        self.assertIsNone(canonical_url("https://other.com/101evler"))
        self.assertEqual(canonical_url("https://www.101evler.com/a?ref=ad"), "https://www.101evler.com/a")

    def test_price_numbers(self):
        self.assertEqual(gbp_number("£85,000"), 85000)
        self.assertEqual(gbp_number("195.000"), 195000)
        self.assertIsNone(gbp_number("250"))

    def test_extract(self):
        html = '<html><head><title>Caesar Resort 5 2+1 90 m²</title><script type="application/ld+json">{"@type":"Apartment","offers":{"price":80000,"priceCurrency":"GBP"},"floorSize":{"value":90}}</script></head><body><main><h1>Caesar Resort 5 2+1</h1>£80,000</main></body></html>'
        result = extract_page(html, "https://www.101evler.com/test")
        self.assertEqual(result["price_gbp"], 80000)
        self.assertEqual(result["area_m2"], 90)

    def test_no_certainty(self):
        prop = {"aliases": ["Caesar Resort 5"], "beds": 2, "area_m2": 76,
                "extra_area_m2": 16, "floor": 3}
        result = classify(prop, {"title": "Caesar Resort 5 2+1 76 m² 3 kat",
                                 "snippet": "", "area_m2": 76})
        self.assertEqual(result[0], "possible_same_needs_photos")
        self.assertLess(result[1], 100)
        self.assertEqual(classify(prop, {"title": "VOLNA 2+1", "snippet": "", "area_m2": 76})[0], "unrelated")


if __name__ == "__main__":
    unittest.main()
