import unittest
from datetime import datetime, timedelta, timezone

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



    def test_feed_date_recent_guard(self):
        fresh = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        self.assertTrue(miner._recent_enough(fresh))
        self.assertFalse(miner._recent_enough(old))

    def test_free_discovery_combines_reddit_and_bing_without_serper(self):
        old_rss = miner._reddit_rss_rows
        old_bing = miner._bing_rss
        try:
            miner._reddit_rss_rows = lambda label, url: [{
                "title": "Buying property in North Cyprus",
                "snippet": "I am planning to buy an apartment.",
                "link": "https://www.reddit.com/r/NorthCyprus/comments/abc123/test/",
                "_query": label,
                "_source": "Reddit Native RSS",
            }]
            miner._bing_rss = lambda query: [{
                "title": "Can foreigners buy property in North Cyprus?",
                "snippet": "Researching title deeds.",
                "link": "https://www.reddit.com/r/NorthCyprus/comments/def456/test/",
                "_query": query,
                "_source": "Bing RSS",
            }]
            rows = miner._free_discovery_rows(["one query"])
            self.assertGreaterEqual(len(rows), len(miner.REDDIT_RSS_FEEDS) + 1)
            self.assertTrue(any(r.get("_source") == "Reddit Native RSS" for r in rows))
            self.assertTrue(any(r.get("_source") == "Bing RSS" for r in rows))
        finally:
            miner._reddit_rss_rows = old_rss
            miner._bing_rss = old_bing

if __name__ == "__main__":
    unittest.main()
