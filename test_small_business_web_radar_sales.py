import unittest
from unittest.mock import patch

import requests

import small_business_web_radar as base
import small_business_web_radar_sales as sales


class BrokenWebsiteSalesTests(unittest.TestCase):
    def _discovery(self, url="https://example-old-site.com/", phone="+90 533 111 22 33"):
        return base.Discovery(
            url=url,
            title="Example Local Clinic",
            category="dental",
            city="Gazimağusa",
            query="dental clinic in Gazimagusa North Cyprus",
            address="Gazimağusa, North Cyprus",
            phone=phone,
            place_type="Dental clinic",
            rating=4.6,
            rating_count=42,
        )

    def test_preserves_wix_site_slug(self):
        self.assertEqual(
            sales.root_url("https://onayandonay.wixsite.com/home/contact"),
            "https://onayandonay.wixsite.com/home",
        )

    def test_normal_domains_still_collapse_to_root(self):
        self.assertEqual(
            sales.root_url("https://example.com/services/page"),
            "https://example.com/",
        )

    def test_http_404_is_hot_when_business_has_direct_contact(self):
        response = type("Resp", (), {"status_code": 404})()
        with patch.object(sales.requests, "get", return_value=response):
            lead = sales.inspect_site(self._discovery())
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertGreaterEqual(lead["redesign_score"], 95)
        self.assertIn("HTTP 404", lead["reasons"][0])

    def test_broken_site_without_contact_is_not_actionable(self):
        response = type("Resp", (), {"status_code": 404})()
        with patch.object(sales.requests, "get", return_value=response):
            lead = sales.inspect_site(self._discovery(phone=""))
        self.assertIsNone(lead)

    def test_ssl_failure_is_hot_when_alternate_scheme_also_fails(self):
        with patch.object(sales.requests, "get", side_effect=requests.exceptions.SSLError("bad cert")):
            lead = sales.inspect_site(self._discovery())
        self.assertIsNotNone(lead)
        self.assertEqual(lead["classification"], "HOT")
        self.assertTrue(any("SSL" in reason for reason in lead["reasons"]))

    def test_single_timeout_is_not_alerted(self):
        with patch.object(sales.requests, "get", side_effect=requests.exceptions.ReadTimeout("slow")):
            lead = sales.inspect_site(self._discovery())
        self.assertIsNone(lead)


if __name__ == "__main__":
    unittest.main()
