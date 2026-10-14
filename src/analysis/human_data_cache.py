"""Reusable human trust-game tables; sources are immutable and hash-validated.

Entry point: python -m src.analysis.human_data_cache --human <xlsx>
Default cache: repository/human_experiment_datas. Origin is never started.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
P_VALUES = [0., .25, .5, .75, 1.]
HERE = Path(__file__).resolve().parent
DEFAULT_CACHE = (HERE.parent.parent if HERE.parent.name == 'src' else HERE) / 'human_experiment_datas'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _write_json(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write_csv(path, frame):
    temporary = path.with_suffix('.csv.tmp')
    frame.to_csv(temporary, index=False, encoding='utf-8-sig')
    temporary.replace(path)


def _read_csv(path):
    return pd.read_csv(path, float_precision='round_trip')


@contextmanager
def _lock(path):
    """OS-owned lock: concurrent preparations cannot mix partial cache files."""
    with path.open('a+b') as stream:
        if not path.stat().st_size:
            stream.write(b'0')
            stream.flush()
        started = time.monotonic()
        acquired = False
        try:
            while not acquired:
                stream.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() - started >= 60:
                        raise TimeoutError('Human cache is busy; active preparation was left intact')
                    time.sleep(.1)
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _validate(frame, rounds):
    key = ['population', 'session', 'p', 'individual', 'round']
    if frame.empty or frame.duplicated(key).any() or not frame.population.eq('Human').all():
        raise ValueError('Empty, duplicate or non-human records in human source')
    amounts = frame[['entrusted', 'returned']].to_numpy()
    if not np.isfinite(amounts).all() or (amounts < -1e-9).any() or (frame.entrusted > 5 + 1e-6).any():
        raise ValueError('Invalid human allocation')
    sizes = frame.groupby(key[:-1])['round'].agg(['count', 'min', 'max'])
    if not ((sizes['count'] == rounds) & (sizes['min'] == 1) & (sizes['max'] == rounds)).all():
        raise ValueError(f'Human individuals must have every round 1..{rounds}')
    counts = frame.groupby(['session', 'p']).individual.nunique()
    if not counts.eq(49).all():
        raise ValueError('Expected 49 individuals per human session and condition')
    for _, group in frame.groupby('session'):
        if sorted(group.p.unique()) != P_VALUES:
            raise ValueError('Human session lacks one of the five p conditions')


def _tables(records, rounds):
    ids = ['population', 'session', 'p', 'individual']
    means = records.groupby(ids)[['entrusted', 'returned']].mean().reset_index()
    means['rounds_averaged'] = rounds
    long = means.melt(id_vars=ids + ['rounds_averaged'], value_vars=['entrusted', 'returned'],
                      var_name='metric', value_name='amount')
    sessions = long.groupby(['population', 'session', 'p', 'metric']).amount.agg(
        n_individuals='size', mean='mean', sd_individual_means='std').reset_index()
    between = sessions.groupby(['population', 'p', 'metric'])['mean'].agg(
        n_sessions='size', mean_session_mean='mean', sd_session_means='std').reset_index()
    temporal = records.groupby(['population', 'session', 'p', 'round'])[['entrusted', 'returned']].mean().reset_index()
    temporal_long = temporal.melt(id_vars=['population', 'session', 'p', 'round'],
                                 value_vars=['entrusted', 'returned'], var_name='metric', value_name='session_mean')
    summary = temporal_long.groupby(['population', 'p', 'round', 'metric']).session_mean.agg(
        n_sessions='size', mean='mean', sd='std').reset_index()
    summary['lower'] = summary['mean'] - summary.sd
    summary['upper'] = summary['mean'] + summary.sd
    summary['band_available'] = summary.n_sessions >= 2
    tables = {'selected_round_records': records, 'individual_means': means,
              'individual_means_long': long, 'session_summary': sessions,
              'between_session_summary': between, 'round_means': temporal,
              'round_summary': summary}
    for metric in ['entrusted', 'returned']:
        tables[f'{metric}_individual_wide'] = pd.DataFrame({f'p={p:g}': pd.Series(
            long.loc[(long.p == p) & (long.metric == metric), 'amount'].to_numpy()) for p in P_VALUES})
        subset = summary[summary.metric == metric]
        trend = pd.DataFrame({'Round': range(1, rounds + 1)})
        for i, p in enumerate(P_VALUES):
            rows = subset[subset.p == p].sort_values('round')
            for column, suffix in [('mean', 'Mean'), ('sd', 'SD'), ('lower', 'Lower'), ('upper', 'Upper')]:
                trend[f'P{i}{suffix}'] = rows[column].to_numpy()
        tables[f'{metric}_round_wide'] = trend
    return tables


def _valid_file(path, expected_hash):
    return bool(expected_hash and path.is_file() and digest(path) == expected_hash)


def load_table(path, rounds, reader, *, table='selected_round_records', cache_dir=None):
    """Return a cached table and provenance; derive absent windows from full records.

    reader(path, None) reads all available rounds and returns (records, source fields).
    Cache corruption is repaired; changes to source or processing code get a new key.
    """
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
        raise ValueError('rounds must be a positive integer')
    source = Path(path).resolve()
    root = Path(cache_dir).resolve() if cache_dir else DEFAULT_CACHE
    source_hash = digest(source)
    reader_hash = hashlib.sha256(inspect.getsource(reader).encode()).hexdigest()
    processor_hash = hashlib.sha256((digest(__file__) + reader_hash).encode()).hexdigest()
    key = f'trust_game_{source_hash[:16]}_{processor_hash[:16]}'
    dataset = root / key
    dataset.mkdir(parents=True, exist_ok=True)
    with _lock(dataset / '.cache.lock'):
        base_manifest = dataset / 'source_manifest.json'
        base_file = dataset / 'all_round_records.csv'
        base = _read_json(base_manifest)
        identity = {'schema_version': SCHEMA_VERSION, 'source_sha256': source_hash,
                    'processor_sha256': processor_hash}
        base_valid = all(base.get(k) == v for k, v in identity.items()) and _valid_file(base_file, base.get('records_sha256'))
        rebuilt = not base_valid
        if rebuilt:
            records, fields = reader(source, None)
            available = int(records['round'].max()) if not records.empty else 0
            _validate(records, available)
            if digest(source) != source_hash:
                raise ValueError('Human source changed while it was read; no cache published')
            _write_csv(base_file, records)
            base = {**identity, 'source_path': str(source), 'source_fields': fields,
                    'available_rounds': available, 'records_count': len(records),
                    'n_sessions': int(records.session.nunique()), 'records_sha256': digest(base_file),
                    'excludes': 'Participant-information worksheet; no personal information exported'}
            _write_json(base_manifest, base)
        if rounds > base['available_rounds']:
            raise ValueError(f"Requested {rounds} rounds; source has only {base['available_rounds']}")
        view = dataset / f'rounds_{rounds}'
        view.mkdir(exist_ok=True)
        view_path = view / 'table_manifest.json'
        meta = _read_json(view_path)
        valid_view = (meta.get('rounds') == rounds and meta.get('base_records_sha256') == base['records_sha256'])
        hashes = meta.get('tables', {}) if valid_view else {}
        # Check every table: a deleted or damaged helper is replenished automatically.
        expected = ['selected_round_records', 'individual_means', 'individual_means_long',
                    'session_summary', 'between_session_summary', 'round_means', 'round_summary',
                    'entrusted_individual_wide', 'returned_individual_wide',
                    'entrusted_round_wide', 'returned_round_wide']
        if table not in expected:
            raise ValueError(f'Unknown human table: {table}; available tables: {expected}')
        missing = [name for name in expected if not _valid_file(view / f'{name}.csv', hashes.get(name))]
        if missing:
            records = _read_csv(base_file)
            selected = records[records['round'].between(1, rounds)].copy()
            _validate(selected, rounds)
            tables = _tables(selected, rounds)
            for name in missing:
                _write_csv(view / f'{name}.csv', tables[name])
            meta = {'rounds': rounds, 'base_records_sha256': base['records_sha256'],
                    'tables': {name: digest(view / f'{name}.csv') for name in expected},
                    'statistics': 'Per-individual means; per-session means; sample SD (ddof=1) across session means. No CI, fitting, smoothing or exclusions.'}
            _write_json(view_path, meta)
        if digest(source) != source_hash:
            raise ValueError('Human source changed while cache was being used')
        frame = _read_csv(view / f'{table}.csv')
        provenance = {'status': 'source_processed' if rebuilt else 'tables_prepared' if missing else 'hit',
                      'cache_dir': str(root), 'dataset': key, 'rounds': rounds,
                      'table': table, 'table_path': str(view / f'{table}.csv'),
                      'table_sha256': meta['tables'][table], 'source_sha256': source_hash,
                      'processor_sha256': processor_hash, 'source_fields': base['source_fields']}
        frame.attrs['human_cache'] = {k: v for k, v in provenance.items() if k != 'source_fields'}
    print(json.dumps({'stage': 'human_cache', **frame.attrs['human_cache']}, ensure_ascii=False), flush=True)
    return frame, provenance


def load_records(path, rounds, reader, cache_dir=None):
    frame, provenance = load_table(path, rounds, reader, cache_dir=cache_dir)
    return frame, provenance['source_fields']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--human', required=True)
    p.add_argument('--rounds', type=int, nargs='+', default=[20, 50])
    p.add_argument('--cache-dir')
    args = p.parse_args()
    try:
        from .fig3 import _load_human_uncached
    except ImportError:
        from fig3 import _load_human_uncached
    for rounds in args.rounds:
        load_records(args.human, rounds, _load_human_uncached, args.cache_dir)


if __name__ == '__main__':
    main()
