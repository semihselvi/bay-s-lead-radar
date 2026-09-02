import unittest

import main_v5_5 as radar


class V55RealSignalTests(unittest.TestCase):
    def lead(self, message: str, author: str = "@real_buyer"):
        return {
            "market": "north_cyprus",
            "message": message,
            "author": author,
            "seller_matches": [],
            "telegram_score": 40,
            "classification": "REVIEW",
        }

    def test_accepts_real_reddit_planning_on_buying(self):
        item = {
            "source": "Serper",
            "url": "https://www.reddit.com/r/NorthCyprus/comments/example/",
            "title": "Buying property in North Cyprus.",
            "text": "Hello, im planning on buying two properties for around 700-800k euros. I will buy them to rent them out.",
            "published": "",
            "author": "",
            "_search_query": "North Cyprus looking to buy property apartment villa budget",
        }
        result = radar.classify_web_v55(item)
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")

    def test_accepts_family_member_northern_cyprus_buyer_with_truncated_title(self):
        item = {
            "source": "Serper",
            "url": "https://www.reddit.com/r/cyprus/comments/example/",
            "title": "My father-in-law wants to buy an apartement in northern ...",
            "text": "Could you help me please?",
            "published": "",
            "author": "",
            "_search_query": "Northern Cyprus moving buying home property expat",
        }
        result = radar.classify_web_v55(item)
        self.assertIsNotNone(result)
        self.assertTrue(result.get("north_context_bridge"))

    def test_accepts_title_deed_terse_buyer_without_budget(self):
        message = (
            "Ищу квартиру 2+1 в İskele Long Beach. "
            "Тапу должен быть уже оформлен на имя собственника. "
            "Предложения отправляйте в личные сообщения."
        )
        result = radar.refine_telegram_v55(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "WARM")
        self.assertEqual(result["buyer_signal"], "purchase_qualified_demand")

    def test_accepts_human_need_word_buyer(self):
        message = (
            "Нужна квартира 2+1 в Искеле для покупки. Бюджет £120000. "
            "Рассмотрю варианты с готовым тапу."
        )
        result = radar.refine_telegram_v55(self.lead(message, author="@anna_buy"))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")

    def test_rejects_short_stay_request(self):
        message = (
            "Ищу квартиру на северном Кипре Искале-боаз 2+1. "
            "Планируется проживание 2х семей с 6 по 12 сентября. Недалеко от моря."
        )
        self.assertIsNone(radar.refine_telegram_v55(self.lead(message)))

    def test_rejects_low_budget_tomorrow_request(self):
        message = "Ищу квартиру на завтра с утра в Искеле до 30€."
        self.assertIsNone(radar.refine_telegram_v55(self.lead(message)))

    def test_rejects_ambiguous_flat_request_without_purchase_signal(self):
        message = "Ищу квартиру рассмотрю варианты. Личка."
        self.assertIsNone(radar.refine_telegram_v55(self.lead(message)))

    def test_rejects_pulsemarket_seller_bot_false_positive(self):
        message = (
            "🆕 НОВОЕ ОБЪЯВЛЕНИЕ НА PulseMarket! 🏠 СРОЧНАЯ ПРОДАЖА ВИЛЛЫ 3+1 В ЭСЕНТЕПЕ "
            "💰 Цена: 360000 £ 📍 Локация: Эсентепе 👤 Контакт: @Guzel_lezug "
            "Клиенту очень срочно нужно продать виллу. 3 года назад клиент приобрёл её у застройщика. "
            "Больше фотографий доступно при публикации в группе. Смотреть на сайте. "
            "Хотите получать новые объявления моментально? Подключить Алерты! #недвижимость #PulseMarket"
        )
        self.assertIsNone(
            radar.refine_telegram_v55(self.lead(message, author="@ScrapYs_bot"))
        )

    def test_rejects_same_seller_ad_even_from_human_account(self):
        message = (
            "СРОЧНАЯ ПРОДАЖА ВИЛЛЫ 3+1 В ЭСЕНТЕПЕ. Цена: 360000 £. "
            "Клиенту очень срочно нужно продать виллу. Контакт в личку."
        )
        self.assertIsNone(
            radar.refine_telegram_v55(self.lead(message, author="@property_admin"))
        )

    def test_rejects_bot_author_even_if_text_looks_like_buyer(self):
        message = "Ищу квартиру 2+1 в Искеле для покупки. Бюджет £120000. Тапу обязательно."
        self.assertIsNone(
            radar.refine_telegram_v55(self.lead(message, author="@AutoBuyer_bot"))
        )


if __name__ == "__main__":
    unittest.main()
