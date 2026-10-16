import unittest
import numpy as np
import pandas as pd
try:
    from .fig5 import gini, summarise, plot_tables
except ImportError:
    from fig5 import gini, summarise, plot_tables

class Contract(unittest.TestCase):
    def test_gini_matches_pairwise_definition(self):
        x=np.array([0.,1.,3.,12.])
        self.assertAlmostEqual(gini(x),np.abs(x[:,None]-x[None,:]).sum()/(2*len(x)*x.sum()))
        self.assertEqual(gini([0,0]),0)
        self.assertAlmostEqual(gini([8,8,8]),0)
        self.assertAlmostEqual(gini([-1,5]),.75)
        with self.assertRaises(ValueError):gini([-2,1])

    def test_gini_within_sessions_not_pooled(self):
        d=pd.DataFrame({'population':['Human']*4,'session':['a','a','b','b'],
            'p':[0]*4,'individual':[1,2,1,2],'group':['Constrained']*4,
            'accumulate_payoff':[1.,1.,100.,100.]})
        expanded,w,s,g=summarise(d)
        self.assertTrue(np.allclose(g['mean'],0))
        self.assertGreater(gini(d.accumulate_payoff),.4)
        self.assertEqual(len(expanded),8)
        self.assertEqual(w.loc[w.group=='Combined','n_individuals'].iloc[0],4)
        self.assertAlmostEqual(w.loc[w.group=='Combined','sd'].iloc[0],d.accumulate_payoff.std(ddof=1))
        tables=plot_tables(expanded,w,s,g)
        self.assertNotIn('P0G1BarY',tables['human_gini'])
        self.assertTrue(np.array_equal(tables['human_wealth']['P0G0RawY'].dropna(),d.accumulate_payoff))

if __name__=='__main__':unittest.main()
