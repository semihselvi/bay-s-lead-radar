import unittest

import adaptive_radar_learning as learning


class AdaptiveRadarLearningTests(unittest.TestCase):
    def test_concern_signal_requires_buyer_or_question_context(self):
        signal = learning.concern_signal(
            "I am looking to buy off-plan in North Cyprus. Is the title deed safe?",
            has_north_context=True,
        )
        self.assertIsNotNone(signal)
        self.assertIn("title_deed", signal["labels"])
        self.assertIn("off_plan_risk", signal["labels"])

        self.assertIsNone(
            learning.concern_signal(
                "Our agency explains title deeds in North Cyprus.",
                has_north_context=True,
            )
        )

    def test_query_ranking_prefers_proven_buyer_queries(self):
        queries = ["zero", "winner", "medium"]
        history = {
            "winner": {"runs": 2, "raw": 100, "north_context": 30, "valid": 8, "unique": 7, "new": 3},
            "medium": {"runs": 2, "raw": 100, "north_context": 10, "valid": 1, "unique": 1, "new": 0},
        }
        ranked = learning.rank_queries(queries, history)
        self.assertEqual(ranked[0], "winner")
        self.assertLess(ranked.index("medium"), ranked.index("zero"))

    def test_query_doc_id_is_stable(self):
        self.assertEqual(learning.query_doc_id("куплю 1+1"), learning.query_doc_id("куплю 1+1"))
        self.assertNotEqual(learning.query_doc_id("куплю 1+1"), learning.query_doc_id("куплю 2+1"))


if __name__ == "__main__":
    unittest.main()
