"""主脚本 / Main entry point: reproduce Figure 3 from immutable raw data.

Run from the repository root: python -m src.analysis.fig3 --help
Windows launcher: src/analysis/run_fig3.ps1

prepare: raw records -> individual 20-round means -> explicit plotting tables.
render: plotting tables -> native, editable Origin graphs and four exports.
all: both stages.  No input is overwritten; each run gets a new output folder.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import subprocess
import shutil
import time
from datetime import datetime
from contextlib import contextmanager

import numpy as np
import pandas as pd

P_VALUES = [0, 0.25, 0.5, 0.75, 1]
LLM_COLORS = ['#1B9E77', '#D95F02', '#7570B3', '#E7298A', '#66A61E']
HUMAN_COLORS = ['#F25A20', '#BA4A31', '#843B37', '#5C2E39', '#372334']
PANELS = [('LLM', 'entrusted'), ('Human', 'entrusted'),
          ('LLM', 'returned'), ('Human', 'returned')]
HERE = Path(__file__).resolve().parent


def box_fill_color(color):
    """Pale opaque fill, so raw markers remain visible on Origin 2021 boxes."""
    rgb=[int(color[i:i+2],16) for i in [1,3,5]]
    return '#'+''.join(f'{round(.28*value+.72*255):02X}' for value in rgb)


def event(stage, **details):
    print(json.dumps({'stage': stage, **details}, ensure_ascii=False), flush=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                   allow_nan=False), encoding='utf-8')


def validate_records(frame, rounds):
    key = ['population', 'session', 'p', 'individual', 'round']
    if frame.duplicated(key).any():
        raise ValueError('Duplicate population/session/p/individual/round records')
    if not np.isfinite(frame[['entrusted', 'returned']].to_numpy()).all():
        raise ValueError('Non-finite allocation: missing values are not imputed')
    if (frame[['entrusted', 'returned']] < -1e-9).any().any():
        raise ValueError('Negative allocation')
    if (frame.entrusted > 5 + 1e-6).any():
        raise ValueError('Total entrusted amount exceeds the five-token endowment')
    sizes = frame.groupby(key[:-1])['round'].agg(['count', 'min', 'max'])
    if not ((sizes['count'] == rounds) & (sizes['min'] == 1) &
            (sizes['max'] == rounds)).all():
        raise ValueError(f'Each individual must have exactly rounds 1..{rounds}')
    counts = frame.groupby(['population', 'session', 'p'])['individual'].nunique()
    if not (counts == 49).all():
        raise ValueError(f'Expected 49 individuals per session/condition; got {counts.to_dict()}')
    for (population, session), group in frame.groupby(['population', 'session']):
        if sorted(group.p.unique()) != P_VALUES:
            raise ValueError(f'{population}/{session} does not contain all five p conditions')


def _load_human_uncached(path, rounds=None):
    import openpyxl
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    selected, fields = [], None
    try:
        for sheet in book:
            match = re.fullmatch(r'TG (0|25|50|75|100)% free session(\d+)', sheet.title)
            if not match:
                continue  # Participant-information sheet is not used or exported.
            rows = sheet.iter_rows(values_only=True)
            names = list(next(rows))
            fields = names
            idx = {name: i for i, name in enumerate(names)}
            for row in rows:
                rd = row[idx['subsession.round_number']]
                if rd is None or int(rd) < 1 or (rounds is not None and int(rd) > rounds):
                    continue
                sent = float(row[idx['player.send_T']])
                returned = float(row[idx['player.return_T']])
                if not math.isclose(sent, sum(float(row[idx[f'player.send_{d}']]) for d in 'LURD'), abs_tol=0.02):
                    raise ValueError(f'Human entrusted total/component mismatch in {sheet.title}')
                if not math.isclose(returned, sum(float(row[idx[f'player.return_{d}']]) for d in 'LURD'), abs_tol=0.02):
                    raise ValueError(f'Human returned total/component mismatch in {sheet.title}')
                selected.append({'population': 'Human', 'session': 'human_' + match[2],
                    'p': int(match[1]) / 100, 'individual': int(row[idx['player.id_in_group']]),
                    'round': int(rd), 'entrusted': sent, 'returned': returned,
                    'source_sheet': sheet.title})
    finally:
        book.close()
    frame = pd.DataFrame(selected)
    if frame.empty:
        raise ValueError('No matching TG worksheets found')
    return frame, fields


def load_human(path, rounds, cache_dir=None):
    """Read validated, reusable human tables; XLSX is parsed only on a cache miss."""
    if __package__:
        from .human_data_cache import load_records
    else:
        from human_data_cache import load_records
    return load_records(path, rounds, _load_human_uncached, cache_dir)


def load_llm(paths, rounds):
    frames, hashes, configurations, fields, seen_hashes = [], [], [], None, set()
    for number, input_path in enumerate(paths, 1):
        input_path = Path(input_path).resolve()
        csv_path = input_path / 'agent_rounds.csv' if input_path.is_dir() else input_path
        sha = digest(csv_path)
        if sha in seen_hashes:
            raise ValueError('Same LLM CSV supplied more than once')
        seen_hashes.add(sha)
        source = pd.read_csv(csv_path)
        fields = list(source.columns)
        required = {'iteration', 'round', 'proportion', 'agent_id', 'total_sent', 'total_returned'}
        if not required.issubset(source.columns):
            raise ValueError(f'Missing LLM columns: {sorted(required - set(source.columns))}')
        if 'data_source' in source and not source.data_source.eq('llm').all():
            raise ValueError('Mock or mixed-source LLM data is not accepted')
        config_path = csv_path.parent / 'config.json'
        cfg = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else None
        if cfg and cfg.get('mock'):
            raise ValueError('Mock configuration is not accepted')
        configurations.append({'input_number': number, 'configuration': cfg})
        selected = source.loc[source['round'].between(1, rounds)].copy()
        if all(f'sent_to_n{i}' in selected for i in range(1, 5)):
            if not np.allclose(selected.total_sent, selected[[f'sent_to_n{i}' for i in range(1, 5)]].sum(axis=1)):
                raise ValueError('LLM entrusted total/component mismatch')
        if all(f'returned_to_n{i}' in selected for i in range(1, 5)):
            if not np.allclose(selected.total_returned, selected[[f'returned_to_n{i}' for i in range(1, 5)]].sum(axis=1)):
                raise ValueError('LLM returned total/component mismatch')
        frame = pd.DataFrame({'population': 'LLM',
            'session': selected.iteration.map(lambda x: f'llm_{number}_iteration_{int(x)}'),
            'p': selected.proportion, 'individual': selected.agent_id,
            'round': selected['round'], 'entrusted': selected.total_sent,
            'returned': selected.total_returned, 'source_sheet': csv_path.name})
        # Retain actual fractions and correction flags for audit, without exclusions.
        for name in ['actual_proportion', 'investor_corrected', 'trustee_corrected',
                     'investor_parse_failed', 'trustee_parse_failed']:
            if name in selected:
                frame[name] = selected[name].values
        frames.append(frame)
        hashes.append({'path': str(csv_path), 'sha256': sha, 'kind': 'LLM CSV'})
        if config_path.exists():
            hashes.append({'path': str(config_path), 'sha256': digest(config_path), 'kind': 'LLM configuration'})
    # Refuse to mix scientifically different configurations when multiple are supplied.
    keys = ['num_agents', 'width', 'height', 'model_type_list', 'history_rounds',
            'total_round_info', 'temperature', 'thinking', 'report_bdi']
    configs = [x['configuration']['params'] for x in configurations if x['configuration']]
    for key in keys:
        if len({json.dumps(x.get(key), sort_keys=True) for x in configs}) > 1:
            raise ValueError(f'LLM configurations differ in {key}; explicit reconciliation required')
    return pd.concat(frames, ignore_index=True), hashes, configurations, fields


def column_roles(names, population):
    primary = {'total_sent', 'total_returned'} if population == 'LLM' else {'player.send_T', 'player.return_T'}
    support = ({'iteration', 'round', 'proportion', 'agent_id', 'num_agents', 'data_source',
        'actual_proportion', 'investor_corrected', 'trustee_corrected',
        'investor_parse_failed', 'trustee_parse_failed'} |
        {f'sent_to_n{i}' for i in range(1, 5)} | {f'returned_to_n{i}' for i in range(1, 5)}) if population == 'LLM' else {
        'player.id_in_group', 'subsession.round_number',
        *[f'player.send_{d}' for d in 'LURD'], *[f'player.return_{d}' for d in 'LURD']}
    return [{'column': name,
        'role': 'render_primary' if name in primary else 'support_only' if name in support else 'retain_not_render',
        'purpose': 'Allocation endpoint' if name in primary else 'Identity, window or validation' if name in support else 'Not used by this figure; retained in immutable input'} for name in names]


def prepare(args, out):
    from scipy.stats import t
    event('read_raw_data')
    human_path = Path(args.human).resolve()
    human_sha = digest(human_path)
    human, human_fields = load_human(human_path, args.rounds, getattr(args, 'human_cache_dir', None))
    llm, hashes, configs, llm_fields = load_llm(args.llm_session, args.rounds)
    records = pd.concat([llm, human], ignore_index=True)
    validate_records(records, args.rounds)
    identifiers = ['population', 'session', 'p', 'individual']
    means = records.groupby(identifiers, sort=True)[['entrusted', 'returned']].mean().reset_index()
    means['rounds_averaged'] = args.rounds
    long = means.melt(id_vars=identifiers + ['rounds_averaged'],
                      value_vars=['entrusted', 'returned'], var_name='metric', value_name='amount')
    summaries = []
    for (population, p, metric), group in long.groupby(['population', 'p', 'metric'], sort=True):
        values = group.amount.to_numpy()
        n, mean, sd = len(values), values.mean(), values.std(ddof=1)
        half = float(t.ppf(.975, n - 1) * sd / math.sqrt(n))
        q1, median, q3 = np.quantile(values, [.25, .5, .75], method='linear')
        summaries.append({'population': population, 'p': p, 'metric': metric,
            'n_individuals': n, 'n_sessions': group.session.nunique(),
            'rounds_averaged': args.rounds, 'mean': mean, 'sd_individual_means': sd,
            'se_individual_means': sd / math.sqrt(n), 'ci95_half_width': half,
            'ci95_low': mean - half, 'ci95_high': mean + half,
            'q1_linear': q1, 'median': median, 'q3_linear': q3,
            'minimum': values.min(), 'maximum': values.max()})
    summary = pd.DataFrame(summaries)
    sessions = long.groupby(['population', 'session', 'p', 'metric']).amount.agg(
        n_individuals='size', mean='mean', sd_individual_means='std').reset_index()
    between = sessions.groupby(['population', 'p', 'metric'])['mean'].agg(
        n_sessions='size', mean_session_mean='mean', sd_session_means='std').reset_index()
    temporal = records.groupby(['population', 'session', 'p', 'round'])[['entrusted', 'returned']].mean().reset_index()
    tables = {'selected_round_records': records, 'individual_means': means,
              'individual_means_long': long, 'summary': summary, 'session_summary': sessions,
              'between_session_summary': between, 'round_means': temporal}
    for (pop, metric) in PANELS:
        subset = long[(long.population == pop) & (long.metric == metric)]
        wide = pd.DataFrame({f'p={p:g}': pd.Series(subset.loc[subset.p == p, 'amount'].to_numpy()) for p in P_VALUES})
        tables[f'{pop.lower()}_{metric}_wide'] = wide
    for name, table in tables.items():
        table.to_csv(out / f'{name}.csv', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(out / 'Fig3_plot_data.xlsx', engine='openpyxl') as writer:
        for name, table in tables.items():
            table.to_excel(writer, sheet_name=name[:31], index=False)
    sources = hashes + [{'path': str(human_path), 'sha256': human_sha, 'kind': 'Human XLSX'}]
    for source in sources:
        if digest(source['path']) != source['sha256']:
            raise ValueError('Input changed during analysis')
    counts = means.groupby('population').agg(individual_means=('individual', 'size'), sessions=('session', 'nunique'))
    plan = {'schema_version': 1, 'figure': 'Fig. 3 interim reproduction',
        'evidence_role': 'Descriptive comparison of 20-round individual average allocations',
        'layout': '2 rows x 4 columns', 'columns': PANELS,
        'upper': 'Native quartile boxes, all individual-average points, mean lines; no mean CI',
        'lower': 'Mean of individual averages and conventional two-sided 95% t interval',
        'ci_formula': 'mean +/- t(0.975,n_individuals-1)*sample_sd(individual_means)/sqrt(n_individuals)',
        'ci_limitation': 'Assumes independent individual averages; does not account for within-network dependence or estimate between-session uncertainty.',
        'no_operations': ['No smoothing', 'No outlier removal', 'No significance tests', 'No fabricated repeats'],
        'source_columns': {'LLM': column_roles(llm_fields, 'LLM'), 'Human': column_roles(human_fields, 'Human')},
        'source_mapping': {'LLM': {'entrusted': 'total_sent', 'returned': 'total_returned'},
                           'Human': {'entrusted': 'player.send_T', 'returned': 'player.return_T'}},
        'confirmed_choices': 'User interview in Codex, 2026-10-11: first 20 rounds; one mean per individual; Human all 3 sessions; current LLM 1 session; upper no CI; lower CI; separate original palettes; editable Origin/source only.',
        'palettes': {'LLM': LLM_COLORS, 'Human': HUMAN_COLORS},
        'palette_provenance': 'Read from original OPJU: Graph4/round_mean_sent (LLM), Graph8/Graph9 (Human)',
        'display_jitter': 'Deterministic seeded horizontal jitter; Y values unchanged and every point retained',
        'counts': json.loads(counts.to_json(orient='index')),
        'sources': sources, 'configurations': configs,
        'human_cache': human.attrs.get('human_cache', {}),
        'software': {'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__},
        'table_hashes': {name: digest(out / f'{name}.csv') for name in tables}}
    write_json(out / 'analysis_plan.json', plan)
    write_json(out / 'validation.json', {'status': 'passed', 'all_individuals_complete': True,
        'n_records': len(records), 'n_individual_means': len(means),
        'counts_per_population_p': means.groupby(['population', 'p']).size().reset_index(name='n').to_dict('records'),
        'source_files_unchanged': True, 'corrected_llm_decisions_retained': True})
    event('tables_complete', output=str(out), counts=plan['counts'])
    return plan


@contextmanager
def origin_slot():
    """Serialize this renderer with current EditaPlot workers in this session."""
    import tempfile
    from ctypes import wintypes
    lock_path=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'EditaPlot'/'locks'/'origin-automation-v1.lock'
    key=hashlib.sha256(str(lock_path).casefold().encode()).hexdigest()[:24]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Local\\EditaPlot.OriginAutomation.v1.'+key)
    if not handle: raise RuntimeError('Origin job mutex unavailable')
    acquired=False
    started=time.monotonic()
    last_report=-30.0
    try:
        while not acquired:
            result=kernel.WaitForSingleObject(handle,250)
            if result in [0,128]: acquired=True
            elif result==258:
                elapsed=time.monotonic()-started
                if elapsed-last_report>=30:
                    event('origin_job_queue',wait_seconds=round(elapsed))
                    last_report=elapsed
                if elapsed>1800: raise RuntimeError('origin_job_queue_timeout; active holder untouched')
            else: raise RuntimeError('Origin job mutex wait failed')
        yield
    finally:
        if acquired: kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


@contextmanager
def isolated_origin(keep_open):
    """Own a new Origin Application, never attach to a user-owned project."""
    if os.name != 'nt':
        raise RuntimeError('Origin rendering requires physical Windows with Origin 2021+')
    buf = ctypes.create_unicode_buffer(256)
    size = ctypes.c_ulong(len(buf))
    if not ctypes.windll.advapi32.GetUserNameW(buf, ctypes.byref(size)):
        raise RuntimeError('origin_execution_context_unknown: stop before COM')
    if buf.value.casefold().startswith('codexsandbox'):
        raise RuntimeError('origin_codex_sandbox_context: current-user approval required before COM')
    import originpro as op
    if not getattr(op, 'oext', False):
        raise RuntimeError('Run this script with external Python, not inside an existing Origin project')
    owned = False
    succeeded = False
    try:
        try:
            op.set_show(False)  # External originpro creates OriginExt.Application, a NEW instance.
            owned = True
        except Exception:
            try:
                op.exit()
            except Exception:
                raise RuntimeError('origin_activation_cleanup_failed; no retry') from None
            raise RuntimeError('origin_activation_failed; no automatic retry') from None
        if not op.lt_exec('sec -poc 30;') or not float(op.lt_float('run.isOCready()')) >= .5:
            raise RuntimeError('origin_startup_not_ready')
        event('origin_connected', version=float(op.lt_float('@V')))
        op.new(asksave=False)
        yield op
        succeeded = True
    finally:
        if owned:
            if succeeded and keep_open:
                op.set_show(True)
            else:
                op.exit()


def set_label(layer, name, text, size=17, bold=False):
    layer.lt_exec(f'label -n {name} "{text}";')
    layer.lt_exec(f'{name}.font=font(Arial);{name}.fsize={size};{name}.color=1;')
    return layer.label(name)


def style_layer(op, graph, layer, position, limits, panel, heading, bottom):
    layer.activate()
    left, top, width, height = position
    layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.fixed=1;layer.factor=1;layer.maxpts=0;')
    layer.axis('x').set_limits(.5, 5.5, 1)
    layer.axis('y').set_limits(*limits)
    font = int(op.lt_float('font(Arial)'))
    for axis in ['x', 'y']:
        for prop, val in [('showAxes',3),('showLabels',1),('ticks',5),('minorTicks',0),('atZero',0),('label.table',0),('label.type',1),('label.numFormat',1),('label.font',font),('label.rotate',0)]:
            layer.set_int(f'{axis}.{prop}', val)
        layer.set_float(f'{axis}.label.pt', 15)
        layer.set_float(f'{axis}.thickness', 1.1)
        layer.set_float(f'{axis}.tickthickness', 1.1)
    # Numeric centers 1..5; labels come from a worksheet, not categorical reordering.
    ticks = op.find_sheet('w', 'Ticks')
    layer.lt_exec(f'range __p_labels={ticks.lt_range(False)}!col(2);axis -ps X T __p_labels;')
    for axis in ['x','y']:
        layer.set_int(f'{axis}.label.font', font)
        layer.set_float(f'{axis}.label.pt', 15)
    # Box templates retain category tick special-cases in Origin 2021.
    # Five explicit editable tick-text objects give identical labels on all panels.
    layer.set_int('x.showLabels',0)
    layer.set_int('x.showlabel',0)
    layer.set_int('x.label.show',0)
    pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
    for i,p in enumerate(P_VALUES):
        name=f'PLabel{i}'
        lab=set_label(layer,name,f'{p:g}',15)
        layer.lt_exec(f'{name}.attach=1;')
        lab.set_float('left',pw*(left+width*(i+.5)/5)/100-lab.get_float('width')/2)
        lab.set_float('top',ph*(top+height+1.5)/100)
    layer.axis('x').title = 'Fraction of free players, p' if bottom else ''
    layer.axis('y').title = ('Mean ' if bottom else '') + ('entrusted amount' if 'entrusted' in heading.lower() else 'returned amount')
    for name in ['xb','yl']:
        label=layer.label(name)
        if label:
            layer.lt_exec(f'{name}.font=font(Arial);{name}.fsize=17;')
    for name in ['Legend','legend']:
        lab=layer.label(name)
        if lab: layer.remove_label(lab)
    # Page-attached heading and panel letter: stable after merge and resizing.
    for name, text, sx, sy, fs in [
        ('Panel', f'({panel})', left-3.6, top-5.0, 18),
        ('Heading', heading, left+width/2, top-5.0, 17)]:
        lab=set_label(layer,name,text,fs)
        layer.lt_exec(f'{name}.attach=1;')
        pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
        lab.set_float('left',pw*sx/100 - (lab.get_float('width')/2 if name=='Heading' else 0))
        lab.set_float('top',ph*sy/100)
    # Place axis titles in reserved page margins rather than inherited template offsets.
    pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
    for name, cx, cy in [('xb',left+width/2,top+height+8.0),('yl',left-4.0,top+height/2)]:
        lab=layer.label(name)
        if lab:
            layer.lt_exec(f'{name}.attach=1;')
            lab.set_float('left',pw*cx/100-lab.get_float('width')/2)
            lab.set_float('top',ph*cy/100-lab.get_float('height')/2)
    # Origin 2021 repositions its special xb title during a refresh.
    # Use an ordinary editable caption in the reserved lower page margin.
    xb=layer.label('xb')
    if xb: layer.remove_label(xb)
    if bottom:
        caption=set_label(layer,'XCaption','Fraction of free players, p',17)
        layer.lt_exec('XCaption.attach=1;')
        caption.set_float('left',pw*(left+width/2)/100-caption.get_float('width')/2)
        caption.set_float('top',ph*(top+height+7.0)/100)
    layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
    state={'position':{'unit':layer.get_int('unit'),
        'left':float(op.lt_float('layer.left')),'top':float(op.lt_float('layer.top')),
        'width':float(op.lt_float('layer.width')),'height':float(op.lt_float('layer.height'))},
        'geometry_crosscheck':[float(op.lt_float(k)) for k in ['v3','v4','v1','v2']],
        'x_limits':list(layer.xlim),'y_limits':list(layer.ylim),
        'axis_fonts':{k:layer.get_int(f'{k}.label.font') for k in ['x','y']},
        'axis_sizes':{k:layer.get_float(f'{k}.label.pt') for k in ['x','y']},
        'x_tick_labels':ticks.to_list(1), 'plot_count':len(layer.plot_list()),
        'titles':{'x':layer.label('XCaption').text if bottom else '', 'y':layer.axis('y').title}}
    expected=[left,top,width,height]
    actual=[state['position'][k] for k in ['left','top','width','height']]
    if state['position']['unit']!=1 or not np.allclose(actual,expected,atol=.03) or not np.allclose(actual,state['geometry_crosscheck'],atol=.03):
        raise RuntimeError('Origin layer geometry readback failed')
    if any(x!=font for x in state['axis_fonts'].values()):
        raise RuntimeError('Axis font readback failed')
    return state


def render(args, out):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    for source in plan['sources']:
        if digest(source['path']) != source['sha256']:
            raise ValueError('Input hash changed since preparation')
    for name, sha in plan['table_hashes'].items():
        if digest(out/f'{name}.csv') != sha:
            raise ValueError('Prepared table hash changed')
    summary=pd.read_csv(out/'summary.csv')
    long=pd.read_csv(out/'individual_means_long.csv')
    event('origin_render_start', mode='isolated', experimental_probe=args.probe)
    with origin_slot(), isolated_origin(not args.close_origin and not args.probe) as op:
        ticks=op.new_sheet('w','Ticks')
        ticks.from_list(0,[1,2,3,4,5],'Center')
        ticks.from_list(1,['0','0.25','0.5','0.75','1'],'p')
        saved_tables={}
        for table in ['individual_means','summary','session_summary','between_session_summary','round_means']:
            sheet=op.new_sheet('w',table.replace('_','').title()[:20])
            sheet.from_df(pd.read_csv(out/f'{table}.csv'))
            saved_tables[table]=sheet.lt_range(False)
        pages=[]
        roles=[]
        for row in range(2):
            for col,(pop,metric) in enumerate(PANELS):
                colors=LLM_COLORS if pop=='LLM' else HUMAN_COLORS
                rows=summary[(summary.population==pop)&(summary.metric==metric)].sort_values('p')
                if row==0:
                    # Native Origin box plot, linked to the individual-average worksheet.
                    raw=pd.read_csv(out/f'{pop.lower()}_{metric}_wide.csv')
                    wks=op.new_sheet('w',f'{pop}{metric.title()}')
                    wks.from_df(raw)
                    wks.cols_axis('yyyyy')
                    wks.activate()
                    command=f'plotgboxraw irng:={wks.lt_range(False)}!1:5 num:=1 g1:="Long Name" sort:=0 theme:="Box_Dashed Whisker Thick Median";'
                    if not op.lt_exec(command):
                        raise RuntimeError('Origin box graph creation failed')
                    graph=op.find_graph()
                    layer=graph[0]
                    layer.group(False)
                    boxes=layer.plot_list()
                    if len(boxes)!=5: raise RuntimeError('Expected five native boxes')
                    for i,(plot,color) in enumerate(zip(boxes,colors),1):
                        plot.color=color
                        plot.set_cmd(f'-pfb color({box_fill_color(color)})',f'-pbc color({color})','-pbw 0.7')
                        plot.transparency=65
                        plot.symbol_size=0  # Native outlier symbols hidden; overlay retains every observation exactly once.
                        layer.set_int(f'plot{i}.boxchart.type',1)
                        # Origin 2021 modern box-range enum (separate Box Style):
                        # native BCBT_25_75=2, LabTalk's 1-based boxRange=3.
                        # Older web documentation included No Box in this enum;
                        # do not use that obsolete numbering on the tested host.
                        layer.set_int(f'plot{i}.boxchart.boxRange',3)
                        layer.set_int(f'plot{i}.boxchart.line',1)
                        layer.set_float(f'plot{i}.boxchart.width',52)
                    helper=pd.DataFrame()
                    for i,p in enumerate(P_VALUES):
                        values=raw.iloc[:,i].dropna().to_numpy()
                        helper[f'X{i}']=pd.Series(i+1+np.random.default_rng(20261011+i).uniform(-.16,.16,len(values)))
                        helper[f'Y{i}']=pd.Series(values)
                    pts=op.new_sheet('w',f'{pop}{metric.title()}Pts')
                    pts.from_df(helper)
                    pts.cols_axis('xy'*5)
                    for i,color in enumerate(colors):
                        plot=layer.add_plot(pts,2*i+1,2*i,type='s')
                        plot.color=color
                        plot.symbol_kind=2
                        plot.symbol_interior=0 if pop=='LLM' else 1
                        plot.symbol_size=3.5 if pop=='LLM' else 3.2
                        plot.transparency=10 if pop=='LLM' else 18
                    # Explicit mean line, independently editable and unambiguous.
                    meanpoints=pd.DataFrame({f'X{i}':pd.Series([i+.77,i+1.23]) for i in range(5)})
                    for i,value in enumerate(rows['mean']): meanpoints[f'Y{i}']=[value,value]
                    meansheet=op.new_sheet('w',f'{pop}{metric.title()}Mean')
                    meansheet.from_df(meanpoints)
                    for i,color in enumerate(colors):
                        plot=layer.add_plot(meansheet,f'Y{i}',f'X{i}',type='l')
                        plot.color='#245B9A' if pop=='LLM' else color
                        plot.set_cmd('-w 900')
                    kind='box_distribution'
                else:
                    event('lower_panel_start', column=col)
                    graph=op.new_graph(template='Line')
                    layer=graph[0]
                    data=pd.DataFrame({'Center':range(1,6),'p':P_VALUES,
                        'Mean':rows['mean'].to_numpy(),'CI95':rows.ci95_half_width.to_numpy()})
                    wks=op.new_sheet('w',f'{pop}{metric.title()}CI')
                    wks.from_df(data)
                    event('lower_table_imported', column=col)
                    wks.cols_axis('xxyy')
                    connector=layer.add_plot(wks,'Mean','Center',type='l')
                    connector.color='#333333'
                    connector.set_cmd('-w 600','-d 1')
                    event('lower_connector_ready', column=col)
                    for i,color in enumerate(colors):
                        one=op.new_sheet('w',f'CI{col}{i}')
                        center, mean, half = float(i+1), float(rows['mean'].iloc[i]), float(rows.ci95_half_width.iloc[i])
                        # Editable worksheet-linked interval/cap primitives avoid
                        # Origin 2021's unstable one-row add_plot(colyerr) route.
                        one.from_df(pd.DataFrame({'PointX':[center,np.nan,np.nan,np.nan,np.nan,np.nan],
                            'PointY':[mean,np.nan,np.nan,np.nan,np.nan,np.nan],
                            'IntervalX':[center,center,np.nan,np.nan,np.nan,np.nan],
                            'IntervalY':[mean-half,mean+half,np.nan,np.nan,np.nan,np.nan],
                            'CapX':[center-.065,center+.065,np.nan,center-.065,center+.065,np.nan],
                            'CapY':[mean-half,mean-half,np.nan,mean+half,mean+half,np.nan]}))
                        one.cols_axis('xyxyxy')
                        for y,x in [('IntervalY','IntervalX'),('CapY','CapX')]:
                            interval=layer.add_plot(one,y,x,type='l')
                            interval.color=color
                            interval.set_cmd('-w 650')
                        plot=layer.add_plot(one,'PointY','PointX',type='s')
                        plot.color=color
                        plot.symbol_kind=2
                        plot.symbol_interior=1
                        plot.symbol_size=5.0
                    kind='mean_ci'
                graph.name=f'Panel{row*4+col+1}'
                pages.append(graph)
                roles.append({'population':pop,'metric':metric,'kind':kind,'upper_ci':False if row==0 else None})
                event('panel_built', panel=graph.name, population=pop, metric=metric)
        expression='+char(10)$+'.join(f'"{page.name}"' for page in pages)
        if not op.lt_exec(f'merge_graph option:=specified graphs:={expression} keep:=1 arrange:=0 row:=2 col:=4 groupgraph:=1 linkarrange:=0 labeltext:=none;'):
            raise RuntimeError('Origin eight-panel merge failed')
        graph=op.find_graph()
        graph.name='Fig3'
        if len(graph)!=8: raise RuntimeError('Expected eight editable graph layers')
        # 36 x 20 cm working canvas; final resizing should preserve legibility.
        graph.activate()
        op.lt_exec('page.updatetoprinter=0;page.kar=0;page.width=(36/2.54)*page.resx;page.height=(20/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'))
        limits={}
        for metric in ['entrusted','returned']:
            maxval=float(long.loc[long.metric==metric,'amount'].max())
            maxci=float(summary.loc[summary.metric==metric,'ci95_high'].max())
            upper=max(maxval,maxci)
            step=1 if metric=='entrusted' else 2 if upper<=16 else 5
            limits[metric]=(0, math.ceil(upper/step)*step+step*.15, step)
        readback=[]
        for i,(layer,role) in enumerate(zip(graph,roles)):
            row,col=divmod(i,4)
            # Same limits for human/LLM of each metric; no axis breaks.
            heading=f"{role['population']} | {role['metric'].title()}"
            position=(6.4+24.1*col,10.5+46.5*row,17.8,31.0)
            state=style_layer(op,graph,layer,position,limits[role['metric']],chr(97+i),heading,row==1)
            state.update(role)
            state['plots']=[{'range':p.lt_range(),'pid':p.get_int('pid'),
                'rgb':list(p.color),'line_width':p.get_float('line.width')} for p in layer.plot_list()]
            if row==0 and len(state['plots'])!=15:
                raise RuntimeError('Upper panel must contain 5 boxes, 5 scatters and 5 mean lines')
            if row==0:
                state['native_box_ranges']=[plot.get_int('boxchart.boxRange') for plot in layer.plot_list()[:5]]
                state['box_fill_colors']=[box_fill_color(color) for color in (LLM_COLORS if role['population']=='LLM' else HUMAN_COLORS)]
                if state['native_box_ranges']!=[3]*5:
                    raise RuntimeError('Origin box range is not the 25th--75th percentiles')
            readback.append(state)
        graph.activate()
        op.lt_exec('doc -uw;')
        opju=out/'Fig3.opju'
        if not op.save(str(opju)): raise RuntimeError('Origin project save failed')
        for ext in ['png','pdf','tif']:
            graph.save_fig(str(out/f'Fig3.{ext}'),width=4200 if ext!='pdf' else 0)
        artifact_sizes={f'Fig3.{ext}':(out/f'Fig3.{ext}').stat().st_size for ext in ['opju','png','pdf','tif']}
        if any(size<=0 for size in artifact_sizes.values()): raise RuntimeError('Empty export')
        write_json(out/'origin_readback.json',{'status':'pending_saved_project_check',
            'origin_version':float(op.lt_float('@V')),'graph':'Fig3','layers':readback,
            'artifact_sizes':artifact_sizes,'visual_qa':'pending'})
        # Reopen the SAVED OPJU, then verify layer counts and source worksheets.
        if not op.open(str(opju)): raise RuntimeError('Saved OPJU reopen failed')
        saved=op.find_graph('Fig3')
        if saved is None or len(saved)!=8: raise RuntimeError('Saved graph not editable/reopenable')
        for layer in list(saved)[:4]:
            if [plot.get_int('boxchart.boxRange') for plot in layer.plot_list()[:5]]!=[3]*5:
                raise RuntimeError('Saved quartile-box range did not persist')
        expected=pd.read_csv(out/'individual_means.csv')
        saved_sheet=op.find_sheet('w',saved_tables['individual_means'])
        if saved_sheet is None: raise RuntimeError('Saved individual-average workbook missing')
        actual=saved_sheet.to_df()
        if len(actual)!=len(expected): raise RuntimeError('Saved individual table row count differs')
        for col in ['entrusted','returned']:
            if not np.allclose(actual[col],expected[col],atol=1e-12): raise RuntimeError('Saved individual means differ')
        write_json(out/'origin_readback.json',{'status':'passed','experimental_probe':args.probe,
            'origin_version':float(op.lt_float('@V')),'graph':'Fig3','layers':readback,
            'artifact_sizes':artifact_sizes,'saved_project_reopened':True,
            'saved_numeric_data_verified':True,'visual_qa':'pending'})
        for source in plan['sources']:
            if digest(source['path'])!=source['sha256']:raise RuntimeError('Source changed during Origin rendering')
        saved.activate()
    event('origin_complete', output=str(out))


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','render','all'])
    p.add_argument('--human',help='Human original trust-game XLSX')
    p.add_argument('--human-cache-dir',help='Reusable human cache; default: repository/human_experiment_datas')
    p.add_argument('--llm-session',action='append',help='LLM output directory or aggregate agent_rounds.csv; repeat once per independent experiment')
    p.add_argument('--rounds',type=int,default=20)
    p.add_argument('--output-dir',help='New output folder (prepare/all), existing prepared folder (render)')
    p.add_argument('--close-origin',action='store_true',help='Close only the instance created by this script after success')
    p.add_argument('--origin-python',help='Optional separate compatible Python with originpro installed; default uses this Python')
    p.add_argument('--probe',action='store_true',help='Isolated experimental route verification; always close the owned instance')
    return p


def main():
    args=parser().parse_args()
    if args.command in ['prepare','all']:
        if not args.human or not args.llm_session: raise ValueError('--human and at least one --llm-session required')
        if args.rounds!=20: raise ValueError('This confirmed Figure 3 contract uses exactly the first 20 rounds')
        first=Path(args.llm_session[0]).resolve()
        if not first.exists(): raise FileNotFoundError(f'LLM source not found: {first}')
        if not Path(args.human).is_file(): raise FileNotFoundError(f'Human source not found: {args.human}')
        parent=first if first.is_dir() else first.parent
        out=Path(args.output_dir).resolve() if args.output_dir else parent/f'agent_rounds_EditaPlot_{datetime.now():%Y%m%d_%H%M%S}'
        out.mkdir(parents=True,exist_ok=False)
        prepare(args,out)
    else:
        if not args.output_dir: raise ValueError('--output-dir with prepared tables required')
        out=Path(args.output_dir).resolve()
        if (out/'Fig3.opju').exists(): raise ValueError('Existing OPJU will not be overwritten; use a fresh prepared directory')
    if args.command in ['render','all']:
        if args.origin_python:
            command=[str(Path(args.origin_python).resolve()),str(Path(__file__).resolve()),'render','--output-dir',str(out)]
            if args.probe: command.append('--probe')
            if args.close_origin: command.append('--close-origin')
            subprocess.run(command,check=True)
        else:
            render(args,out)
    snapshot=out/'source'
    snapshot.mkdir(exist_ok=True)
    for name in ['fig3.py','human_data_cache.py']:
        shutil.copy2(HERE/name,snapshot/name)
    write_json(out/'source_manifest.json',{'fig3.py_sha256':digest(__file__),
        'human_data_cache.py_sha256':digest(HERE/'human_data_cache.py'),
        'source_path':str(Path(__file__).resolve()),'argv':sys.argv,
        'utc_time':datetime.now().astimezone().isoformat()})
    event('complete',output=str(out))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc) if type(exc).__name__ not in ['com_error', 'COMError'] else 'Origin operation failed (private COM details omitted)'
        event('failed', error_type=type(exc).__name__, message=message)
        raise SystemExit(1) from None
