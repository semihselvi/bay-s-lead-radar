import unittest

import europe_home_buyer_radar as radar


class EuropeHomeBuyerRadarTests(unittest.TestCase):
    def item(self, text, query="", url="https://www.reddit.com/r/example/comments/abc"):
        return {"source":"Test","url":url,"title":"User discussion","text":text,"published":"","author":"user","discovery_query":query}

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


if __name__ == "__main__":
    unittest.main()
