import unittest

import russian_public_buyer_radar as r


def item(text, url="https://vk.com/wall-1_1"):
    return {
        "title": text,
        "text": "",
        "url": url,
        "platform": r.platform_from_url(url),
        "source": "test",
    }


class RussianPublicBuyerRadarTests(unittest.TestCase):
    def assertAccepted(self, text):
        lead, reason = r.classify_candidate(item(text))
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])
        return lead

    def assertRejected(self, text, reason):
        lead, got = r.classify_candidate(item(text))
        self.assertIsNone(lead)
        self.assertEqual(reason, got)

    def test_explicit_buyer(self):
        lead = self.assertAccepted(
            "Я хочу купить квартиру на Северном Кипре, бюджет 120 000 евро. Подскажите район."
        )
        self.assertEqual("HOT", lead["classification"])

    def test_planning_buyer(self):
        self.assertAccepted(
            "Мы планируем купить виллу в Гирне в следующем месяце. Что посоветуете?"
        )

    def test_investor_buyer(self):
        self.assertAccepted(
            "Я рассматриваю покупку квартиры в Искеле для инвестиций. Бюджет €150000."
        )

    def test_tenant_rejected(self):
        self.assertRejected(
            "Ищу квартиру на Северном Кипре, хочу снять на год.",
            "tenant",
        )

    def test_seller_rejected(self):
        self.assertRejected(
            "Продаю квартиру на Северном Кипре. Отличная цена, пишите в лс.",
            "seller_or_listing",
        )

    def test_agent_rejected(self):
        self.assertRejected(
            "Агентство недвижимости Северного Кипра предлагает квартиры. Свяжитесь с нами.",
            "provider_or_agent",
        )

    def test_completed_buyer_rejected(self):
        self.assertRejected(
            "Я уже купил квартиру на Северном Кипре и теперь делюсь опытом.",
            "completed_or_cancelled",
        )

    def test_generic_article_rejected(self):
        self.assertRejected(
            "Недвижимость Северного Кипра: обзор рынка и цены на квартиры.",
            "no_explicit_purchase_intent",
        )

    def test_south_cyprus_not_accepted(self):
        self.assertRejected(
            "Я хочу купить квартиру в Лимассоле на Кипре.",
            "no_north_cyprus_context",
        )

    def test_no_property_rejected(self):
        self.assertRejected(
            "Я хочу купить автомобиль на Северном Кипре.",
            "no_property",
        )


if __name__ == "__main__":
    unittest.main()
