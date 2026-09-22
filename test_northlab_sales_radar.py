import unittest

import northlab_sales_radar as radar


class NorthlabSalesRadarTests(unittest.TestCase):
    def assertLead(self, text, expected_class):
        lead, reason = radar.classify(text)
        self.assertIsNotNone(lead, (text, reason))
        self.assertEqual(lead["lead_class"], expected_class)
        return lead

    def assertReject(self, text, expected_reason):
        lead, reason = radar.classify(text)
        self.assertIsNone(lead)
        self.assertEqual(reason, expected_reason)

    def test_hot_website_project(self):
        lead = self.assertLead(
            "We need someone to redesign our restaurant website this week. Budget is €1500.",
            "HOT PROJECT",
        )
        self.assertIn("WEBSITE", lead["project_types"])

    def test_warm_website_project(self):
        self.assertLead(
            "Looking for someone who can build a website for a small business.",
            "WARM PROJECT",
        )

    def test_hot_crm_project(self):
        lead = self.assertLead(
            "Firmamız için müşteri takip CRM sistemi lazım, teklif almak istiyoruz.",
            "HOT PROJECT",
        )
        self.assertIn("CRM", lead["project_types"])

    def test_booking_project_ru(self):
        lead = self.assertLead(
            "Нужна система онлайн-бронирования для нашей компании.",
            "HOT PROJECT",
        )
        self.assertIn("BOOKING", lead["project_types"])

    def test_partner(self):
        self.assertLead(
            "Looking for a white-label development partner for overflow website projects.",
            "PARTNER",
        )

    def test_problem_signal(self):
        self.assertLead(
            "Our company website is outdated and we need a website redesign.",
            "HOT PROJECT",
        )

    def test_marketplace_bot_ad_rejected(self):
        self.assertReject(
            "🆕 НОВОЕ ОБЪЯВЛЕНИЕ НА PulseMarket! Цена: 1 ₺ 🌐 Смотреть на сайте #спрос",
            "marketplace_ad",
        )

    def test_government_portal_login_problem_rejected(self):
        self.assertReject(
            "Не могу зайти в личный кабинет на сайте permissions.gov/staypermit - пользователь не найден. Куда обращаться?",
            "portal_account_support",
        )

    def test_document_advice_in_personal_account_rejected(self):
        self.assertReject(
            "Если в списке документов в личном кабинете есть пункт с банковской выпиской, то нужна.",
            "document_portal_context",
        )

    def test_job_seeker_rejected(self):
        self.assertReject(
            "I am a web developer looking for a job. Here is my CV.",
            "job_seeker",
        )

    def test_full_time_vacancy_rejected(self):
        self.assertReject(
            "Vacancy: full-time web developer, salary €2500.",
            "employment_vacancy",
        )

    def test_service_provider_rejected(self):
        self.assertReject(
            "We build websites and CRM software for businesses. Our services include web design.",
            "service_provider",
        )

    def test_course_rejected(self):
        self.assertReject(
            "Looking for a web development course and tutorial.",
            "education",
        )


if __name__ == "__main__":
    unittest.main()
