import unittest

from buyer_intent_core import classify_candidate


class BuyerIntentCoreTests(unittest.TestCase):
    def test_accepts_direct_purchase(self):
        lead, reason = classify_candidate({
            "source": "test",
            "text": "I am looking to buy an apartment abroad. My budget is €120,000 and I want a payment plan.",
        })
        self.assertEqual(reason, "accepted")
        self.assertEqual(lead["classification"], "HOT")

    def test_rejects_rental(self):
        lead, reason = classify_candidate({
            "source": "test",
            "text": "I am looking to rent an apartment abroad for 6 months.",
        })
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_rejects_agent(self):
        lead, reason = classify_candidate({
            "source": "test",
            "text": "Real estate agent here. Contact me for apartments for sale.",
        })
        self.assertIsNone(lead)
        self.assertEqual(reason, "seller_or_agent")

    def test_accepts_non_english_purchase(self):
        lead, reason = classify_candidate({
            "source": "test",
            "text": "Ich möchte eine Wohnung im Ausland kaufen. Budget €150000.",
        })
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)


if __name__ == "__main__":
    unittest.main()
