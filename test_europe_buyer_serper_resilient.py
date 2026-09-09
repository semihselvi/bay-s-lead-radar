import os
import unittest
from unittest.mock import patch

import europe_abroad_buyer_radar as abroad_base
import europe_buyer_search_fallback as fallback_search
import europe_buyer_serper_resilient as guard


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class SerperResilienceTests(unittest.TestCase):
    def test_detects_credit_exhaustion(self):
        self.assertTrue(guard.is_serper_credit_error(RuntimeError('Serper HTTP 402: {"message":"Not enough credits"}')))
        self.assertTrue(guard.is_serper_credit_error('SERPER_HTTP_402: Not enough credits'))

    def test_credit_exhaustion_disables_serper_and_uses_fallback(self):
        serper_calls = []
        fallback_calls = []

        def original(profile, query):
            serper_calls.append((profile, query))
            raise RuntimeError('Serper HTTP 402: Not enough credits')

        def fallback(profile, query):
            fallback_calls.append((profile, query))
            return [{"source": "Exa", "url": f"https://example.com/{query}"}]

        wrapped = guard.resilient_serper(original, 'test', fallback=fallback)
        self.assertEqual(wrapped('germany_home', 'q1')[0]['source'], 'Exa')
        self.assertEqual(wrapped('germany_home', 'q2')[0]['source'], 'Exa')
        self.assertEqual(len(serper_calls), 1)
        self.assertEqual(len(fallback_calls), 2)

    def test_non_credit_runtime_error_still_fails(self):
        def original(profile, query):
            raise RuntimeError('Serper HTTP 500: upstream failure')

        wrapped = guard.resilient_serper(original, 'test', fallback=lambda *args: [])
        with self.assertRaises(RuntimeError):
            wrapped('germany_home', 'q1')

    def test_provider_chain_falls_from_exa_quota_to_tavily(self):
        calls = []

        def exa(profile, query, lane):
            calls.append('exa')
            raise guard.ProviderRecoverableError('Exa HTTP 402: credits exhausted')

        def tavily(profile, query, lane):
            calls.append('tavily')
            return [{"source": "Tavily", "url": "https://example.com"}]

        with patch.dict(os.environ, {'RADAR_FALLBACK_QUERY_LIMIT': '10'}, clear=True):
            chain = guard.FallbackProviderChain('home', providers=[('exa', exa), ('tavily', tavily)])
            self.assertEqual(chain('germany_home', 'q1')[0]['source'], 'Tavily')
            self.assertEqual(chain('germany_home', 'q2')[0]['source'], 'Tavily')
        self.assertEqual(calls, ['exa', 'tavily', 'tavily'])

    def test_provider_chain_degrades_when_optional_keys_missing(self):
        with patch.dict(os.environ, {'RADAR_FALLBACK_QUERY_LIMIT': '10'}, clear=True):
            chain = guard.FallbackProviderChain('home')
            self.assertEqual(chain('germany_home', 'q1'), [])
            self.assertIn('exa', chain.disabled)
            self.assertIn('tavily', chain.disabled)

    def test_exa_http_500_is_real_failure(self):
        with patch.dict(os.environ, {'EXA_API_KEY': 'test'}, clear=True):
            with patch.object(fallback_search.requests, 'post', return_value=FakeResponse(500, {'error': 'upstream'})):
                with self.assertRaises(RuntimeError):
                    guard.exa_search('germany_home', 'Germany buy house', 'home')

    def test_exa_rows_keep_discovery_query(self):
        payload = {
            'results': [{
                'url': 'https://reddit.com/r/germany/comments/abc/test',
                'title': 'Buying a house',
                'text': 'I want to buy a house in Germany',
                'publishedDate': '2026-09-08T00:00:00.000Z',
                'author': 'user1',
            }]
        }
        with patch.dict(os.environ, {'EXA_API_KEY': 'test'}, clear=True):
            with patch.object(fallback_search.requests, 'post', return_value=FakeResponse(200, payload)):
                rows = guard.exa_search('germany_home', 'site:reddit.com/r/germany buy house', 'home')
        self.assertEqual(rows[0]['source'], 'Exa')
        self.assertEqual(rows[0]['discovery_query'], 'site:reddit.com/r/germany buy house')

    def test_fallback_query_budget_rotates_and_caps_calls(self):
        calls = []

        def exa(profile, query, lane):
            calls.append(query)
            return []

        with patch.dict(os.environ, {
            'RADAR_FALLBACK_QUERY_LIMIT': '2',
            'HOME_RADAR_QUERY_LIMIT': '10',
        }, clear=True):
            chain = guard.FallbackProviderChain('home', providers=[('exa', exa)])
            for i in range(10):
                chain('germany_home', f'q{i}')
        self.assertEqual(len(calls), 2)

    def test_global_expat_result_cannot_inherit_resident_country_from_query(self):
        item = {
            'source': 'Exa',
            'url': 'https://www.expat.com/en/forum/africa/mauritius/1118773-spouse-permanent-resident-application.html',
            'title': 'Spouse Permanent Resident Application - Mauritius forum - Expat.com',
            'text': (
                'I am a Mauritian by birth - still have my Mauritian passport and '
                'we have Canadian citizenships. We are planning to buy a property in Mauritius.'
            ),
        }
        queries = {
            'germany_abroad': 'site:expat.com Germany "buy property abroad" forum',
            'netherlands_abroad': 'site:expat.com Netherlands "buy property abroad" forum',
            'belgium_abroad': 'site:expat.com Belgium "buy property abroad" forum',
            'switzerland_abroad': 'site:expat.com Switzerland "buy property abroad" forum',
        }
        for profile, query in queries.items():
            candidate = dict(item, discovery_query=query)
            matched, explicit = guard.strict_abroad_audience_match(
                abroad_base, profile, candidate, candidate['text']
            )
            self.assertFalse(matched, profile)
            self.assertFalse(explicit, profile)

    def test_mauritius_false_positive_is_rejected_by_production_audience_gate(self):
        item = {
            'source': 'Exa',
            'url': 'https://www.expat.com/en/forum/africa/mauritius/1118773-spouse-permanent-resident-application.html',
            'title': 'Spouse Permanent Resident Application - Mauritius forum - Expat.com',
            'text': (
                'I am a Mauritian by birth - still have my Mauritian passport and '
                'we have Canadian citizenships. We are planning to buy a property in Mauritius.'
            ),
            'published': '2026-09-09T00:00:00Z',
            'author': 'Lkjba',
        }

        def strict(profile, candidate, text):
            return guard.strict_abroad_audience_match(abroad_base, profile, candidate, text)

        with patch.object(abroad_base, 'audience_match', side_effect=strict):
            for profile in (
                'germany_abroad', 'netherlands_abroad',
                'belgium_abroad', 'switzerland_abroad',
            ):
                query = abroad_base.PROFILES[profile]['queries'][4]
                lead, reason = abroad_base.classify(
                    profile, dict(item, discovery_query=query)
                )
                self.assertIsNone(lead, profile)
                self.assertEqual(reason, 'audience_unverified', profile)

    def test_explicit_resident_on_global_site_still_passes(self):
        item = {
            'url': 'https://www.expat.com/en/forum/europe/example.html',
            'discovery_query': 'site:expat.com Switzerland "buy property abroad" forum',
        }
        matched, explicit = guard.strict_abroad_audience_match(
            abroad_base,
            'switzerland_abroad',
            item,
            'I live in Switzerland and I am planning to buy a property in Portugal.',
        )
        self.assertTrue(matched)
        self.assertTrue(explicit)

    def test_matching_country_subreddit_can_bridge(self):
        item = {
            'url': 'https://www.reddit.com/r/germany/comments/abc/buying_abroad/',
            'discovery_query': 'site:reddit.com/r/germany "buy a house abroad"',
        }
        matched, explicit = guard.strict_abroad_audience_match(
            abroad_base,
            'germany_abroad',
            item,
            'We are planning to buy a property in Spain.',
        )
        self.assertTrue(matched)
        self.assertFalse(explicit)

    def test_resident_profiles_share_cross_profile_dedupe_key(self):
        lead = {
            'url': 'https://www.example.com/path/post?utm_source=test',
            'text': 'I want to buy a property abroad',
        }

        def original(profile, row):
            return f'original-{profile}'

        de_key = guard.cross_profile_abroad_lead_key(original, 'germany_abroad', lead)
        be_key = guard.cross_profile_abroad_lead_key(original, 'belgium_abroad', lead)
        self.assertEqual(de_key, be_key)
        self.assertEqual(
            guard.cross_profile_abroad_lead_key(original, 'golden_visa', lead),
            'original-golden_visa',
        )


if __name__ == '__main__':
    unittest.main()
