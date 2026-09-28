import unittest

import youtube_nc_buyer_radar as y


class YouTubeNCBuyerRadarTests(unittest.TestCase):
    def test_price_question_is_warm(self):
        lead, reason = y.classify_comment("How much is this apartment? Can you send more details?")
        self.assertIsNotNone(lead, reason)
        self.assertEqual(lead["intent_type"], "BUYER")

    def test_payment_plan_is_hot(self):
        lead, reason = y.classify_comment("I'm interested. What is the deposit and payment plan?")
        self.assertIsNotNone(lead, reason)
        self.assertEqual(lead["classification"], "HOT")

    def test_generic_praise_rejected(self):
        lead, reason = y.classify_comment("Great video!")
        self.assertIsNone(lead)
        self.assertEqual(reason, "praise_only")

    def test_provider_rejected(self):
        lead, reason = y.classify_comment("I am an agent, contact me on WhatsApp for our projects")
        self.assertIsNone(lead)
        self.assertEqual(reason, "provider")

    def test_rental_only_rejected(self):
        lead, reason = y.classify_comment("How much is the monthly rent?")
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_relative_age(self):
        self.assertEqual(y.parse_comment_age("2 days ago"), 2)
        self.assertEqual(y.parse_comment_age("3 weeks ago"), 21)
        self.assertEqual(y.parse_comment_age("2 months ago"), 60)


if __name__ == "__main__":
    unittest.main()
