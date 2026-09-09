import unittest

import nc_v5_diagnostic_runner_quality as v5_quality
import nc_v5_batch_quality_guard as batch_guard
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

    def test_rejects_robot_vacuum_request_despite_apartment_context(self):
        lead = {
            "market": "north_cyprus",
            "message": (
                "Здравствуйте! Может кто-нибудь ещё продаёт робот-пылесос- моющий? "
                "Геолокация Искеле-Фамагуста. Интересует для большой квартиры. В пределах 150 евро"
            ),
            "author": "Farida Hafiye",
            "group": "СЕВЕРНЫЙ КИПР | БАРАХОЛКА",
            "seller_matches": [],
            "telegram_score": 52,
            "classification": "REVIEW",
        }
        self.assertTrue(batch_guard.is_nonproperty_goods_request(lead["message"]))
        self.assertIsNone(v5_quality.radar.refine_telegram_v55(lead))

    def test_rejects_school_uniform_purchase_even_when_doma_appears(self):
        lead = {
            "market": "north_cyprus",
            "message": (
                "Куплю школьную форму şht Ertugrul ilkokulu Lefkoşa, для сына, "
                "6,7 лет, у кого завалялась дома"
            ),
            "author": "Ay Us",
            "group": "СЕВЕРНЫЙ КИПР | ФОРУМ",
            "seller_matches": [],
            "telegram_score": 58,
            "classification": "WARM",
        }
        self.assertTrue(batch_guard.is_nonproperty_goods_request(lead["message"]))
        self.assertIsNone(v5_quality.radar.refine_telegram_v55(lead))

    def test_real_property_buyer_still_passes_goods_guard(self):
        lead = {
            "market": "north_cyprus",
            "message": (
                "Куплю от собственника 1+1 или 2+1 в Royal Sun или Royal Sun Elite. "
                "Этаж только граунд! Либо выше, но с лифтом."
            ),
            "author": "@des_okk",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "seller_matches": [],
            "telegram_score": 85,
            "classification": "HOT",
        }
        self.assertFalse(batch_guard.is_nonproperty_goods_request(lead["message"]))
        result = v5_quality.radar.refine_telegram_v55(lead)
        self.assertIsNotNone(result)
        self.assertIn(result.get("classification"), {"HOT", "WARM"})

    def test_purchase_only_rejects_exact_long_term_tenant(self):
        lead = {
            "market": "north_cyprus",
            "message": "Сниму 2+1, 3+1, на долгосрок, Алсанжак/Лапта. Семья 3 чел. От собственника",
            "author": "@Queen77777777777777",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "seller_matches": [],
            "telegram_score": 85,
            "classification": "HOT",
        }
        self.assertIsNone(v5_quality.purchase_only_lead(lead))

    def test_purchase_only_rejects_shared_rental_ambiguity(self):
        lead = {
            "market": "north_cyprus",
            "message": "Ищем на подселение в комнату ,квартира в Гирне",
            "author": "@krzhuby",
            "group": "СЕВЕРНЫЙ КИПР | ФОРУМ",
            "seller_matches": [],
            "telegram_score": 68,
            "classification": "WARM",
        }
        self.assertIsNone(v5_quality.purchase_only_lead(lead))

    def test_purchase_only_keeps_real_property_buyer(self):
        lead = {
            "market": "north_cyprus",
            "message": "Куплю 2+1 в Искеле. Бюджет £120000. Тапу обязательно.",
            "author": "@real_buyer",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "seller_matches": [],
            "telegram_score": 85,
            "classification": "HOT",
        }
        result = v5_quality.purchase_only_lead(lead)
        self.assertIsNotNone(result)
        self.assertIn(result.get("classification"), {"HOT", "WARM"})

    def test_cross_group_semantic_duplicate_for_same_person(self):
        batch_guard._SEMANTIC_SEEN.clear()
        first = {
            "author": "Ay Us",
            "message": "Куплю школьную форму şht ertugrul ilkokulu Lefkoşa для сына 6,7 лет у кого дома завалялась",
        }
        second = {
            "author": "Ay Us",
            "message": "Куплю школьную форму şht Ertugrul ilkokulu Lefkoşa, для сына, 6,7 лет, у кого завалялась дома",
        }
        self.assertFalse(batch_guard.semantic_cross_group_duplicate(first))
        self.assertTrue(batch_guard.semantic_cross_group_duplicate(second))

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
