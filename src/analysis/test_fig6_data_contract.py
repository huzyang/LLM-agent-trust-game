import unittest
import numpy as np
import pandas as pd
try:
    from .fig6 import features,fit_phenotypes,summarise,make_tables,FACTORS
except ImportError:
    from fig6 import features,fit_phenotypes,summarise,make_tables,FACTORS

class Contract(unittest.TestCase):
    def test_lag_and_directional_conditions(self):
        rows=[]
        for t,(send,back,inc) in enumerate([(5,2,1),(3,0,2),(4,1,1),(2,0,3)],1):
            row={'population':'LLM','session':'s','p':0,'individual':1,'round':t,'entrusted':send,'returned':10*t}
            for i in range(4):row.update({f'sent{i}':send/4,f'back{i}':back,f'incoming{i}':inc})
            rows.append(row)
        f=features(pd.DataFrame(rows)).set_index('role')
        self.assertAlmostEqual(f.loc['entrusted','A'],3.5)
        self.assertAlmostEqual(f.loc['entrusted','B'],2.5)
        self.assertEqual(f.loc['entrusted','C'],4)
        self.assertEqual(f.loc['entrusted','D'],4)
        self.assertEqual(f.loc['entrusted','En'],0)
        self.assertTrue(np.isnan(f.loc['entrusted','E']))
        self.assertEqual(f.loc['returned','F'],30)
        self.assertEqual(f.loc['returned','D'],40)
        self.assertEqual(f.loc['returned','Dn']+f.loc['returned','En']+f.loc['returned','Fn'],2)

    def test_imputation_is_not_observed_profile(self):
        rows=[]
        for i,a in enumerate([.1,.2,2,2.1,4.8,4.9]):
            r={'population':'LLM','session':'s','p':0,'individual':i,'role':'entrusted'}
            for f in FACTORS:r[f]=a if f!='D' else np.nan;r[f+'n']=20 if f=='A' else (0 if f=='D' else 4)
            rows.append(r)
        labels,models=fit_phenotypes(pd.DataFrame(rows))
        self.assertTrue(labels.D.isna().all());self.assertTrue(np.allclose(labels.D_input,labels.A))
        self.assertEqual(models[0]['all_missing_factors'],['D'])
        profiles,fractions=summarise(labels)
        self.assertTrue(profiles.loc[profiles.factor=='D','mean_observed'].isna().all())
        present=fractions[fractions.denominator>0]
        self.assertTrue(np.allclose(present.groupby(['population','role','p']).fraction.sum(),1))
        self.assertEqual(set(labels.phenotype),{'Prosocial','Neutral','Antisocial'})

if __name__=='__main__':unittest.main()
