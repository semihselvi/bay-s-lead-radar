import unittest

from ocean_learning import normalize_identity, query_score


class OceanLearningTests(unittest.TestCase):
    def test_same_author_merges_across_sources(self):
        a = normalize_identity({"source": "Reddit", "author": "Buyer123", "text": ""})
        b = normalize_identity({"source": "Bluesky", "author": "@buyer123", "text": ""})
        self.assertEqual(a, b)

    def test_email_identity_wins(self):
        a = normalize_identity({"source": "Forum", "author": "x", "text": "email me at buyer@example.com"})
        b = normalize_identity({"source": "YouTube", "author": "y", "text": "buyer@example.com"})
        self.assertEqual(a, b)

    def test_new_buyer_query_scores_above_stale(self):
        productive = query_score({"runs": 2, "raw": 50, "qualified": 4, "new": 2})
        stale = query_score({"runs": 6, "raw": 500, "qualified": 8, "new": 0})
        self.assertGreater(productive, stale)


if __name__ == "__main__":
    unittest.main()
