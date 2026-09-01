import unittest

import europe_abroad_buyer_radar as radar


class AbroadBuyerRadarTests(unittest.TestCase):
    def item(self, text, query, url="https://www.reddit.com/r/example/comments/abc/post"):
        return {
            "source": "Test",
            "url": url,
            "title": "User discussion",
            "text": text,
            "published": "",
            "author": "user",
            "discovery_query": query,
        }

    def test_germany_explicit_resident_hot(self):
        lead, reason = radar.classify("germany_abroad", self.item(
            "Ich wohne in Deutschland und möchte eine Wohnung in Nordzypern kaufen. Budget €220000.",
            'Deutschland "Nordzypern" "ich möchte kaufen"',
        ))
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertEqual(lead["target_market"], "north_cyprus")

    def test_germany_context_bridge_warm(self):
        lead, reason = radar.classify("germany_abroad", self.item(
            "Ich möchte eine Ferienwohnung in Spanien kaufen und habe ein Budget von €180000.",
            'Deutschland "wir wollen" "Ferienwohnung im Ausland kaufen"',
            url="https://www.wertpapier-forum.de/topic/123-auslandsimmobilie/",
        ))
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "WARM")
        self.assertEqual(lead["target_market"], "spain")
        self.assertFalse(lead["audience_explicit"])

    def test_rejects_rental(self):
        lead, reason = radar.classify("netherlands_abroad", self.item(
            "Ik woon in Nederland en zoek een appartement in Spanje om te huren per maand.",
            'Nederland "huis in het buitenland kopen"',
        ))
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_rejects_seller(self):
        lead, reason = radar.classify("belgium_abroad", self.item(
            "Villa in Portugal for sale. Real estate agent, contact us on WhatsApp.",
            'Belgium "buy property abroad"',
        ))
        self.assertIsNone(lead)
        self.assertEqual(reason, "seller")

    def test_switzerland_explicit_resident(self):
        lead, _ = radar.classify("switzerland_abroad", self.item(
            "Ich wohne in der Schweiz und möchte ein Haus in Portugal kaufen. Eigenkapital CHF 250000.",
            'Schweiz "Immobilie im Ausland kaufen"',
        ))
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertEqual(lead["target_market"], "portugal")

    def test_golden_visa_hot(self):
        lead, reason = radar.classify("golden_visa", self.item(
            "I am considering a golden visa and my budget is €500000. Which country has the best property route?",
            '"golden visa" "which country" investor forum',
        ))
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")


if __name__ == "__main__":
    unittest.main()
