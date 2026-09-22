import unittest

import nc_v6_broad_radar as v6


class BroadIntentTests(unittest.TestCase):
    def assertLead(self, text, expected_class, group="North Cyprus Expats"):
        lead, reason = v6.classify_text(text, group=group)
        self.assertIsNotNone(lead, (text, reason))
        self.assertEqual(lead["lead_class"], expected_class, (text, lead))
        return lead

    def test_hot_buyer_budget_question(self):
        lead = self.assertLead(
            "Long Beach’te 120 bin pound civarında ne alınabilir?",
            "HOT BUYER",
        )
        self.assertEqual(lead["estimated_region"], "Long Beach")
        self.assertTrue(lead["estimated_budget"])

    def test_relocation_without_property_word(self):
        lead = self.assertLead(
            "Aralık ayında İskele’ye taşınacağız, çocuklarla hangi bölge daha iyi?",
            "RELOCATION",
        )
        self.assertEqual(lead["intent_type"], "RELOCATION")

    def test_ambiguous_two_bedroom_demand_is_watch_not_dropped(self):
        lead = self.assertLead(
            "İki yatak odalı, denize yakın, eşyalı bir şey arıyorum.",
            "WATCH",
        )
        self.assertIn("NEAR_SEA", lead["important_criteria"])
        self.assertIn("FURNISHED", lead["important_criteria"])

    def test_investment_question(self):
        self.assertLead("Long Beach yatırım için nasıl?", "INVESTOR")

    def test_hot_tenant(self):
        lead = self.assertLead(
            "Mağusa’da kiralık arıyorum, Ekim ayında taşınacağım. Bütçe £900.",
            "HOT TENANT",
        )
        self.assertEqual(lead["intent_type"], "TENANT")

    def test_property_research(self):
        self.assertLead(
            "Kuzey Kıbrıs'ta ev fiyatları ne kadar? 150 bin pound bütçeyle ne alınabilir?",
            "HOT BUYER",
        )

    def test_title_deed_research(self):
        self.assertLead("İskele'de koçanlı ev arıyorum.", "WARM BUYER")

    def test_payment_plan_investor(self):
        self.assertLead("Long Beach'te taksitli proje var mı, yatırım için bakıyorum.", "INVESTOR")

    def test_residency_property_research(self):
        self.assertLead("Oturma izni için Kuzey Kıbrıs'ta ev bakıyorum.", "WARM BUYER")

    def test_buy_to_rent_investor(self):
        self.assertLead("Kuzey Kıbrıs'ta ev alıp kiraya vermek istiyorum.", "HOT BUYER")

    def test_russian_buyer(self):
        self.assertLead("Хочу купить квартиру на Северном Кипре, бюджет £140000.", "HOT BUYER")

    def test_russian_investor(self):
        self.assertLead("Северный Кипр инвестиции: какой доход от аренды в Искеле?", "INVESTOR")

    def test_english_relocation(self):
        self.assertLead("We are moving to North Cyprus in December. Which area is best for a family?", "RELOCATION")

    def test_english_investor(self):
        self.assertLead("What is the rental yield in Long Beach, North Cyprus?", "INVESTOR")

    def test_listing_is_rejected(self):
        lead, reason = v6.classify_text(
            "FOR SALE 2+1 apartment Long Beach. Price £145000, 85 sqm, WhatsApp +90...",
            group="North Cyprus Property",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")

    def test_non_property_goods_rejected(self):
        lead, reason = v6.classify_text(
            "İskele'de daire için robot süpürge arıyorum, bütçe 150 euro.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "nonproperty_goods")

    def test_service_request_rejected(self):
        lead, reason = v6.classify_text(
            "Girne'de dairem için elektrikçi arıyorum.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "service_request")

    def test_realtor_request_is_service_not_property_lead(self):
        lead, reason = v6.classify_text(
            "Kuzey Kıbrıs'ta güvenilir emlakçı arıyorum.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "service_request")

    def test_generic_cyprus_without_north_context_does_not_force_market(self):
        lead, reason = v6.classify_text(
            "Looking for an apartment in Limassol.",
            group="Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_north_context")


if __name__ == "__main__":
    unittest.main()
