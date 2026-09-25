import unittest

import russian_public_buyer_radar as ru


class RussianPublicBuyerRadarTests(unittest.TestCase):
    def item(self, text, url="https://vk.com/wall-1_1"):
        return {"title": "", "text": text, "url": url, "published": "", "author": ""}

    def test_accepts_explicit_buyer(self):
        lead, reason = ru.classify_item(
            self.item("Северный Кипр, хочу купить квартиру в Искеле. Бюджет 120000 евро. Что посоветуете?")
        )
        self.assertIsNotNone(lead, reason)
        self.assertIn(lead["intent_type"], {"BUYER", "INVESTOR"})

    def test_rejects_rental_only(self):
        lead, reason = ru.classify_item(
            self.item("Северный Кипр. Ищу квартиру в аренду в Искеле на 6 месяцев.")
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental_only")

    def test_rejects_seller(self):
        lead, reason = ru.classify_item(
            self.item("Северный Кипр. Продаю квартиру в Искеле, пишите в личку.")
        )
        self.assertIsNone(lead)

    def test_rejects_without_north_cyprus(self):
        lead, reason = ru.classify_item(
            self.item("Хочу купить квартиру в Москве, бюджет 150000 евро.")
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_north_cyprus_context")

    def test_accepts_research_with_purchase_intent(self):
        lead, reason = ru.classify_item(
            self.item("Северный Кипр: стоит ли покупать недвижимость в Гирне для инвестиции?")
        )
        self.assertIsNotNone(lead, reason)


if __name__ == "__main__":
    unittest.main()
