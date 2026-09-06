import unittest
from unittest.mock import patch

import europe_abroad_buyer_radar as base
import europe_abroad_buyer_radar_verified as verified


class VerifiedAbroadBuyerRadarTests(unittest.TestCase):
    def serper_item(self, title, text, url="https://www.reddit.com/r/CitizenshipInvestment/comments/abc123/eu_passport_malta_italy/"):
        return {
            "source": "Serper",
            "url": url,
            "title": title,
            "text": text,
            "published": "7 hours ago",
            "author": "",
            "discovery_query": 'site:reddit.com "golden visa" "looking for" property',
        }

    def test_reddit_post_id(self):
        self.assertEqual(
            verified.reddit_post_id("https://www.reddit.com/r/x/comments/AbC123/example/"),
            "abc123",
        )

    def test_reddit_listing_page_is_not_a_post(self):
        url = "https://www.reddit.com/r/ifiwonthelottery/new/"
        self.assertTrue(verified.is_reddit_url(url))
        self.assertFalse(verified.is_reddit_post(url))

    def test_reddit_listing_page_serper_snippet_is_dropped(self):
        item = self.serper_item(
            "r/ifiwonthelottery - Reddit",
            "I plan to engage with a Golden Visa program to obtain citizenship in ...",
            url="https://www.reddit.com/r/ifiwonthelottery/new/",
        )
        with patch.object(verified, "_ORIGINAL_SERPER", return_value=[item]):
            rows = verified.verified_serper_search("golden_visa", 'site:reddit.com "golden visa" "I want" investment')
        self.assertEqual(rows, [])

    def test_exact_lottery_hypothetical_is_rejected(self):
        item = self.serper_item(
            "What I would do if I won",
            "If I won the lottery, I would help my family and plan to engage with a Golden Visa program.",
            url="https://www.reddit.com/r/ifiwonthelottery/comments/abc123/my_plan/",
        )
        self.assertEqual(
            verified.hypothetical_reddit_reason(item),
            "hypothetical_lottery_subreddit",
        )

    def test_parse_reddit_payload_replaces_search_snippet(self):
        original = self.serper_item(
            "EU passport, Malta? Italy?",
            "Unrelated search snippet says Portugal golden visa is a good option.",
        )
        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "id": "abc123",
                        "title": "EU passport, Malta? Italy?",
                        "selftext": "I am comparing retirement routes but I am not asking about a golden visa.",
                        "author": "actual_user",
                        "created_utc": 1788300000,
                        "permalink": "/r/CitizenshipInvestment/comments/abc123/eu_passport_malta_italy/",
                    }
                }]
            }
        }]
        item = verified._parse_reddit_payload(original, payload)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "Reddit direct")
        self.assertEqual(item["author"], "actual_user")
        self.assertNotIn("Portugal golden visa", item["text"])
        self.assertTrue(item["source_verified"])

    def test_payload_id_mismatch_is_rejected(self):
        original = self.serper_item("Some title", "Some snippet")
        payload = [{"data": {"children": [{"data": {
            "id": "different",
            "title": "Other post",
            "selftext": "Golden visa budget 500000",
        }}]}}]
        self.assertIsNone(verified._parse_reddit_payload(original, payload))

    def test_unrelated_search_snippet_cannot_create_golden_lead_after_verification(self):
        original = self.serper_item(
            "EU passport, Malta? Italy?",
            "I want a golden visa in Portugal and my budget is €500000.",
        )
        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "id": "abc123",
                        "title": "EU passport, Malta? Italy?",
                        "selftext": "I want to retire in Europe in 5-8 years and I am comparing passport timelines.",
                        "author": "actual_user",
                        "created_utc": 1788300000,
                        "permalink": "/r/CitizenshipInvestment/comments/abc123/eu_passport_malta_italy/",
                    }
                }]
            }
        }]
        exact_item = verified._parse_reddit_payload(original, payload)
        lead, reason = base.classify("golden_visa", exact_item)
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_golden_context")

    def test_real_exact_golden_post_still_qualifies(self):
        original = self.serper_item("Golden Visa options", "Search snippet")
        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "id": "abc123",
                        "title": "Golden Visa options",
                        "selftext": "I am considering a golden visa and my investment budget is €500000. Which country should I choose?",
                        "author": "actual_user",
                        "created_utc": 1788300000,
                        "permalink": "/r/CitizenshipInvestment/comments/abc123/golden_visa_options/",
                    }
                }]
            }
        }]
        exact_item = verified._parse_reddit_payload(original, payload)
        lead, reason = base.classify("golden_visa", exact_item)
        self.assertEqual(reason, "accepted")
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")


if __name__ == "__main__":
    unittest.main()
