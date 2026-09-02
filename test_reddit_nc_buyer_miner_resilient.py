import unittest

import reddit_nc_buyer_miner_resilient as miner


class RedditIndexFallbackTests(unittest.TestCase):
    def row(self, title, snippet="", link="https://www.reddit.com/r/NorthCyprus/comments/abc123/example/"):
        return {"title": title, "snippet": snippet, "link": link}

    def test_accepts_direct_buyer_title(self):
        signal, reason = miner.classify_index_result(
            self.row(
                "Buying property in North Cyprus : r/NorthCyprus",
                "I am planning to buy a 2+1 apartment and my budget is £150000.",
            ),
            'site:reddit.com/r/NorthCyprus "buying property"',
        )
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["buyer_stage"], "DIRECT")
        self.assertEqual(signal["classification"], "HOT")

    def test_accepts_research_title(self):
        signal, reason = miner.classify_index_result(
            self.row(
                "Can foreigners buy property safely in North Cyprus? : r/NorthCyprus",
                "Trying to understand title deeds before making a decision.",
            ),
            'site:reddit.com/r/NorthCyprus "safe to buy"',
        )
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["buyer_stage"], "RESEARCH")
        self.assertEqual(signal["classification"], "WARM")

    def test_rejects_snippet_only_buyer_due_serper_related_text_risk(self):
        signal, reason = miner.classify_index_result(
            self.row(
                "Life in North Cyprus : r/NorthCyprus",
                "Related post: I want to buy an apartment in Iskele with a £120000 budget.",
            ),
            'site:reddit.com/r/NorthCyprus property',
        )
        self.assertIsNone(signal)
        self.assertEqual(reason, "title_not_buyer_topic")

    def test_rejects_rental(self):
        signal, reason = miner.classify_index_result(
            self.row(
                "Looking to buy or rent in North Cyprus? : r/NorthCyprus",
                "Actually looking to rent only, £700 per month.",
            ),
            'site:reddit.com/r/NorthCyprus property',
        )
        self.assertIsNone(signal)
        self.assertEqual(reason, "rental")

    def test_rejects_non_reddit_thread(self):
        signal, reason = miner.classify_index_result(
            self.row(
                "Buying property in North Cyprus",
                "I want to buy.",
                link="https://example.com/article",
            ),
            "North Cyprus buying property",
        )
        self.assertIsNone(signal)
        self.assertEqual(reason, "not_reddit_thread")


if __name__ == "__main__":
    unittest.main()
