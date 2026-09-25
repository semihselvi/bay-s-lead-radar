import unittest
from unittest.mock import patch

import nc_v6_broad_radar as v6


class BroadIntentTests(unittest.TestCase):
    def assertLead(self, text, expected_class, group="North Cyprus Expats"):
        lead, reason = v6.classify_text(text, group=group)
        self.assertIsNotNone(lead, (text, reason))
        self.assertEqual(lead["lead_class"], expected_class, (text, lead))
        return lead

    def test_hot_buyer_budget_question(self):
        lead = self.assertLead(
            "Long Beach’te 120 bin pound civarında ne alınabilir?",
            "HOT BUYER",
        )
        self.assertEqual(lead["estimated_region"], "Long Beach")
        self.assertTrue(lead["estimated_budget"])

    def test_relocation_without_property_word(self):
        lead = self.assertLead(
            "Aralık ayında İskele’ye taşınacağız, çocuklarla hangi bölge daha iyi?",
            "RELOCATION",
        )
        self.assertEqual(lead["intent_type"], "RELOCATION")

    def test_ambiguous_two_bedroom_demand_is_watch_not_dropped(self):
        lead = self.assertLead(
            "İki yatak odalı, denize yakın, eşyalı bir şey arıyorum.",
            "WATCH",
        )
        self.assertIn("NEAR_SEA", lead["important_criteria"])
        self.assertIn("FURNISHED", lead["important_criteria"])

    def test_investment_question(self):
        self.assertLead("Long Beach yatırım için nasıl?", "INVESTOR")

    def test_hot_tenant(self):
        lead = self.assertLead(
            "Mağusa’da kiralık arıyorum, Ekim ayında taşınacağım. Bütçe £900.",
            "HOT TENANT",
        )
        self.assertEqual(lead["intent_type"], "TENANT")

    def test_property_research(self):
        self.assertLead(
            "Kuzey Kıbrıs'ta ev fiyatları ne kadar? 150 bin pound bütçeyle ne alınabilir?",
            "HOT BUYER",
        )

    def test_title_deed_research(self):
        self.assertLead("İskele'de koçanlı ev arıyorum.", "WARM BUYER")

    def test_payment_plan_investor(self):
        self.assertLead("Long Beach'te taksitli proje var mı, yatırım için bakıyorum.", "INVESTOR")

    def test_residency_property_research(self):
        self.assertLead("Oturma izni için Kuzey Kıbrıs'ta ev bakıyorum.", "WARM BUYER")

    def test_buy_to_rent_investor(self):
        self.assertLead("Kuzey Kıbrıs'ta ev alıp kiraya vermek istiyorum.", "INVESTOR")

    def test_russian_buyer(self):
        self.assertLead("Хочу купить квартиру на Северном Кипре, бюджет £140000.", "HOT BUYER")

    def test_russian_investor(self):
        self.assertLead("Северный Кипр инвестиции: какой доход от аренды в Искеле?", "INVESTOR")

    def test_english_relocation(self):
        self.assertLead("We are moving to North Cyprus in December. Which area is best for a family?", "RELOCATION")

    def test_english_investor(self):
        self.assertLead("What is the rental yield in Long Beach, North Cyprus?", "INVESTOR")

    def test_listing_is_rejected(self):
        lead, reason = v6.classify_text(
            "FOR SALE 2+1 apartment Long Beach. Price £145000, 85 sqm, WhatsApp +90...",
            group="North Cyprus Property",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")

    def test_non_property_goods_rejected(self):
        lead, reason = v6.classify_text(
            "İskele'de daire için robot süpürge arıyorum, bütçe 150 euro.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "nonproperty_goods")

    def test_service_request_rejected(self):
        lead, reason = v6.classify_text(
            "Girne'de dairem için elektrikçi arıyorum.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "service_request")

    def test_realtor_request_is_service_not_property_lead(self):
        lead, reason = v6.classify_text(
            "Kuzey Kıbrıs'ta güvenilir emlakçı arıyorum.",
            group="North Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "service_request")

    def test_real_russian_rental_is_hot_tenant(self):
        self.assertLead(
            "Ищу в аренду Фамагуста квартиры 1+1/2+1 в Sky Sakarya или Premier за 600 долларов в месяц?",
            "HOT TENANT",
        )

    def test_one_month_studio_is_tenant(self):
        self.assertLead(
            "Ищу небольшую студию в Thalassa Beach Resort на 1 месяц, ориентировочно с 29 сентября.",
            "HOT TENANT",
        )

    def test_dated_short_stay_is_tenant(self):
        self.assertLead(
            "Ищу рядом 2 квартиры 2+1 и 1+1 с 9.10-19.10.",
            "HOT TENANT",
        )

    def test_crypto_not_property_buyer(self):
        lead, reason = v6.classify_text(
            "Всем привет, срочно куплю USDT за наличные. Только личная встреча",
            group="СЕВЕРНЫЙ КИПР | All you need",
        )
        self.assertIsNone(lead)

    def test_textbook_not_property_buyer(self):
        lead, reason = v6.classify_text("Куплю учебник", group="СЕВЕРНЫЙ КИПР | ФОРУМ")
        self.assertIsNone(lead)

    def test_padel_racket_not_property_buyer(self):
        lead, reason = v6.classify_text("Куплю 2 ракетки для падела. Можно Б/у", group="Iskele | Long Beach")
        self.assertIsNone(lead)

    def test_post_purchase_residency_question_not_buyer(self):
        lead, reason = v6.classify_text(
            "Добрый вечер. Получила титул. Подаю в первый раз на ВНЖ. Выписка с банка требуется?",
            group="СЕВЕРНЫЙ КИПР | ФОРУМ",
        )
        self.assertIsNone(lead)

    def test_property_management_company_not_investor(self):
        lead, reason = v6.classify_text(
            "Наша управляющая компания берет на себя полное обслуживание и сдачу недвижимости в долгосрочную аренду. Берем в управление недвижимость в районе Гирне.",
            group="СЕВЕРНЫЙ КИПР | ФОРУМ",
        )
        self.assertIsNone(lead)

    def test_agent_client_request_is_not_rejected_for_being_agent(self):
        lead, reason = v6.classify_text(
            "ищу для клиента виллу в лапте ближе к морю",
            group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
        )
        self.assertIsNotNone(lead)
        self.assertEqual(reason, "accepted")

    def test_housekeeper_job_rejected(self):
        lead, reason = v6.classify_text(
            "ВАКАНСИЯ — ПОМОЩНИЦА ПО ДОМУ. Зарплата 1500$ в месяц, проживание в доме.",
            group="СЕВЕРНЫЙ КИПР | ФОРУМ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "job_post")

    def test_car_installment_listing_rejected(self):
        lead, reason = v6.classify_text(
            "🚗 Марка/модель: Honda S660 Год: 2022 Рассрочка: Есть Место: Гирне Цена: 23,500£",
            group="СЕВЕРНЫЙ КИПР | ФОРУМ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "vehicle")

    def test_tutor_request_rejected(self):
        lead, reason = v6.classify_text(
            "Ищу репетитора для детей 7–11 лет. Репетитор должен приходить к нам домой.",
            group="СЕВЕРНЫЙ КИПР | ФОРУМ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "personal_service")

    def test_long_term_studio_is_hot_tenant(self):
        self.assertLead(
            "Ищу студию в роял сан, роял лайф (Искеле) на долгий срок",
            "HOT TENANT",
        )

    def test_owner_rental_request_is_hot_tenant(self):
        self.assertLead(
            "Я ищу квартиру-студию в Caesar Resort для себя. Владельцы, планирующие сдавать свои квартиры в аренду, пожалуйста, напишите мне.",
            "HOT TENANT",
        )

    def test_ready_client_intermediary_is_sales_lead(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "I am urgently looking for a 1+1 apartment in Famagusta for a ready client; the budget is between £45,000 and £50,000.",
                group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            )
        self.assertIsNotNone(lead)
        self.assertIn(lead["lead_class"], {"HOT BUYER", "WARM BUYER"})
        self.assertEqual(reason, "accepted")

    def test_vehicle_rental_rejected(self):
        lead, reason = v6.classify_text(
            "ищу в аренду авто 25€ в сутки. На 3ое суток!",
            group="Северный Кипр: объявления, работа, недвижимость",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "vehicle")

    def test_rental_supply_listing_rejected(self):
        lead, reason = v6.classify_text(
            "Аренда, Алсанджак 2+1 комплексе Olive hill. 1100£ 1-1-1 Айдат в цене Рассматриваем только европейцев.",
            group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")

    def test_sale_with_installment_rejected_not_investor(self):
        lead, reason = v6.classify_text(
            "Продаю таунхаус 2+1 с прямым видом на море в Эсентапе. 220000£, 120000£ сразу +100000£ в рассрочку.",
            group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")

    def test_marketing_investment_listing_rejected(self):
        lead, reason = v6.classify_text(
            "Такие участки появляются редко. Этот объект продается по цене ниже рынка. Если вы ищете ликвидную инвестицию — сейчас момент. 155 000 £. Пишите в личные сообщения.",
            group="Северный Кипр Недвижимость",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")

    def test_property_law_discussion_rejected(self):
        lead, reason = v6.classify_text(
            "Так все было хорошо до закона, мы квартиры продавали за час через переуступку, желающих было море.",
            group="СЕВЕРНЫЙ КИПР | ЧАТ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "discussion_or_hypothetical")

    def test_hypothetical_sarcastic_buy_rejected(self):
        lead, reason = v6.classify_text(
            "может, я когда-нибудь тогда квартиру куплю в Риксе, а пока будем сидеть и плакать",
            group="СЕВЕРНЫЙ КИПР | ЧАТ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "discussion_or_hypothetical")

    def test_lefkosa_owner_direct_rental_rejected(self):
        lead, reason = v6.classify_text(
            "Здравстуйте! Ищу квартиру 1+1 в Лефкоше, на долгосрочную аренду, с октября, от собственника.",
            group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "owner_direct_only")

    def test_generic_cyprus_without_north_context_does_not_force_market(self):
        lead, reason = v6.classify_text(
            "Looking for an apartment in Limassol.",
            group="Cyprus Expats",
        )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_north_context")




    def test_owner_direct_only_request_rejected(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Ищу 2+1 в Искеле для клиента, бюджет £120000, только от собственника",
                group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "owner_direct_only")

    def test_turkish_owner_only_request_rejected(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Müşterim için İskele'de 1+1 arıyorum, bütçe £100000, sadece sahibinden",
                group="Kuzey Kıbrıs Emlak",
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "owner_direct_only")

    def test_sales_only_rejects_rental(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Сниму 1+1 в Искеле, бюджет 600 евро",
                group="Северный Кипр Недвижимость",
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "rental_excluded_sales_only")

    def test_sales_only_rejects_generic_investment_discussion(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Какая доходность от недвижимости в Искеле?",
                group="Северный Кипр Недвижимость",
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "no_explicit_purchase_intent")

    def test_sales_only_accepts_direct_property_buyer(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Хочу купить квартиру 1+1 в Искеле, бюджет £120000",
                group="Северный Кипр Недвижимость",
            )
        self.assertIsNotNone(lead)
        self.assertIn(lead["lead_class"], {"HOT BUYER", "INVESTOR"})
        self.assertEqual(reason, "accepted")


    def test_sales_only_accepts_budget_property_demand_without_buy_verb(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Ищу 1+1 в Искеле, бюджет £100000",
                group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            )
        self.assertIsNotNone(lead)
        self.assertIn(lead["lead_class"], {"HOT BUYER", "WARM BUYER"})
        self.assertEqual(reason, "accepted")

    def test_sales_only_rejects_small_rental_sized_budget_without_buy(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Ищу 1+1 в Искеле, бюджет £600",
                group="СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            )
        self.assertIsNone(lead)


    def test_review_rejects_listing_shaped_sale(self):
        review = v6.build_review_candidate({
            "message": "Новый дюплекс 2+1 в Алсанджаке. Площадь 110 м². Цена 115.000 GBP. Обменный титул.",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@seller",
        })
        self.assertIsNone(review)

    def test_review_rejects_ambiguous_student_search(self):
        review = v6.build_review_candidate({
            "message": "Ищу для двух парней студентов 2+1 или студию, Гирне",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@person",
        })
        self.assertIsNone(review)

    def test_review_rejects_rental_listing(self):
        review = v6.build_review_candidate({
            "message": "Аренда Гирне. Вилла 3+1, 1600£, 2 депозита и комиссия.",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@agent",
        })
        self.assertIsNone(review)

    def test_review_keeps_plausible_purchase_research(self):
        review = v6.build_review_candidate({
            "message": "Ищу квартиру в Искеле. Какой район лучше для инвестиции и какие сейчас цены?",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@person",
        })
        self.assertIsNotNone(review)
        self.assertEqual(review["classification"], "REVIEW")
        self.assertIn("purchase_context", review["review_reasons"])


    def test_review_evaluator_explains_ambiguous_student_search(self):
        review, reason = v6.evaluate_review_candidate({
            "message": "Ищу для двух парней студентов 2+1 или студию, Гирне",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@person",
        })
        self.assertIsNone(review)
        self.assertEqual(reason, "no_purchase_context")

    def test_review_evaluator_explains_supply_listing(self):
        review, reason = v6.evaluate_review_candidate({
            "message": "Студия Caesar Blue, вид на море, всё оплачено, 52.000£",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@seller",
        })
        self.assertIsNone(review)
        self.assertIn(reason, {"supply_listing", "no_demand", "listing_shape"})

    def test_review_evaluator_marks_real_review_accepted(self):
        review, reason = v6.evaluate_review_candidate({
            "message": "Ищу квартиру в Искеле. Какой район лучше для инвестиции и какие сейчас цены?",
            "group": "СЕВЕРНЫЙ КИПР | НЕДВИЖИМОСТЬ",
            "author": "@person",
        })
        self.assertIsNotNone(review)
        self.assertEqual(reason, "accepted")


    def test_serper_credit_exhaustion_disables_rest_of_run(self):
        module = v6.radar.v53
        module._SERPER_DISABLED_FOR_RUN = False

        class FakeResponse:
            status_code = 400
            text = "Not enough credits"
            def json(self):
                return {"message": "Not enough credits", "statusCode": 400}

        calls = {"n": 0}

        def fake_post(*args, **kwargs):
            calls["n"] += 1
            return FakeResponse()

        try:
            with patch.dict("os.environ", {"SERPER_API_KEY": "test-key"}):
                with patch.object(module.core.requests, "post", side_effect=fake_post):
                    self.assertEqual(module._serper_search("first query"), [])
                    self.assertEqual(module._serper_search("second query"), [])
            self.assertTrue(module._SERPER_DISABLED_FOR_RUN)
            self.assertEqual(calls["n"], 1)
        finally:
            module._SERPER_DISABLED_FOR_RUN = False

    def test_search_debug_reports_disabled_paid_search_once(self):
        module = v6.radar.v53
        old_exa = module._EXA_DISABLED_FOR_RUN
        old_serper = module._SERPER_DISABLED_FOR_RUN
        try:
            module._EXA_DISABLED_FOR_RUN = True
            module._SERPER_DISABLED_FOR_RUN = True
            with patch.object(v6, "_existing_search", return_value=[]), patch.object(v6, "_bing_rss_search", return_value=[]):
                v6.DEBUG["web_provider_errors"].clear()
                v6.search_debug("North Cyprus buyer")
                v6.search_debug("North Cyprus buyer 2")
            self.assertEqual(v6.DEBUG["web_provider_errors"]["paid_search_disabled_for_run"], 1)
            self.assertEqual(v6.DEBUG["web_provider_errors"].get("exa_serper_empty_or_quota", 0), 0)
        finally:
            module._EXA_DISABLED_FOR_RUN = old_exa
            module._SERPER_DISABLED_FOR_RUN = old_serper
            v6.DEBUG["web_provider_errors"].clear()


    def test_strict_extra_prefilter_accepts_explicit_nc_buyer(self):
        self.assertTrue(v6.strict_extra_candidate_signal(
            "I want to buy a 2+1 apartment in North Cyprus, budget £120,000."
        ))

    def test_strict_extra_prefilter_rejects_non_nc_buyer(self):
        self.assertFalse(v6.strict_extra_candidate_signal(
            "I want to buy a 2+1 apartment in Marbella, budget €120,000."
        ))

    def test_strict_extra_prefilter_rejects_nc_nonproperty_chatter(self):
        self.assertFalse(v6.strict_extra_candidate_signal(
            "We are visiting North Cyprus next week. Which restaurant is best?"
        ))

    def test_unrelated_group_can_still_accept_explicit_nc_buyer(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            text = "Looking to buy a 1+1 apartment in North Cyprus. Budget £95,000."
            self.assertTrue(v6.strict_extra_candidate_signal(text))
            lead, reason = v6.classify_text(
                text,
                group="Random International Chat",
                explicit_geo=True,
            )
        self.assertIsNotNone(lead)
        self.assertEqual(reason, "accepted")
        self.assertIn(lead["lead_class"], {"HOT BUYER", "WARM BUYER"})

    def test_unrelated_group_plain_listing_rejected_by_prefilter(self):
        text = "North Cyprus apartment for sale, 1+1, £95,000. DM for details."
        self.assertFalse(v6.strict_extra_candidate_signal(text))

    def test_unrelated_group_marketing_listing_rejected_by_classifier(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            text = "Buy an apartment in North Cyprus today: 1+1 for sale, £95,000. DM for details."
            self.assertTrue(v6.strict_extra_candidate_signal(text))
            lead, reason = v6.classify_text(
                text,
                group="Random International Chat",
                explicit_geo=True,
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "supply_or_agent")


    def test_first_person_buyer_with_for_sale_phrase_is_not_blocked(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            text = "I want to buy an apartment for sale in North Cyprus, budget £95,000."
            lead, reason = v6.classify_text(
                text,
                group="Random International Chat",
                explicit_geo=True,
            )
        self.assertIsNotNone(lead)
        self.assertEqual(reason, "accepted")
        self.assertIn(lead["lead_class"], {"HOT BUYER", "WARM BUYER"})


    def test_live_robot_vacuum_message_is_not_property_buyer(self):
        with patch.dict("os.environ", {"RADAR_SALES_ONLY": "1"}):
            lead, reason = v6.classify_text(
                "Куплю моющий робот пылесос для большой квартиры. "
                "В хорошем состоянии Искеле -Фамагуста и др. Цена 1 тл для бота",
                group="СЕВЕРНЫЙ КИПР | БАРАХОЛКА",
            )
        self.assertIsNone(lead)
        self.assertEqual(reason, "nonproperty_goods")

if __name__ == "__main__":
    unittest.main()
