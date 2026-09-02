import unittest
from bs4 import BeautifulSoup

import small_business_web_radar as radar


class SmallBusinessWebRadarTests(unittest.TestCase):
    def test_blocks_directory_and_social_urls(self):
        self.assertTrue(radar.blocked_url("https://www.facebook.com/example"))
        self.assertTrue(radar.blocked_url("https://www.tripadvisor.com/Restaurant_Review-x"))
        self.assertFalse(radar.blocked_url("https://example-cafe.com/"))

    def test_detects_north_cyprus_context(self):
        self.assertIsNotNone(radar.NORTH_CYPRUS_RE.search("Family salon in Girne"))
        self.assertIsNotNone(radar.NORTH_CYPRUS_RE.search("Northern Cyprus dental clinic"))

    def test_place_rejects_large_business(self):
        row = {
            "title": "Example University",
            "address": "Girne, North Cyprus",
            "description": "Large university campus",
            "type": "University",
            "website": "https://example.edu/",
            "ratingCount": 900,
        }
        self.assertEqual(radar._place_reject_reason(row, "Girne", "university in Girne North Cyprus"), "large_business")

    def test_place_requires_own_website(self):
        row = {
            "title": "Local Barber",
            "address": "Girne, North Cyprus",
            "type": "Barber shop",
            "website": "",
        }
        self.assertEqual(radar._place_reject_reason(row, "Girne", "barber in Girne North Cyprus"), "no_website")

    def test_rejects_ecommerce_site(self):
        html = """
        <html><head><title>Local Shop</title></head><body>
        <a href='/cart'>View Cart</a><a href='/checkout'>Checkout</a>
        <button>Add to cart</button><p>WooCommerce</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        self.assertEqual(radar._page_reject_reason(html, text, soup, "https://example.com/"), "ecommerce")

    def test_legacy_site_scores_high(self):
        html = """
        <html>
        <head><title>Home</title></head>
        <body bgcolor='white'>
        <font size='3'>Girne family hair salon</font>
        <p>Copyright 2019</p>
        <a href='contact.html'>Contact</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        score, reasons = radar.score_site("http://example.com/", html, soup, 4.5)
        self.assertGreaterEqual(score, 60)
        self.assertIn("HTTPS yok", reasons)
        self.assertIn("mobil viewport yok", reasons)
        self.assertTrue(any("telif yılı eski" in x for x in reasons))

    def test_modern_simple_site_stays_below_threshold(self):
        html = """
        <html lang='en'>
        <head>
          <title>Girne Barber Studio</title>
          <meta name='viewport' content='width=device-width, initial-scale=1'>
          <meta name='description' content='Independent barber studio in Girne, North Cyprus. Appointments and grooming services.'>
          <meta property='og:title' content='Girne Barber Studio'>
          <link rel='icon' href='/favicon.ico'>
          <link rel='canonical' href='https://example.com/'>
          <script type='application/ld+json'>{}</script>
        </head>
        <body>
          <h1>Girne Barber Studio</h1>
          <p>North Cyprus independent barber studio. Modern cuts and beard grooming.</p>
          <a href='tel:+905551112233'>Call</a>
          <p>Copyright 2026</p>
          <div>""" + ("Service information and gallery. " * 500) + """</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        score, _ = radar.score_site("https://example.com/", html, soup, 0.5)
        self.assertLess(score, radar.MIN_SCORE)

    def test_extracts_public_business_contacts(self):
        html = """
        <html><body>
        <a href='tel:+90 555 111 22 33'>Call</a>
        <a href='mailto:hello@example.com'>Email</a>
        <a href='https://wa.me/905551112233'>WhatsApp</a>
        <a href='/contact'>Contact Us</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        contacts = radar.extract_contacts(soup, html, "https://example.com/")
        self.assertEqual(contacts["email"], "hello@example.com")
        self.assertTrue(contacts["phone"].startswith("+90"))
        self.assertIn("wa.me", contacts["whatsapp"])
        self.assertEqual(contacts["contact_page"], "https://example.com/contact")

    def test_query_rotation_is_bounded(self):
        queries = radar.build_queries()
        self.assertEqual(len(queries), min(radar.QUERY_LIMIT, len(radar.LOCATIONS) * len(radar.CATEGORIES)))
        self.assertTrue(all("North Cyprus" in q for _, _, q in queries))


if __name__ == "__main__":
    unittest.main()
