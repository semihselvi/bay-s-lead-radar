import unittest
from unittest.mock import patch

import forum_engine


class ForumEngineTests(unittest.TestCase):
    def test_real_forumscraper_symbols_are_available(self):
        self.assertIsNotNone(forum_engine._fs_extractor)
        self.assertIsNotNone(forum_engine._fs_outputs)

    def test_detects_xenforo_and_extracts_post(self):
        html = """
        <html><body data-template="thread_view" data-xf-init="test">
          <article class="message" id="post-123">
            <a class="username">BuyerOne</a>
            <time datetime="2026-09-25T10:00:00+00:00"></time>
            <div class="message-body"><div class="bbWrapper">
              I am looking to buy a 2 bed apartment in North Cyprus near Kyrenia.
            </div></div>
          </article>
        </body></html>
        """
        result = forum_engine.extract_forum_posts(html, "https://example.com/thread")
        self.assertEqual(result["engine"], "xenforo")
        self.assertEqual(len(result["posts"]), 1)
        post = result["posts"][0]
        self.assertEqual(post["author"], "BuyerOne")
        self.assertIn("looking to buy", post["text"])
        self.assertTrue(post["published"].startswith("2026-09-25T10:00:00"))

    def test_detects_phpbb(self):
        html = """
        <html><head><meta name="copyright" content="phpBB"></head><body>
        <div class="post" id="p45">
          <p class="author"><strong>Alice</strong></p>
          <div class="postbody"><div class="content">Want to buy property in North Cyprus.</div></div>
          <time datetime="2026-09-24T09:00:00+00:00"></time>
        </div>
        </body></html>
        """
        result = forum_engine.extract_forum_posts(html)
        self.assertEqual(result["engine"], "phpbb")
        self.assertEqual(len(result["posts"]), 1)



    def test_forumscraper_fallback_normalizes_structured_posts(self):
        class FakeExtractor:
            def __init__(self, **kwargs):
                pass

            def guess(self, url, html, **kwargs):
                return {
                    "data": {
                        "threads": [{
                            "format_version": "xenforo-2-thread",
                            "posts": [{
                                "id": 77,
                                "user": "BuyerTwo",
                                "date": "2026-09-26T08:30:00+0000",
                                "text": "<p>I want to buy a villa in <b>North Cyprus</b>, budget £250,000.</p>",
                            }],
                        }]
                    }
                }

        class FakeOutputs:
            data = 1
            threads = 2

        # No native post wrapper -> universal parser should become the fallback.
        html = "<html><body><main>forum shell</main></body></html>"
        with patch.object(forum_engine, "_fs_extractor", FakeExtractor), patch.object(
            forum_engine, "_fs_outputs", FakeOutputs
        ):
            result = forum_engine.extract_forum_posts(html, "https://example.com/threads/77")

        self.assertEqual(result["engine"], "xenforo")
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["posts"][0]["author"], "BuyerTwo")
        self.assertIn("want to buy a villa", result["posts"][0]["text"])
        self.assertNotIn("<p>", result["posts"][0]["text"])


    def test_discovers_forum_thread_urls(self):
        class FakeScraper:
            pass

        class FakeExtractor:
            def __init__(self, **kwargs):
                pass

            def guess(self, root_url, **kwargs):
                return {
                    "urls": {
                        "threads": [
                            "https://forum.example.com/threads/buying-north-cyprus.101/",
                            "https://forum.example.com/threads/buying-north-cyprus.101/",
                            "https://forum.example.com/threads/payment-plan.102/",
                            "not-a-url",
                        ]
                    },
                    "scraper": FakeScraper(),
                }

        class FakeOutputs:
            urls = 1

        with patch.object(forum_engine, "_fs_extractor", FakeExtractor), patch.object(
            forum_engine, "_fs_outputs", FakeOutputs
        ):
            result = forum_engine.discover_forum_threads(
                "https://forum.example.com/",
                limit=10,
            )

        self.assertEqual(len(result["threads"]), 2)
        self.assertEqual(
            result["threads"][0],
            "https://forum.example.com/threads/buying-north-cyprus.101/",
        )
        self.assertFalse(result["error"])

if __name__ == "__main__":
    unittest.main()
