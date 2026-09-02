import unittest

import reddit_nc_buyer_miner as miner


class RedditNorthCyprusBuyerMinerTests(unittest.TestCase):
    TITLE = "Buying property in North Cyprus"
    CONTEXT = "Foreign buyers discuss title deeds, locations and purchasing property in North Cyprus."

    def classify(self, body, title=None, context=None):
        return miner.classify_comment(
            body,
            self.TITLE if title is None else title,
            self.CONTEXT if context is None else context,
        )

    def test_accepts_direct_buyer_with_budget(self):
        lead, reason = self.classify(
            "I am thinking about buying a 1+1 apartment in Iskele. My budget is £120000 and I want to understand the title deed first."
        )
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertEqual(lead["buyer_stage"], "DIRECT")

    def test_accepts_research_stage_comment_in_old_buyer_thread(self):
        lead, reason = self.classify(
            "I was looking into it recently. What title deed should a foreign buyer check before buying an apartment?"
        )
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "WARM")
        self.assertEqual(lead["buyer_stage"], "RESEARCH")

    def test_accepts_family_member_purchase_intent(self):
        lead, _ = self.classify(
            "My father-in-law wants to buy an apartment and is trying to understand which title deed is safest."
        )
        self.assertIsNotNone(lead)
        self.assertEqual(lead["buyer_stage"], "DIRECT")

    def test_rejects_agent_pitch(self):
        lead, reason = self.classify(
            "I work in real estate in North Cyprus. DM me and I can show you our properties."
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "seller_or_agent")

    def test_rejects_rental_only(self):
        lead, reason = self.classify(
            "I am looking to rent a studio in Iskele for £500 per month."
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental")

    def test_rejects_past_owner_without_new_purchase(self):
        lead, reason = self.classify(
            "I bought an apartment in Kyrenia five years ago and already have my title deed."
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "past_owner")

    def test_rejects_generic_opinion(self):
        lead, reason = self.classify(
            "I think the whole market is risky and people should be careful."
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_buyer_intent")

    def test_rejects_non_north_cyprus_thread(self):
        lead, reason = self.classify(
            "I am planning to buy an apartment with a £200000 budget.",
            title="Buying an apartment in Spain",
            context="Property discussion about Spain and Portugal.",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_north_context")

    def test_extracts_reddit_thread_id(self):
        self.assertEqual(
            miner.extract_thread_id("https://www.reddit.com/r/NorthCyprus/comments/1k04v1u/buying_property_in_trnc/"),
            "1k04v1u",
        )
        self.assertEqual(miner.extract_thread_id("https://redd.it/1cegsun"), "1cegsun")


if __name__ == "__main__":
    unittest.main()
