import unittest

import web_source_discovery as d


class WebSourceDiscoveryTests(unittest.TestCase):
    def test_discovers_html_alternate_feeds(self):
        html = """
        <html><head>
          <link rel="alternate" type="application/rss+xml" href="/forum/feed.xml">
          <link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml">
        </head></html>
        """
        found = d.discover_html_feeds(html, "https://example.com/forum/")
        self.assertEqual(
            found,
            ["https://example.com/forum/feed.xml", "https://example.com/atom.xml"],
        )

    def test_discovers_robots_sitemaps(self):
        robots = """
        User-agent: *
        Disallow: /private
        Sitemap: https://example.com/sitemap.xml
        Sitemap: /forum-sitemap.xml
        """
        found = d.discover_robots_sitemaps(robots, "https://example.com")
        self.assertIn("https://example.com/sitemap.xml", found)
        self.assertIn("https://example.com/forum-sitemap.xml", found)

    def test_parses_sitemap_index_and_urlset(self):
        index = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sitemap-forum.xml</loc></sitemap>
        </sitemapindex>
        """
        pages, nested = d.parse_sitemap(index, "https://example.com/sitemap.xml")
        self.assertEqual(pages, [])
        self.assertEqual(nested, ["https://example.com/sitemap-forum.xml"])

        urlset = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/forum/thread-1</loc></url>
          <url><loc>https://example.com/about</loc></url>
        </urlset>
        """
        pages, nested = d.parse_sitemap(urlset, "https://example.com/sitemap-forum.xml")
        self.assertEqual(len(pages), 2)
        self.assertEqual(nested, [])

    def test_parses_rss_and_atom_links(self):
        rss = """<rss><channel>
          <item><link>https://example.com/forum/thread-1</link></item>
        </channel></rss>"""
        self.assertEqual(
            d.parse_feed_urls(rss, "https://example.com/feed.xml"),
            ["https://example.com/forum/thread-1"],
        )

        atom = """<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><link href="https://example.com/forum/thread-2"/></entry>
        </feed>"""
        self.assertEqual(
            d.parse_feed_urls(atom, "https://example.com/atom.xml"),
            ["https://example.com/forum/thread-2"],
        )

    def test_internal_links_are_same_site_and_non_assets(self):
        html = """
        <a href="/forum/topic/north-cyprus-buying">topic</a>
        <a href="https://example.com/property/kyrenia">property</a>
        <a href="https://other.com/forum/topic">external</a>
        <a href="/assets/photo.jpg">image</a>
        """
        links = d.extract_internal_links(
            html,
            "https://example.com/",
            "https://example.com/",
        )
        self.assertIn("https://example.com/forum/topic/north-cyprus-buying", links)
        self.assertIn("https://example.com/property/kyrenia", links)
        self.assertNotIn("https://other.com/forum/topic", links)
        self.assertNotIn("https://example.com/assets/photo.jpg", links)

    def test_relevant_url_gate(self):
        self.assertTrue(d.relevant_url("https://example.com/forum/topic/north-cyprus-buying"))
        self.assertTrue(d.relevant_url("https://example.com/property/kyrenia-villa"))
        self.assertFalse(d.relevant_url("https://example.com/about-us"))
        self.assertFalse(d.relevant_url("https://example.com/contact"))


if __name__ == "__main__":
    unittest.main()
