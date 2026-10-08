import unittest

import northlab_lead_radar_core as core


class NorthlabLeadRadarCoreTests(unittest.TestCase):
    def test_accepts_explicit_hot_buyer(self):
        self.assertTrue(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "message": "Куплю квартиру 3+1 в Querencia.",
            "lead_reasons": ["explicit_purchase_intent"],
            "specificity": 2,
        }))

    def test_accepts_specific_owner_direct_search(self):
        self.assertTrue(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "WARM BUYER",
            "message": "Ищу кто продает от собственника 2+1 в 4 очереди Цезаря",
            "lead_reasons": ["implicit_property_demand", "owner_direct_buyer_preference"],
            "specificity": 3,
        }))

    def test_rejects_implicit_property_demand(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "WARM BUYER",
            "message": "Ищу квартиру 2+1 на Северном Кипре",
            "lead_reasons": ["implicit_property_demand"],
            "specificity": 1,
        }))

    def test_rejects_property_research_signal(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "WARM BUYER",
            "message": "Какие квартиры лучше смотреть на Северном Кипре?",
            "lead_reasons": ["property_research_signal"],
            "specificity": 1,
        }))

    def test_rejects_tenant(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "TENANT",
            "lead_class": "HOT TENANT",
            "message": "Сниму 1+1 в Искеле на шесть месяцев.",
        }))

    def test_rejects_relocation_and_investor_chatter(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "RELOCATION",
            "lead_class": "RELOCATION",
            "message": "Thinking about moving to North Cyprus.",
        }))
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "INVESTOR",
            "lead_class": "INVESTOR",
            "message": "What are the yields in North Cyprus?",
        }))

    def test_rejects_car_purchase_even_if_upstream_labels_buyer(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "author": "@anna_smrnva",
            "message": "Куплю авто ~5000£ либо с первым взносом в рассрочку",
            "lead_reasons": ["explicit_purchase_intent"],
            "specificity": 2,
        }))

    def test_rejects_buyer_label_if_message_is_rental(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "message": "Looking to rent a 1+1 in Iskele for six months.",
            "lead_reasons": ["explicit_purchase_intent"],
            "specificity": 2,
        }))


if __name__ == "__main__":
    unittest.main()
