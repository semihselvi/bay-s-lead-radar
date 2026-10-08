import unittest

import northlab_lead_radar_core as core


class NorthlabLeadRadarCoreTests(unittest.TestCase):
    def test_accepts_hot_buyer(self):
        self.assertTrue(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "message": "Куплю квартиру 3+1 в Querencia.",
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
        }))

    def test_rejects_buyer_label_if_message_is_rental(self):
        self.assertFalse(core.is_actionable_buyer({
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "message": "Looking to rent a 1+1 in Iskele for six months.",
        }))


class SmartNotifyPolicyTests(unittest.TestCase):
    def test_explicit_buyer_is_actionable(self):
        lead = {
            "market": "north_cyprus",
            "intent_type": "BUYER",
            "lead_class": "HOT BUYER",
            "message": "Куплю квартиру 2+1 в Искеле",
            "lead_reasons": ["explicit_purchase_intent"],
            "intent_score": 86,
            "specificity": 2,
        }
        self.assertTrue(core.is_actionable_buyer(lead))


if __name__ == "__main__":
    unittest.main()
