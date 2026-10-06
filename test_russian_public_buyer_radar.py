import unittest
from datetime import datetime, timezone

import russian_public_buyer_radar as r


def item(text, url="https://vk.com/wall-1_1"):
    return {
        "title": text,
        "text": "",
        "url": url,
        "platform": r.platform_from_url(url),
        "source": "test",
    }


class RussianPublicBuyerRadarTests(unittest.TestCase):
    def test_vk_ok_real_post_permalink_only(self):
        self.assertTrue(r._vk_ok_permalink("VK", "https://vk.com/wall-123_456"))
        self.assertTrue(r._vk_ok_permalink("OK", "https://ok.ru/group/123/topic/987"))
        self.assertFalse(r._vk_ok_permalink("VK", "https://vk.com/northcyprusinvest"))
        self.assertFalse(r._vk_ok_permalink("OK", "https://ok.ru/group/123"))
        self.assertFalse(r._vk_ok_permalink("VK", "https://evil.example.com/wall-123_456"))

    def test_vk_ok_search_index_requires_original_post_text(self):
        from unittest.mock import patch, Mock
        html = (
            '<div class="wall_post_text">Я хочу купить квартиру на Северном Кипре, '
            'бюджет 120 000 евро. Подскажите район.</div>'
            '<time datetime="2026-10-05T11:30:00+00:00"></time>'
        )
        with patch.object(r.requests, "get", return_value=Mock(status_code=200, text=html)):
            text, published = r._vk_ok_verified_content("https://vk.com/wall-123_456", "VK")
        self.assertIn("хочу купить квартиру", text)
        self.assertTrue(published.startswith("2026-10-05"))
        with patch.object(r.requests, "get", return_value=Mock(status_code=403, text="")):
            self.assertEqual(("", ""), r._vk_ok_verified_content("https://vk.com/wall-123_456", "VK"))
        with patch.object(r.requests, "get", return_value=Mock(status_code=200, text="<title>Куплю квартиру</title>")):
            self.assertEqual(("", ""), r._vk_ok_verified_content("https://vk.com/wall-123_456", "VK"))

    def test_vk_ok_index_date_must_come_from_original_post(self):
        from unittest.mock import patch, Mock
        html = '<html><time datetime="2026-10-05T11:30:00+00:00"></time></html>'
        with patch.object(r.requests, "get", return_value=Mock(status_code=200, text=html)):
            dt = r._vk_ok_verified_date("https://vk.com/wall-123_456")
        self.assertTrue(dt.startswith("2026-10-05T11:30:00"))
        with patch.object(r.requests, "get", return_value=Mock(status_code=403, text="")):
            self.assertEqual(r._vk_ok_verified_date("https://vk.com/wall-123_456"), "")

    def assertAccepted(self, text):
        lead, reason = r.classify_candidate(item(text))
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])
        return lead

    def assertRejected(self, text, reason):
        lead, got = r.classify_candidate(item(text))
        self.assertIsNone(lead)
        self.assertEqual(reason, got)

    def test_explicit_buyer(self):
        lead = self.assertAccepted(
            "Я хочу купить квартиру на Северном Кипре, бюджет 120 000 евро. Подскажите район."
        )
        self.assertEqual("HOT", lead["classification"])

    def test_planning_buyer(self):
        self.assertAccepted(
            "Мы планируем купить виллу в Гирне в следующем месяце. Что посоветуете?"
        )

    def test_investor_buyer(self):
        self.assertAccepted(
            "Я рассматриваю покупку квартиры в Искеле для инвестиций. Бюджет €150000."
        )

    def test_tenant_rejected(self):
        self.assertRejected(
            "Ищу квартиру на Северном Кипре, хочу снять на год.",
            "tenant",
        )

    def test_seller_rejected(self):
        self.assertRejected(
            "Продаю квартиру на Северном Кипре. Отличная цена, пишите в лс.",
            "seller_or_listing",
        )

    def test_company_rental_article_is_not_buyer(self):
        self.assertRejected(
            "Северный Кипр. Если вы рассматриваете варианты аренды жилья, компания Alliance-Estate "
            "ваш идеальный партнер. Мы специализируемся на аренде и продаже недвижимости. "
            "Звоните нам или посетите наш сайт.",
            "provider_or_agent",
        )

    def test_agent_rejected(self):
        self.assertRejected(
            "Агентство недвижимости Северного Кипра предлагает квартиры. Свяжитесь с нами.",
            "provider_or_agent",
        )

    def test_completed_buyer_rejected(self):
        self.assertRejected(
            "Я уже купил квартиру на Северном Кипре и теперь делюсь опытом.",
            "completed_or_cancelled",
        )

    def test_generic_article_rejected(self):
        self.assertRejected(
            "Недвижимость Северного Кипра: обзор рынка и цены на квартиры.",
            "no_explicit_purchase_intent",
        )

    def test_long_beach_racing_is_not_north_cyprus(self):
        self.assertFalse(
            r.has_nc_context("Long Beach drift yarışları ve motorsporları takvimi")
        )

    def test_long_beach_with_cyprus_context_is_north_cyprus(self):
        self.assertTrue(
            r.has_nc_context("Северный Кипр, Лонг Бич, Искеле")
        )

    def test_old_native_post_is_stale(self):
        candidate = item("Я хочу купить квартиру на Северном Кипре.")
        candidate["source_type"] = "public_platform_api"
        candidate["published"] = "1704067200"
        self.assertFalse(r.is_recent_enough(candidate, 90))

    def test_south_cyprus_not_accepted(self):
        self.assertRejected(
            "Я хочу купить квартиру в Лимассоле на Кипре.",
            "no_north_cyprus_context",
        )

    def test_comment_buyer_with_parent_context(self):
        candidate = item("Хочу купить квартиру, бюджет 130 000 евро. Что посоветуете?")
        candidate["north_cyprus_context"] = True
        lead, reason = r.classify_candidate(candidate)
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])

    def test_comment_without_buyer_intent_rejected(self):
        candidate = item("Спасибо, очень интересная статья.")
        candidate["north_cyprus_context"] = True
        lead, reason = r.classify_candidate(candidate)
        self.assertIsNone(lead)
        self.assertIn(reason, {"no_property", "no_explicit_purchase_intent"})

    def test_no_property_rejected(self):
        self.assertRejected(
            "Я хочу купить автомобиль на Северном Кипре.",
            "no_property",
        )



    def test_native_russian_date_parser(self):
        now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(r._native_published("вчера 15:20", now=now).startswith("2026-09-24"))
        self.assertTrue(r._native_published("13 окт 2025", now=now).startswith("2025-10-13"))

    def test_native_clock_is_today(self):
        now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(r._native_published("11:01", now=now).startswith("2026-09-25"))

    def test_native_buyer_still_uses_strict_classifier(self):
        candidate = {
            "title": "Хочу купить квартиру",
            "text": "Я хочу купить квартиру на Северном Кипре, бюджет 120 000 евро.",
            "url": "https://ok.ru/group/1/topic/2",
            "platform": "OK",
            "source": "OK Native Public",
            "source_type": "public_native_html",
            "published": datetime.now(timezone.utc).isoformat(),
            "north_cyprus_context": True,
        }
        lead, reason = r.classify_candidate(candidate)
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])

    def test_native_listing_still_rejected(self):
        candidate = {
            "title": "Продажа квартиры",
            "text": "Продаю квартиру на Северном Кипре, цена 120 000 евро. Пишите в личку.",
            "url": "https://ok.ru/group/1/topic/3",
            "platform": "OK",
            "source": "OK Native Public",
            "source_type": "public_native_html",
            "published": datetime.now(timezone.utc).isoformat(),
            "north_cyprus_context": True,
        }
        lead, reason = r.classify_candidate(candidate)
        self.assertIsNone(lead)
        self.assertEqual("seller_or_listing", reason)


    def test_vk_html_parser_extracts_north_cyprus_buyer(self):
        html = """
        <div class="post">
          <a class="PostHeaderSubtitle__link" href="/wall-123_456">сегодня в 11:20</a>
          <div class="wall_post_text">
            Я хочу купить квартиру на Северном Кипре, бюджет 120 000 евро. Подскажите район.
          </div>
        </div>
        """
        rows = r._vk_rows_from_html(html, "ru_cyprus", "Русские на Кипре")
        self.assertEqual(1, len(rows))
        self.assertEqual("VK", rows[0]["platform"])
        self.assertIn("wall-123_456", rows[0]["url"])
        lead, reason = r.classify_candidate(rows[0])
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])

    def test_vk_html_data_post_id_keeps_valid_wall_permalink(self):
        html = """
        <div class="post" data-post-id="-123_456">
          <time datetime="2026-10-05T11:20:00+00:00"></time>
          <div class="wall_post_text">
            Я хочу купить квартиру на Северном Кипре, бюджет 120 000 евро.
          </div>
        </div>
        """
        rows = r._vk_rows_from_html(html, "ru_cyprus", "Русские на Кипре")
        self.assertEqual(1, len(rows))
        self.assertEqual("https://vk.com/wall-123_456", rows[0]["url"])

    def test_scheduled_vk_scan_calls_native_group_adapter(self):
        from unittest.mock import patch, MagicMock
        with (
            patch.object(r, "vk_native_seed_search", return_value=[]) as native,
            patch.object(r, "ok_native_search", return_value=[]),
            patch.object(r, "bing_rss_search", return_value=[]),
            patch.object(r, "firestore_client", return_value=MagicMock()),
        ):
            report = r.scan_vk_ok()
        native.assert_called_once()
        self.assertEqual({}, report["raw"])
        self.assertEqual(0, report["notified"])

    def test_vk_html_parser_drops_south_cyprus_only_post(self):
        html = """
        <div class="post">
          <a class="PostHeaderSubtitle__link" href="/wall-123_457">сегодня в 11:25</a>
          <div class="wall_post_text">
            Я хочу купить квартиру в Лимассоле на Кипре, бюджет 300 000 евро.
          </div>
        </div>
        """
        rows = r._vk_rows_from_html(html, "ru_cyprus", "Русские на Кипре")
        self.assertEqual([], rows)


    def test_mailru_relative_date_parser(self):
        now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(r._native_published("1ч", now=now).startswith("2026-09-25"))
        self.assertTrue(r._native_published("3д", now=now).startswith("2026-09-22"))

    def test_mailru_question_html_can_feed_strict_buyer_classifier(self):
        html = """
        <div class="question-card">
          <span>1ч</span>
          <a href="/question/270999999">Хочу купить квартиру на Северном Кипре</a>
          <p>Я хочу купить квартиру на Северном Кипре, бюджет 130 000 евро. Какой район посоветуете?</p>
        </div>
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        anchor = soup.find("a")
        container = r._best_html_container(anchor)
        text = r.normalize(container.get_text(" ", strip=True))
        self.assertTrue(r.has_nc_context(text))
        candidate = {
            "title": r.normalize(anchor.get_text(" ", strip=True)),
            "text": text,
            "url": "https://otvet.mail.ru/question/270999999",
            "platform": "MailRu Answers",
            "source": "MailRu Answers Native Public",
            "source_type": "public_native_html",
            "published": r._native_published("1ч", now=datetime.now(timezone.utc)),
            "north_cyprus_context": True,
        }
        lead, reason = r.classify_candidate(candidate)
        self.assertIsNotNone(lead, reason)
        self.assertEqual("BUYER", lead["intent_type"])

if __name__ == "__main__":
    unittest.main()
