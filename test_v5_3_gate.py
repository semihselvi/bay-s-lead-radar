import unittest

import main_v5_3 as radar


class V53BuyerGateTests(unittest.TestCase):
    def lead(self, message: str):
        return {
            "market": "north_cyprus",
            "message": message,
            "seller_matches": [],
            "telegram_score": 40,
            "classification": "REVIEW",
        }

    def test_accepts_terse_russian_budgeted_buyer(self):
        message = "Ищу квартиру 1+1 в Искеле, бюджет до £90,000."
        result = radar.refine_with_budgeted_demand(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")
        self.assertEqual(result["buyer_signal"], "budgeted_property_demand")

    def test_accepts_terse_english_budgeted_buyer(self):
        message = "Looking for a 2 bedroom apartment in Long Beach. Budget £120k."
        result = radar.refine_with_budgeted_demand(self.lead(message))
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], "HOT")

    def test_rejects_russian_rental_with_monthly_budget(self):
        message = "Ищу квартиру 2+1 в Искеле в аренду, бюджет €700 в месяц."
        self.assertIsNone(radar.refine_with_budgeted_demand(self.lead(message)))

    def test_rejects_small_household_purchase(self):
        message = "Ищу чайник в Гирне, бюджет £30."
        self.assertIsNone(radar.refine_with_budgeted_demand(self.lead(message)))

    def test_rejects_listing_ad(self):
        message = "Продаётся квартира 1+1 в Искеле. Цена £90,000. Код объекта 1234."
        self.assertIsNone(radar.refine_with_budgeted_demand(self.lead(message)))

    def test_purchase_scale_budget(self):
        self.assertTrue(radar._purchase_scale_budget("budget £90,000"))
        self.assertTrue(radar._purchase_scale_budget("budget €120k"))
        self.assertFalse(radar._purchase_scale_budget("budget £900"))


if __name__ == "__main__":
    unittest.main()
