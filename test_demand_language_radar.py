import unittest

import demand_language_radar as dl


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        self.assert_orient = orient
        return list(self.rows)


class DemandLanguageRadarTests(unittest.TestCase):
    def test_related_rows_filters_to_safe_north_cyprus_demand_terms(self):
        related = {
            "rising": FakeFrame([
                {"query": "north cyprus payment plan apartment", "value": 80},
                {"query": "cheap flights cyprus", "value": 100},
            ]),
            "top": FakeFrame([
                {"query": "купить квартиру северный кипр рассрочка", "value": 50},
            ]),
        }
        rows = dl.related_rows(related, seed="north cyprus property", language="en")
        terms = {x["term"] for x in rows}
        self.assertIn("north cyprus payment plan apartment", terms)
        self.assertIn("купить квартиру северный кипр рассрочка", terms)
        self.assertNotIn("cheap flights cyprus", terms)
        ru = next(x for x in rows if x["term"].startswith("купить"))
        self.assertIn("telegram", ru["surfaces"])

    def test_content_feedback_ranks_repeated_buyer_concerns(self):
        rows = [
            {"labels": ["payment_plan"], "score": 80, "text": "How does the payment plan work?", "source": "Telegram"},
            {"labels": ["payment_plan", "off_plan_risk"], "score": 90, "text": "Is off-plan safe with installments?", "source": "Forum"},
            {"labels": ["title_deed"], "score": 88, "text": "Which title deed is safe?", "source": "Telegram"},
        ]
        feedback = dl.build_content_feedback(rows)
        self.assertEqual(feedback["topics"][0]["label"], "payment_plan")
        self.assertEqual(feedback["topics"][0]["count"], 2)
        self.assertIn("taksit", feedback["topics"][0]["suggested_title"].casefold())


if __name__ == "__main__":
    unittest.main()
