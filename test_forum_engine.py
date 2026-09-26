import unittest

import forum_engine


class ForumEngineTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
