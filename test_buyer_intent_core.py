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

    def test_rejects_generic_investing_back_home(self):
        lead, reason = classify_candidate({
            "source": "Reddit Comment RSS",
            "text": "I learned investing to prepare for the future. I tell people to build something either here or back home, like a degree, business or investing.",
        })
        self.assertIsNone(lead)
        self.assertIn(reason, {"no_property", "generic_investing", "no_explicit_purchase_intent"})

    def test_rejects_reddit_relocation_advice_false_positive(self):
        lead, reason = classify_candidate({
            "source": "Reddit Comment RSS",
            "title": "Employer cancelled my Netherlands relocation",
            "text": "Save yourself the hustle, even selling everything it’s better to go back home",
            "url": "https://www.reddit.com/r/expats/comments/example/comment/",
        })
        self.assertIsNone(lead)
        self.assertEqual(reason, "reddit_no_purchase_verb")

    def test_reddit_comment_still_accepts_explicit_property_purchase(self):
        lead, reason = classify_candidate({
            "source": "Reddit Comment RSS",
            "title": "Moving abroad",
            "text": "I want to buy an apartment abroad and my budget is €150,000.",
        })
        self.assertIsNotNone(lead)
        self.assertEqual(reason, "accepted")

    def test_accepts_non_english_purchase(self):
        lead, reason = classify_candidate({
            "source": "test",
            "text": "Ich möchte eine Wohnung im Ausland kaufen. Budget €150000.",
        })
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)


if __name__ == "__main__":
    unittest.main()
