"""Safety checks for missing rounds and falsely duplicated replications.

All fixtures here are synthetic and never enter Figure 3 or its source tables.
"""
import tempfile
from pathlib import Path
import unittest
import pandas as pd
if __package__:
    from .fig3 import validate_records, load_llm
else:
    from fig3 import validate_records, load_llm


class DataContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = pd.DataFrame([
            {'population':'LLM', 'session':'synthetic_session', 'p':p,
             'individual':person, 'round':rd, 'entrusted':2., 'returned':3.}
            for p in [0.,.25,.5,.75,1.] for person in range(49) for rd in range(1,21)
        ])

    def test_complete_network_sessions_are_accepted(self):
        validate_records(self.records,20)

    def test_missing_individual_round_stops_analysis(self):
        with self.assertRaisesRegex(ValueError,'exactly rounds'):
            validate_records(self.records.iloc[1:],20)

    def test_duplicate_round_is_not_an_extra_observation(self):
        duplicate=pd.concat([self.records,self.records.iloc[[0]]],ignore_index=True)
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            validate_records(duplicate,20)

    def test_same_file_cannot_be_passed_as_two_replications(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'agent_rounds.csv'
            pd.DataFrame({'iteration':[1],'round':[1],'proportion':[0.],
                          'agent_id':[0],'total_sent':[2.],'total_returned':[3.],
                          'data_source':['llm']}).to_csv(path,index=False)
            with self.assertRaisesRegex(ValueError,'more than once'):
                load_llm([path,path],20)


if __name__=='__main__':
    unittest.main()
