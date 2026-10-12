from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import nc_v6_broad_radar as radar


class PrimeBuyerSourceBootstrapTests(unittest.TestCase):
    def test_russian_six_month_rental_is_not_a_property_buyer(self):
        message = (
            "Добрый день ищу квартиру на пол года в фамагусте "
            "желательно от собственника студия либо 1+1 спасибо"
        )
        self.assertIsNotNone(radar.RENT_DEMAND_RE.search(message))
        with patch.dict(os.environ, {"RADAR_SALES_ONLY": "1"}):
            signal, reason = radar.classify_text(
                message, group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ"
            )
        self.assertIsNone(signal)
        self.assertEqual(reason, "rental_hard_excluded")

    def test_russian_tenant_profile_is_not_a_property_buyer(self):
        message = (
            "Ищу для себя квартиру прямо от собственника 1+1, "
            "в Royal Sun или Royal Life. Без комиссии! Не курю, без животных."
        )
        self.assertIsNotNone(radar.RENT_DEMAND_RE.search(message))

    def test_explicit_purchase_stays_eligible(self):
        message = "Куплю квартиру 2+1 в Искеле с титулом. Бюджет £120000."
        self.assertIsNone(radar.RENT_DEMAND_RE.search(message))
        with patch.dict(os.environ, {"RADAR_SALES_ONLY": "1"}):
            signal, reason = radar.classify_text(
                message, group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ"
            )
        self.assertIsNotNone(signal, reason)
        self.assertEqual(signal["intent_type"], "BUYER")

    def test_public_discussion_bootstrap_without_joining(self):
        seeds = radar.TELEGRAM_BOOTSTRAP_DISCUSSION_SEEDS
        self.assertIn("cyprusforum", seeds)
        self.assertIn("northern_cyprus_forum", seeds)
        self.assertIn("NCyprus_Iskele", seeds)
        self.assertEqual(len(seeds), len(set(seeds)))


if __name__ == "__main__":
    unittest.main()
