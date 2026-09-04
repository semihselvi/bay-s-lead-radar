import unittest

import nc_v5_diagnostic_runner_quality as v5_quality
import reddit_nc_buyer_miner_resilient_quality as reddit_quality


class ReviewedFalsePositiveTests(unittest.TestCase):
    def test_rejects_one_day_rental_from_buyer_qualification_lane(self):
        lead = {
            "market": "north_cyprus",
            "message": "Ищу дом с бассейном на 1 день Искеле Лонг бич",
            "author": "@vikaaadz",
            "seller_matches": [],
            "telegram_score": 40,
            "classification": "REVIEW",
        }
        self.assertIsNone(v5_quality.radar.refine_telegram_v55(lead))

    def test_rejects_virtual_property_buttcoin(self):
        row = {
            "link": "https://www.reddit.com/r/Buttcoin/comments/1w4wcxz/buy_virtual_property/?tl=de",
            "title": "virtuelle Immobilie kaufen : r/Buttcoin",
            "snippet": "virtuelle Immobilie kaufen. Ich hänge gerade in der U-Bahn rum.",
        }
        signal, reason = reddit_quality.classify_index_result_quality(
            row,
            'site:reddit.com Nordzypern ("Immobilie kaufen" OR "Wohnung kaufen")',
        )
        self.assertIsNone(signal)
        self.assertIn(reason, {"blocked_nonbuyer_subreddit", "virtual_or_crypto_property"})

    def test_rejects_sarcastic_ad_subreddit(self):
        row = {
            "link": "https://www.reddit.com/r/beschissene_Werbungen/comments/1vtkti9/ja_doch_da_wuerde_ich_auf_jeden_fall_eine/",
            "title": "Ja, doch, da würde ich auf jeden Fall eine Immobilie kaufen - Reddit",
            "snippet": "Kind möchte Eltern gerne eine Immobilie kaufen für den Lebensabend, aber ... Nordzypern kaufen.",
        }
        signal, reason = reddit_quality.classify_index_result_quality(
            row,
            'site:reddit.com Nordzypern ("Immobilie kaufen" OR "Wohnung kaufen")',
        )
        self.assertIsNone(signal)
        self.assertEqual(reason, "blocked_nonbuyer_subreddit")

    def test_query_cannot_create_north_context(self):
        row = {
            "link": "https://www.reddit.com/r/germany/comments/example/immobilie_kaufen/",
            "title": "Immobilie kaufen",
            "snippet": "Ich möchte eine Wohnung in Berlin kaufen.",
        }
        signal, reason = reddit_quality.classify_index_result_quality(
            row,
            'site:reddit.com Nordzypern ("Immobilie kaufen" OR "Wohnung kaufen")',
        )
        self.assertIsNone(signal)
        self.assertEqual(reason, "no_north_context")

    def test_real_north_cyprus_research_still_passes(self):
        row = {
            "link": "https://www.reddit.com/r/NorthCyprus/comments/example/title_deed/",
            "title": "Title deed when buying property in North Cyprus",
            "snippet": "I am considering buying an apartment in North Cyprus and want to understand title deeds.",
        }
        signal, reason = reddit_quality.classify_index_result_quality(
            row,
            'site:reddit.com/r/NorthCyprus "buying property"',
        )
        self.assertIsNotNone(signal, reason)
        self.assertIn(signal.get("buyer_stage"), {"DIRECT", "RESEARCH"})


if __name__ == "__main__":
    unittest.main()
