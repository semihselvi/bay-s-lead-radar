import unittest

import main_v5_1 as gate


class TelegramBuyerGateTests(unittest.TestCase):
    def lead(self, message: str):
        return {
            "market": "north_cyprus",
            "message": message,
            "seller_matches": [],
            "telegram_score": 50,
            "classification": "WARM",
        }

    def test_rejects_russian_listing_ad_with_remote_purchase_copy(self):
        message = (
            "Северный Кипр. 2-комнатные апартаменты 63 м² с панорамным видом на море. "
            "Апартаменты готовы к проживанию. £96,000. Код объекта 3586. "
            "Возможно посетить онлайн интересующую Вас квартиру и приобрести удаленно."
        )
        self.assertIsNone(gate.refine_telegram_property_buyer(self.lead(message)))

    def test_accepts_russian_self_buyer(self):
        message = "Я хочу купить квартиру 1+1 в Искеле. Бюджет £90,000, покупка в этом году."
        result = gate.refine_telegram_property_buyer(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")
        self.assertEqual(result["buyer_signal"], "self_purchase")

    def test_accepts_english_self_buyer(self):
        message = "I am looking to buy a 2 bedroom apartment in Long Beach, North Cyprus. Budget £120,000."
        result = gate.refine_telegram_property_buyer(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")

    def test_rejects_rental_request(self):
        message = "Ищу квартиру 2+1 в Искеле в аренду. Бюджет 650 евро в месяц."
        self.assertIsNone(gate.refine_telegram_property_buyer(self.lead(message)))

    def test_rejects_non_property_purchase(self):
        message = "Куплю машину в Гирне. Бюджет £6000."
        self.assertIsNone(gate.refine_telegram_property_buyer(self.lead(message)))

    def test_accepts_property_consideration_question(self):
        message = "Подскажите, где лучше купить квартиру в Искеле или Гирне на Северном Кипре?"
        result = gate.refine_telegram_property_buyer(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "WARM")
        self.assertEqual(result["buyer_signal"], "purchase_consideration")


if __name__ == "__main__":
    unittest.main()
