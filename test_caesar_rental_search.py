import unittest
from types import SimpleNamespace
from telethon.tl.types import PeerChannel, PeerChat
import caesar_rental_search as radar


class CaesarRentalSupplyTests(unittest.TestCase):
    def test_niche_studio_offer(self):
        self.assertEqual("niche_studio", radar.classify(
            "Caesar Resort & SPA, сдаётся студия с нишей, 450£ в месяц"))
    def test_one_bed_offer(self):
        self.assertEqual("1+1", radar.classify(
            "Caesar Resort 1+1 kiralık daire £500"))
    def test_rental_wanted_is_not_offer(self):
        self.assertIsNone(radar.classify(
            "Caesar Resort 1+1 kiralık arıyorum, teklif gönderin"))
        self.assertIsNone(radar.classify(
            "Caesar Resort, ищу студию с нишей в аренду"))
    def test_sale_listing_is_not_rent(self):
        self.assertIsNone(radar.classify(
            "Caesar Resort 1+1 satılık £70000"))
    def test_other_project_is_not_caesar(self):
        self.assertIsNone(radar.classify(
            "Caesar Blue 1+1 kiralık"))
    def test_group_provides_project_context(self):
        self.assertEqual("1+1", radar.classify(
            "Kiralık 1+1, £500", group="Caesar Resort & SPA"))
    def test_public_and_private_links(self):
        msg = SimpleNamespace(id=43, peer_id=PeerChannel(123))
        self.assertEqual("https://t.me/resortgroup/43", radar.link_for(
            SimpleNamespace(username="resortgroup", id=123), msg))
        self.assertEqual("https://t.me/c/123/43", radar.link_for(
            SimpleNamespace(username=None, id=123), msg))
        self.assertEqual("", radar.link_for(
            SimpleNamespace(username=None, id=123),
            SimpleNamespace(id=43, peer_id=PeerChat(123))))


if __name__ == "__main__":
    unittest.main()
