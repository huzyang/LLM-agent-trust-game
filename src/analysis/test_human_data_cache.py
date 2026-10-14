"""Cache hit, source invalidation, corruption repair and window isolation."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import pandas as pd

if __package__:
    from .human_data_cache import load_records, load_table
else:
    from human_data_cache import load_records, load_table


class HumanCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / 'synthetic.xlsx'
        self.source.write_bytes(b'first synthetic input')
        self.cache = root / 'cache'
        self.calls = 0
        self.records = pd.DataFrame([
            {'population':'Human', 'session':'synthetic_session', 'p':p,
             'individual':i, 'round':r, 'entrusted':2., 'returned':3.,
             'source_sheet':'synthetic'}
            for p in [0.,.25,.5,.75,1.] for i in range(49) for r in range(1,51)])
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def reader(self, source, rounds):
        self.calls += 1
        self.assertIsNone(rounds)
        frame = self.records.copy()
        if source.read_bytes().startswith(b'second'):
            frame['entrusted'] = 3.
        return frame, ['player.send_T', 'player.return_T']

    def load(self, rounds=20, table='selected_round_records'):
        return load_table(self.source, rounds, self.reader, table=table, cache_dir=self.cache)

    def test_hit_skips_source_reader(self):
        first, provenance = self.load()
        self.assertEqual(provenance['status'], 'source_processed')
        again, provenance = self.load()
        self.assertEqual(provenance['status'], 'hit')
        self.assertEqual(self.calls, 1)
        pd.testing.assert_frame_equal(first, again)

    def test_new_window_uses_full_cached_records(self):
        self.load(20)
        full, provenance = self.load(50)
        self.assertEqual(self.calls, 1)
        self.assertEqual(provenance['status'], 'tables_prepared')
        self.assertEqual(len(full), 49*5*50)
        self.assertEqual(full['round'].max(), 50)
        third, _ = self.load(30)
        self.assertEqual(len(third), 49*5*30)
        self.assertEqual(self.calls, 1)

    def test_missing_and_corrupt_tables_are_repaired_without_excel(self):
        first, info = self.load()
        view = Path(info['table_path']).parent
        (view/'individual_means.csv').unlink()
        Path(info['table_path']).write_text('damaged', encoding='utf-8')
        repaired, info = self.load()
        self.assertEqual(info['status'], 'tables_prepared')
        self.assertEqual(self.calls, 1)
        self.assertTrue((view/'individual_means.csv').is_file())
        pd.testing.assert_frame_equal(first, repaired)

    def test_source_change_creates_separate_version(self):
        first, old = self.load()
        self.source.write_bytes(b'second synthetic input')
        changed, new = self.load()
        self.assertNotEqual(old['dataset'], new['dataset'])
        self.assertEqual(self.calls, 2)
        self.assertTrue(Path(old['table_path']).is_file())
        self.assertTrue(first.entrusted.eq(2.).all())
        self.assertTrue(changed.entrusted.eq(3.).all())

    def test_corrupt_base_is_rebuilt(self):
        _, info = self.load()
        base = Path(info['table_path']).parent.parent/'all_round_records.csv'
        base.write_text('damaged', encoding='utf-8')
        _, info = self.load()
        self.assertEqual(info['status'], 'source_processed')
        self.assertEqual(self.calls, 2)

    def test_rounds_beyond_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source has only 50'):
            self.load(51)


if __name__ == '__main__':
    unittest.main()
