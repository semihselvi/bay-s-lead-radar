import unittest

import europe_buyer_serper_resilient as guard


class SerperResilienceTests(unittest.TestCase):
    def test_detects_credit_exhaustion(self):
        self.assertTrue(guard.is_serper_credit_error(RuntimeError('Serper HTTP 402: {"message":"Not enough credits"}')))
        self.assertTrue(guard.is_serper_credit_error('SERPER_HTTP_402: Not enough credits'))

    def test_credit_exhaustion_disables_provider_for_rest_of_run(self):
        calls = []

        def original(profile, query):
            calls.append((profile, query))
            raise RuntimeError('Serper HTTP 402: Not enough credits')

        wrapped = guard.resilient_serper(original, 'test')
        self.assertEqual(wrapped('germany_home', 'q1'), [])
        self.assertEqual(wrapped('germany_home', 'q2'), [])
        self.assertEqual(len(calls), 1)

    def test_non_credit_runtime_error_still_fails(self):
        def original(profile, query):
            raise RuntimeError('Serper HTTP 500: upstream failure')

        wrapped = guard.resilient_serper(original, 'test')
        with self.assertRaises(RuntimeError):
            wrapped('germany_home', 'q1')


if __name__ == '__main__':
    unittest.main()
