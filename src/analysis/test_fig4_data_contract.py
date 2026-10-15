"""Check per-round individual dispersion, distinct session identities and bounds."""
import unittest
import numpy as np
import pandas as pd

try:
    from .fig4 import summarise_rounds
except ImportError:
    from fig4 import summarise_rounds


class TemporalContractTests(unittest.TestCase):
    def test_sd_uses_pooled_individuals_not_session_means(self):
        rows = []
        for session, values in [('one', [0., 2.]), ('two', [2., 4.]), ('three', [4., 6.])]:
            for person, value in enumerate(values):
                rows.append(dict(population='Human', session=session, p=0,
                                 round=1, individual=person, entrusted=value, returned=value * 2))
        sessions, summary = summarise_rounds(pd.DataFrame(rows))
        result = summary[summary.metric == 'entrusted'].iloc[0]
        self.assertEqual(len(sessions), 3)
        self.assertEqual(result.n_sessions, 3)
        self.assertEqual(result.n_individuals, 6)
        self.assertEqual(result['mean'], 3.)
        expected_sd = np.sqrt(4.4)  # sample variance of [0,2,2,4,4,6]
        self.assertAlmostEqual(result.sd, expected_sd)
        self.assertAlmostEqual(result.lower, 3. - expected_sd)
        self.assertAlmostEqual(result.upper, 3. + expected_sd)

    def test_single_session_retains_real_individual_sd(self):
        rows = [dict(population='LLM', session='one', p=0, round=rd,
                     individual=person, entrusted=value, returned=value * 2)
                for rd in [1, 2] for person, value in enumerate([1., 3.])]
        _, summary = summarise_rounds(pd.DataFrame(rows))
        sent = summary[summary.metric == 'entrusted']
        self.assertTrue(np.allclose(sent.sd, np.sqrt(2)))
        self.assertTrue(np.allclose(sent.lower, 2 - np.sqrt(2)))
        self.assertTrue(summary.band_available.all())
        self.assertTrue((summary.n_sessions == 1).all())
        self.assertTrue((summary.n_individuals == 2).all())
        self.assertEqual(len(summary), 4)

    def test_people_are_pooled_without_deduplicating_ids_across_sessions(self):
        rows = [dict(population='Human', session=session, p=0, round=1,
                     individual=i, entrusted=value, returned=value)
                for session, n, value in [('a', 2, 0.), ('b', 4, 4.)]
                for i in range(n)]
        _, summary = summarise_rounds(pd.DataFrame(rows))
        self.assertTrue(np.allclose(summary['mean'], 8./3.))
        self.assertTrue((summary.n_individuals == 6).all())

    def test_rounds_and_conditions_are_not_pooled_and_sd_is_not_clipped(self):
        rows = [dict(population='LLM', session='one', p=p, round=rd,
                     individual=i, entrusted=v + offset, returned=v + offset)
                for p, rd, offset in [(0, 1, 0), (.5, 1, 1), (0, 2, 2)]
                for i, v in enumerate([0., 0., 3.])]
        _, summary = summarise_rounds(pd.DataFrame(rows))
        sent = summary[summary.metric == 'entrusted'].sort_values(['round', 'p'])
        self.assertEqual(len(sent), 3)
        self.assertTrue(np.allclose(sent['mean'], [1., 2., 3.]))
        self.assertTrue(np.allclose(sent.sd, np.sqrt(3)))
        self.assertLess(sent.iloc[0].lower, 0.)


if __name__ == '__main__':
    unittest.main()
