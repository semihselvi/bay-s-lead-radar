import unittest
from datetime import datetime, timezone

import europe_home_buyer_radar as radar


class EuropeHomeBuyerRadarTests(unittest.TestCase):
    def item(self, text, query="", url="https://www.reddit.com/r/example/comments/abc/post"):
        return {
            "source": "Test",
            "url": url,
            "title": "User discussion",
            "text": text,
            "published": "",
            "author": "user",
            "discovery_query": query,
        }

    def test_germany_ready_buyer(self):
        lead, reason = radar.classify("germany_home", self.item(
            "Ich suche eine Wohnung zum Kauf in Berlin. Budget €480000. Finanzierung bestätigt und Eigenkapital vorhanden."
        ))
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertEqual(lead["buyer_stage"], "READY")

    def test_netherlands_active_buyer(self):
        lead, _ = radar.classify("netherlands_home", self.item(
            "Ik zoek een huis om te kopen in Utrecht. Budget €550000 en hypotheek is besproken."
        ))
        self.assertIsNotNone(lead)
        self.assertEqual(lead["buyer_stage"], "ACTIVE")

    def test_belgium_french_buyer(self):
        lead, _ = radar.classify("belgium_home", self.item(
            "Je cherche un appartement à acheter à Bruxelles. Budget €350000 et apport disponible."
        ))
        self.assertIsNotNone(lead)
        self.assertEqual(lead["target_market"], "belgium")

    def test_switzerland_ready_buyer(self):
        lead, _ = radar.classify("switzerland_home", self.item(
            "Wir suchen eine Wohnung zum Kauf in Zürich. Eigenkapital CHF 250000 vorhanden und Hypothek bestätigt."
        ))
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")

    def test_rejects_rental(self):
        lead, reason = radar.classify("germany_home", self.item(
            "Ich suche eine Mietwohnung in Berlin für €1600 pro Monat."
        ))
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_rejects_seller(self):
        lead, reason = radar.classify("belgium_home", self.item(
            "Appartement à vendre à Bruxelles. Contact us on WhatsApp, real estate agent."
        ))
        self.assertIsNone(lead)
        self.assertEqual(reason, "seller")

    def test_rejects_wrong_destination(self):
        lead, _ = radar.classify("germany_home", self.item(
            "I live in Germany and I am looking to buy a house in Spain. Budget €300000."
        ))
        self.assertIsNone(lead)

    def test_accepts_query_context_bridge(self):
        lead, _ = radar.classify("germany_home", self.item(
            "I am looking to buy an apartment. Budget €420000.",
            query='site:reddit.com/r/germany "buy apartment" Germany'
        ))
        self.assertIsNotNone(lead)
        self.assertTrue(lead["target_context_bridge"])
        self.assertEqual(lead["classification"], "WARM")

    def test_rejects_non_user_source(self):
        lead, reason = radar.classify("germany_home", self.item(
            "I am looking to buy an apartment in Berlin.",
            url="https://www.immobilienscout24.de/expose/123"
        ))
        self.assertIsNone(lead)
        self.assertEqual(reason, "non_user_source")

    def test_reddit_post_id(self):
        self.assertEqual(
            radar.reddit_post_id(
                "https://www.reddit.com/r/askswitzerland/comments/1w468mq/looking_for_an_apartment/"
            ),
            "1w468mq",
        )

    def test_reddit_payload_replaces_contaminated_search_snippet(self):
        original = {
            "source": "Serper",
            "url": "https://www.reddit.com/r/askswitzerland/comments/1w468mq/looking_for_an_apartment_in_zurich_surrounding/",
            "title": "Looking for an apartment in Zurich / surrounding areas",
            "text": "Planning to buy House/Apartment around Zurich area · r/Switzerland. • 9mo ago.",
            "published": "7 hours ago",
            "author": "",
            "discovery_query": 'site:reddit.com/r/askswitzerland "buy house"',
        }
        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "id": "1w468mq",
                        "title": "Looking for an apartment in Zurich / surrounding areas",
                        "selftext": "I am moving to Zurich and looking to rent an apartment in the surrounding areas. My monthly rent budget is CHF 2500.",
                        "author": "actual_user",
                        "created_utc": datetime.now(timezone.utc).timestamp(),
                        "permalink": "/r/askswitzerland/comments/1w468mq/looking_for_an_apartment_in_zurich_surrounding/",
                    }
                }]
            }
        }]
        exact = radar.parse_reddit_payload(original, payload)
        self.assertIsNotNone(exact)
        self.assertTrue(exact["source_verified"])
        self.assertNotIn("Planning to buy House/Apartment", exact["text"])
        lead, reason = radar.classify("switzerland_home", exact)
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_reddit_payload_id_mismatch_is_rejected(self):
        original = self.item(
            "Looking to buy apartment in Zurich",
            url="https://www.reddit.com/r/askswitzerland/comments/1w468mq/example/",
        )
        payload = [{"data": {"children": [{"data": {
            "id": "different",
            "title": "Other post",
            "selftext": "I want to buy a house in Zurich",
        }}]}}]
        self.assertIsNone(radar.parse_reddit_payload(original, payload))

    def test_verified_reddit_buyer_still_qualifies(self):
        original = {
            "source": "Serper",
            "url": "https://www.reddit.com/r/askswitzerland/comments/abc123/buying_in_zurich/",
            "title": "Buying in Zurich",
            "text": "Search snippet",
            "published": "2 hours ago",
            "author": "",
            "discovery_query": 'site:reddit.com/r/askswitzerland "buy house"',
        }
        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "id": "abc123",
                        "title": "Buying an apartment in Zurich",
                        "selftext": "I am looking to buy an apartment in Zurich. Budget CHF 900000 and mortgage pre-approved.",
                        "author": "real_buyer",
                        "created_utc": datetime.now(timezone.utc).timestamp(),
                        "permalink": "/r/askswitzerland/comments/abc123/buying_in_zurich/",
                    }
                }]
            }
        }]
        exact = radar.parse_reddit_payload(original, payload)
        lead, reason = radar.classify("switzerland_home", exact)
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertEqual(lead["credibility_score"], 90)


if __name__ == "__main__":
    unittest.main()
