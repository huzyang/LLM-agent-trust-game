"""Check experimental-unit aggregation and missing single-session uncertainty."""
import unittest
import numpy as np
import pandas as pd

try:
    from .fig4 import summarise_rounds
except ImportError:
    from fig4 import summarise_rounds


class TemporalContractTests(unittest.TestCase):
    def test_sd_uses_session_means_not_individuals(self):
        rows = []
        for session, values in [('one', [0., 2.]), ('two', [2., 4.]), ('three', [4., 6.])]:
            for person, value in enumerate(values):
                rows.append(dict(population='Human', session=session, p=0,
                                 round=1, individual=person, entrusted=value, returned=value * 2))
        sessions, summary = summarise_rounds(pd.DataFrame(rows))
        result = summary[summary.metric == 'entrusted'].iloc[0]
        self.assertEqual(len(sessions), 3)
        self.assertEqual(result.n_sessions, 3)
        self.assertEqual(result['mean'], 3.)
        self.assertEqual(result.sd, 2.)
        self.assertEqual(result.lower, 1.)
        self.assertEqual(result.upper, 5.)

    def test_single_session_does_not_fabricate_zero_sd(self):
        rows = [dict(population='LLM', session='one', p=0, round=rd,
                     individual=person, entrusted=value, returned=value * 2)
                for rd in [1, 2] for person, value in enumerate([1., 3.])]
        _, summary = summarise_rounds(pd.DataFrame(rows))
        self.assertTrue(summary.sd.isna().all())
        self.assertTrue(summary.lower.isna().all())
        self.assertFalse(summary.band_available.any())
        self.assertTrue((summary.n_sessions == 1).all())
        self.assertEqual(len(summary), 4)

    def test_sessions_are_equally_weighted(self):
        rows = [dict(population='Human', session=session, p=0, round=1,
                     individual=i, entrusted=value, returned=value)
                for session, n, value in [('a', 2, 0.), ('b', 4, 4.)]
                for i in range(n)]
        _, summary = summarise_rounds(pd.DataFrame(rows))
        self.assertTrue(np.allclose(summary['mean'], 2.))


if __name__ == '__main__':
    unittest.main()
