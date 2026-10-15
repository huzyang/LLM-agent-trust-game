"""主脚本 / Main entry point: raw data -> round tables -> editable Origin Figure 4.

LLM: all 20 rounds; Human: all 50 rounds. At each condition and round,
pool individual amounts across the selected sessions. Scatter shows the mean;
bands show +/-1 sample SD of individual amounts (ddof=1), not a confidence interval.
No smoothing, fitting, exclusions, imputation or convergence test.
Run: python -m src.analysis.fig4 --help; Windows: run_fig4.ps1.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd

try:
    from . import fig3 as shared
except ImportError:
    import fig3 as shared

PANELS = [('LLM', 'entrusted'), ('LLM', 'returned'),
          ('Human', 'entrusted'), ('Human', 'returned')]
P_VALUES = shared.P_VALUES
PAGE_CM = (28, 23)
POSITIONS = [(10, 12, 35, 29), (61, 12, 35, 29),
             (10, 62, 35, 29), (61, 62, 35, 29)]


def summarise_rounds(records):
    """Describe per-round individual dispersion; do not infer independent repeats."""
    identifiers = ['population', 'session', 'p', 'round']
    sessions = records.groupby(identifiers)[['entrusted', 'returned']].mean().reset_index()
    counts = records.groupby(identifiers).size().rename('n_individuals').reset_index()
    sessions = sessions.merge(counts, on=identifiers, validate='one_to_one')
    long = records.melt(id_vars=identifiers + ['individual'],
                         value_vars=['entrusted', 'returned'],
                         var_name='metric', value_name='amount')
    summary = long.groupby(['population', 'p', 'round', 'metric']).agg(
        n_sessions=('session', 'nunique'), n_individuals=('amount', 'size'),
        mean=('amount', 'mean'), sd=('amount', 'std')).reset_index()
    summary['lower'] = summary['mean'] - summary['sd']
    summary['upper'] = summary['mean'] + summary['sd']
    summary['band_available'] = summary.n_individuals >= 2
    return sessions, summary


def summarise_human_cached(records):
    """Persist the newly requested individual-SD tables beside the cleaned cache."""
    try:
        from . import human_data_cache as cache
    except ImportError:
        import human_data_cache as cache
    provenance = records.attrs.get('human_cache', {})
    if not provenance.get('table_path'):
        return (*summarise_rounds(records), {'status': 'not_cached'})
    view = Path(provenance['table_path']).parent
    identity = {
        'selected_records_sha256': provenance['table_sha256'],
        'aggregation_sha256': hashlib.sha256(inspect.getsource(summarise_rounds).encode()).hexdigest(),
        'pandas': pd.__version__,
        'definition': 'Pooled individual amounts per condition and round; sample SD, ddof=1',
    }
    paths = [view / 'fig4_session_round_means.csv', view / 'fig4_individual_round_summary.csv']
    manifest_path = view / 'fig4_individual_sd_manifest.json'
    with cache._lock(view.parent / '.cache.lock'):
        manifest = cache._read_json(manifest_path)
        valid = manifest.get('identity') == identity and all(
            cache._valid_file(path, manifest.get('hashes', {}).get(path.name)) for path in paths)
        if valid:
            tables = [cache._read_csv(path) for path in paths]
            status = 'hit'
        else:
            tables = summarise_rounds(records)
            for path, table in zip(paths, tables):
                cache._write_csv(path, table)
            cache._write_json(manifest_path, {'identity': identity,
                'hashes': {path.name: shared.digest(path) for path in paths}})
            status = 'tables_prepared'
    result = {'status': status, 'manifest': str(manifest_path), **identity}
    shared.event('human_fig4_individual_sd_cache', **result)
    return (*tables, result)


def plotting_tables(summary):
    tables = {}
    for population, metric in PANELS:
        part = summary[(summary.population == population) & (summary.metric == metric)]
        table = pd.DataFrame({'Round': sorted(part['round'].unique())})
        for i, p in enumerate(P_VALUES):
            rows = part[part.p == p].sort_values('round')
            if not np.array_equal(rows['round'], table.Round):
                raise ValueError('Incomplete condition/round summary')
            for source, suffix in [('mean', 'Mean'), ('sd', 'SD'),
                                   ('lower', 'Lower'), ('upper', 'Upper')]:
                table[f'P{i}{suffix}'] = rows[source].to_numpy()
        tables[f'{population.lower()}_{metric}'] = table
    return tables


def prepare(args, out):
    shared.event('read_raw_data')
    human_path = Path(args.human).resolve()
    human_hash = shared.digest(human_path)
    human, human_fields = shared.load_human(human_path, 50, getattr(args, 'human_cache_dir', None))
    llm, sources, configs, llm_fields = shared.load_llm(args.llm_session, 20)
    shared.validate_records(human, 50)
    shared.validate_records(llm, 20)
    if human.session.nunique() != 3:
        raise ValueError('Confirmed human contract requires three independent sessions')
    records = pd.concat([llm, human], ignore_index=True)
    llm_sessions, llm_summary = summarise_rounds(llm)
    human_sessions, human_summary, human_sd_cache = summarise_human_cached(human)
    sessions = pd.concat([llm_sessions, human_sessions], ignore_index=True)
    summary = pd.concat([llm_summary, human_summary], ignore_index=True)
    tables = {'selected_round_records': records, 'session_round_means': sessions,
              'round_summary': summary, **plotting_tables(summary)}
    for name, table in tables.items():
        table.to_csv(out / f'{name}.csv', index=False, encoding='utf-8-sig')
    with pd.ExcelWriter(out / 'Fig4_plot_data.xlsx', engine='openpyxl') as writer:
        for name, table in tables.items():
            table.to_excel(writer, sheet_name=name[:31], index=False)
    sources.append({'path': str(human_path), 'sha256': human_hash, 'kind': 'Human XLSX'})
    for source in sources:
        if shared.digest(source['path']) != source['sha256']:
            raise ValueError('Source changed during preparation')
    plan = {'schema_version': 1, 'figure': 'Fig. 4 interim reproduction',
        'purpose': 'Compare observed round-by-round entrusted and returned allocations across p conditions and populations.',
        'layout': '2 rows x 2 columns; LLM top, Human bottom; entrusted left, returned right',
        'rounds': {'LLM': 20, 'Human': 50}, 'p_values': P_VALUES,
        'n_sessions': {'LLM': int(llm.session.nunique()), 'Human': 3},
        'aggregation': 'At each p and round, pool individual outgoing totals across selected sessions; mean and sample SD of those individual amounts. Session/player keys remain distinct.',
        'band': 'mean +/- sample SD of individual amounts at each p and round; ddof=1; descriptive behavioural dispersion, not a confidence interval or between-session uncertainty',
        'user_confirmed': ['2x2 layout', 'LLM 20 rounds; Human full 50 rounds',
                           'All four panels: mean scatter without connecting lines and +/-1 individual SD shading',
                           'Legends inside the right-hand Returned panels only; no session-count annotations',
                           'Existing LLM and Nature human palettes'],
        'no_operations': ['No smoothing', 'No fitting', 'No convergence assertion',
                          'No outlier removal', 'No fabricated repeats', 'No significance tests'],
        'sources': sources, 'configurations': configs,
        'human_cache': human.attrs.get('human_cache', {}),
        'human_individual_sd_cache': human_sd_cache,
        'column_roles': {'LLM': shared.column_roles(llm_fields, 'LLM'),
                         'Human': shared.column_roles(human_fields, 'Human')},
        'style': {'page_cm': PAGE_CM, 'positions_percent': POSITIONS,
                  'LLM_colors': shared.LLM_COLORS, 'Human_colors': shared.HUMAN_COLORS,
                  'mean_mark': 'scatter', 'symbol_size_pt': 4.2,
                  'band_transparency_percent': 88, 'legend_pt': 14,
                  'legend_location': 'inside Returned panels, above data',
                  'session_count_labels': False,
                  'font': 'Arial', 'tick_pt': 16, 'title_pt': 18},
        'route': 'experimental four-panel Origin composition; must pass isolated probe before formal rendering',
        'table_hashes': {name: shared.digest(out / f'{name}.csv') for name in tables}}
    for population, axis_name in [('LLM', 'round'), ('Human', 'subsession.round_number')]:
        for column in plan['column_roles'][population]:
            if column['column'] == axis_name:
                column.update(role='render_primary', purpose='Observed round number on the X axis')
            elif population == 'LLM' and column['column'] == 'proportion':
                column.update(role='render_secondary', purpose='Nominal condition encoded by curve color')
    shared.write_json(out / 'analysis_plan.json', plan)
    shared.write_json(out / 'validation.json', {'status': 'passed',
        'records': {'LLM': len(llm), 'Human': len(human)}, 'session_round_rows': len(sessions),
        'summary_rows': len(summary), 'source_hashes_verified': True,
        'all_individual_sd_bands_available': bool(summary.band_available.all()),
        'band_unit': 'individual amounts within each condition and round',
        'individuals_per_session_condition_round': 49})
    # Three-session human averages should reproduce the existing Origin reference,
    # which is independent of the newly approved uncertainty calculation.
    if args.reference_dir:
        comparisons = {}
        for metric, filename in [('entrusted', 'Book2_Sheet2.csv'), ('returned', 'Book2_Sheet3.csv')]:
            reference = pd.read_csv(Path(args.reference_dir) / filename)
            actual = tables[f'human_{metric}'][[f'P{i}Mean' for i in range(5)]].to_numpy()
            error = float(np.max(np.abs(actual - reference.iloc[:, 1:6].to_numpy())))
            if actual.shape != (50, 5) or error > 1e-8:
                raise ValueError('Human 50-round means disagree with original Origin reference')
            comparisons[metric] = {'max_absolute_difference': error, 'rounds': 50}
        shared.write_json(out / 'human_reference_validation.json', comparisons)
    notes = f'''# Figure 4 reproduction

Main script: src/analysis/fig4.py. LLM rounds 1–20; Human rounds 1–50.

At each p and round, scatter shows the mean of individual outgoing totals. Shading is ±1 sample SD of those individual amounts (ddof=1). Human participants are pooled across all three sessions, using (session, individual) as the identity; repeated rounds are not pooled. This band describes behavioural dispersion, not a confidence interval or between-session uncertainty. It is not divided by sqrt(n). Exact mean ±SD bounds are retained, including bounds outside the possible range of individual amounts.

LLM data contain {llm.session.nunique()} session(s), 49 agents per condition per round. Human data contain three sessions, 147 individuals per condition per round. Session counts are retained in provenance and are not annotated on the figure. No independent repeats are invented.

No connecting lines between mean scatter points. Shading connects adjacent round bounds only for display; no smoothing, fitting, normalization, exclusion or convergence test. Entrusted and returned amounts are total outgoing amounts to four neighbours. Nominal p values and the original population palettes are retained. The two internal legends are in the Returned panels.

Suggested caption: Temporal dynamics of entrusted (a, c) and returned (b, d) amounts under five nominal fractions of free players. Points show the mean individual amount at each round; shaded bands show ±1 sample standard deviation across individuals. LLM agents (a, b) were observed over 20 rounds and human participants (c, d) over 50 rounds. Human observations are pooled across the three sessions.
'''
    (out / 'Fig4_notes.md').write_text(notes, encoding='utf-8')
    shared.event('data_prepared', output=str(out), llm_records=len(llm), human_records=len(human))


def style_panel(op, graph, layer, index, limits, n_sessions):
    population, metric = PANELS[index]
    layer.activate()
    left, top, width, height = POSITIONS[index]
    layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.fixed=1;layer.factor=1;layer.maxpts=0;')
    rounds = 20 if population == 'LLM' else 50
    layer.axis('x').set_limits(0, rounds + (.8 if rounds == 20 else 1.5), 5 if rounds == 20 else 10)
    layer.axis('y').set_limits(*limits)
    font = int(op.lt_float('font(Arial)'))
    for axis in ['x', 'y']:
        for key, value in [('showAxes', 3), ('showLabels', 1), ('ticks', 5),
                           ('minorTicks', 0), ('atZero', 0), ('label.table', 0),
                           ('label.type', 1), ('label.numFormat', 1),
                           ('label.font', font), ('label.rotate', 0)]:
            layer.set_int(f'{axis}.{key}', value)
        layer.set_float(f'{axis}.label.pt', 16)
        layer.set_float(f'{axis}.thickness', 1.0)
        layer.set_float(f'{axis}.tickthickness', 1.0)
    layer.axis('x').title = ''
    layer.axis('y').title = f'Mean total {metric} amount'
    yl = layer.label('yl')
    if yl:
        layer.lt_exec('yl.font=font(Arial);yl.fsize=18;yl.attach=1;')
    for name in ['Legend', 'legend', 'xb']:
        label = layer.label(name)
        if label:
            layer.remove_label(label)
    pw, ph = op.lt_float('page.width'), op.lt_float('page.height')
    if yl:
        yl.set_float('left', pw * (left - 5.6) / 100 - yl.get_float('width') / 2)
        yl.set_float('top', ph * (top + height / 2) / 100 - yl.get_float('height') / 2)
    texts = [('Panel', f'({chr(97 + index)})', left - 3, top - 6, 19, False),
             ('Heading', f'{population} | {metric.title()}', left + width / 2, top - 6, 18, True),
             ('XCaption', 'Round', left + width / 2, top + height + 4.8, 18, True)]
    for name, text, x, y, size, center in texts:
        lab = shared.set_label(layer, name, text, size)
        layer.lt_exec(f'{name}.attach=1;')
        lab.set_float('left', pw * x / 100 - (lab.get_float('width') / 2 if center else 0))
        lab.set_float('top', ph * y / 100)
    layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
    geometry = [float(op.lt_float(f'layer.{name}')) for name in ['left', 'top', 'width', 'height']]
    crosscheck = [float(op.lt_float(k)) for k in ['v3', 'v4', 'v1', 'v2']]
    if layer.get_int('unit') != 1 or not np.allclose(geometry, POSITIONS[index], atol=.03) or not np.allclose(geometry, crosscheck, atol=.03):
        raise RuntimeError('Native panel geometry check failed')
    if any(layer.get_int(f'{axis}.label.font') != font for axis in ['x', 'y']):
        raise RuntimeError('Axis font verification failed')
    return {'population': population, 'metric': metric, 'n_sessions': n_sessions,
            'geometry_percent': geometry, 'layer_x_crosscheck': crosscheck,
            'x_limits': list(layer.xlim), 'y_limits': list(layer.ylim),
            'axis_font': font, 'axis_tick_pt': [layer.get_float(f'{a}.label.pt') for a in ['x', 'y']],
            'texts': {name: {'text': layer.label(name).text,
                              'size': layer.label(name).get_float('fsize'),
                              'font': layer.label(name).get_int('font')}
                      for name in ['Panel', 'Heading', 'XCaption', 'yl']}}


def render(args, out):
    plan = json.loads((out / 'analysis_plan.json').read_text(encoding='utf-8'))
    if plan.get('style', {}).get('mean_mark') != 'scatter' or 'individual amounts' not in plan.get('band', ''):
        raise ValueError('Prepare fresh tables for the confirmed individual-SD scatter contract')
    for source in plan['sources']:
        if shared.digest(source['path']) != source['sha256']:
            raise ValueError('Source hash differs from the prepared plan')
    for name, sha in plan['table_hashes'].items():
        if shared.digest(out / f'{name}.csv') != sha:
            raise ValueError('Prepared table was modified')
    if not args.probe:
        evidence = json.loads(Path(args.route_evidence).read_text(encoding='utf-8')) if args.route_evidence else None
        if not evidence or evidence.get('status') != 'passed' or evidence.get('visual_qa') != 'passed' or not evidence.get('experimental_probe'):
            raise ValueError('Formal rendering requires a visually verified isolated route probe (--route-evidence)')
        if evidence.get('renderer_sha256') != shared.digest(__file__):
            raise ValueError('Renderer changed since route probe; reverify the route')
        if evidence.get('shared_module_sha256') != shared.digest(shared.__file__):
            raise ValueError('Shared loader/lifecycle changed since route probe; reverify the route')
    summary = pd.read_csv(out / 'round_summary.csv')
    limits = {}
    for metric in ['entrusted', 'returned']:
        subset = summary[summary.metric == metric]
        highest = max(subset['mean'].max(), subset.upper.max())
        lowest = min(0.0, subset.lower.min())
        step = 1 if metric == 'entrusted' else 2
        if metric == 'returned':
            highest += (highest - lowest) * .30  # Reserved internal two-row legend space.
        limits[metric] = (math.floor(lowest / step) * step,
                          math.ceil(highest / step) * step + step * .2, step)
    shared.event('origin_render_start', experimental_probe=args.probe)
    with shared.origin_slot(), shared.isolated_origin(not args.close_origin and not args.probe) as op:
        saved_tables = {}
        for i, name in enumerate(['session_round_means', 'round_summary']):
            wks = op.new_sheet('w', f'Audit{i}')
            wks.from_df(pd.read_csv(out / f'{name}.csv'))
            saved_tables[name] = wks.lt_range(False)
        roles = []
        graph = op.new_graph(template='Line')
        graph.name = 'Fig4'
        for index, (population, metric) in enumerate(PANELS):
            data = pd.read_csv(out / f'{population.lower()}_{metric}.csv')
            wks = op.new_sheet('w', f'Trend{index}')
            wks.from_df(data)
            wks.cols_axis('x' + 'y' * (len(data.columns) - 1))
            saved_tables[f'{population.lower()}_{metric}'] = wks.lt_range(False)
            layer = graph[0] if index == 0 else graph.add_layer()
            colors = shared.LLM_COLORS if population == 'LLM' else shared.HUMAN_COLORS
            n_sessions = plan['n_sessions'][population]
            plot_roles = []
            if data[[f'P{i}Upper' for i in range(5)]].notna().all().all():
                for i, color in enumerate(colors):
                    upper = layer.add_plot(wks, f'P{i}Upper', 'Round', type='l')
                    lower = layer.add_plot(wks, f'P{i}Lower', 'Round', type='l')
                    for bound in [upper, lower]:
                        bound.color = color
                        bound.set_cmd('-w 0')
                        bound.transparency = 88
                    plot_roles += [{'kind': 'sd_upper_fill', 'p': P_VALUES[i]},
                                   {'kind': 'sd_lower', 'p': P_VALUES[i]}]
            for i, color in enumerate(colors):
                plot = layer.add_plot(wks, f'P{i}Mean', 'Round', type='s')
                plot.color = color
                plot.symbol_kind = 2
                plot.symbol_interior = 1
                plot.symbol_size = 4.2
                plot_roles.append({'kind': 'mean', 'p': P_VALUES[i]})
            roles.append(plot_roles)
            if len(layer.plot_list()) != len(plot_roles):
                raise RuntimeError(f'Panel construction count differs: panel={index}, expected={len(plot_roles)}, actual={len(layer.plot_list())}')
            shared.event('panel_built', panel=index + 1, population=population, metric=metric)
        if len(graph) != 4:
            raise RuntimeError('Expected four editable layers')
        graph.activate()
        op.lt_exec(f'page.updatetoprinter=0;page.kar=0;page.width=({PAGE_CM[0]}/2.54)*page.resx;page.height=({PAGE_CM[1]}/2.54)*page.resy;doc -uw;')
        graph.set_int('background', op.ocolor('#FFFFFF'))
        readback = []
        for index, layer in enumerate(graph):
            population, metric = PANELS[index]
            state = style_panel(op, graph, layer, index, limits[metric], plan['n_sessions'][population])
            plots = layer.plot_list()
            if len(plots) != len(roles[index]):
                raise RuntimeError(f'Plot count differs from confirmed elements: panel={index}, expected={len(roles[index])}, actual={len(plots)}, ranges={[p.lt_range() for p in plots]}')
            state['plots'] = []
            for i, (plot, role) in enumerate(zip(plots, roles[index])):
                item = {**role, 'range': plot.lt_range(), 'pid': plot.get_int('pid'),
                        'rgb': list(plot.color), 'line_width': plot.get_float('line.width'),
                        'transparency': plot.transparency}
                if role['kind'] == 'mean':
                    # Origin 2021 does not expose plotN.symbol.interior readback.
                    # Verify native scatter type, circle shape and physical size.
                    item.update(symbol_kind=plot.symbol_kind, symbol_size=plot.symbol_size)
                    if item['pid'] != 201:
                        raise RuntimeError('Mean plot is not native scatter')
                if role['kind'] == 'sd_upper_fill':
                    # Apply native upper-to-next-lower fills only after all
                    # curves have been added to the final graph layer.
                    color = (shared.LLM_COLORS if population == 'LLM' else shared.HUMAN_COLORS)[P_VALUES.index(role['p'])]
                    layer.lt_exec(f'range __band = {plot.lt_range()};set __band -pf 1;set __band -pfv 9;set __band -pfb color({color});set __band -p2fb color({color});set __band -pfm 3;set __band -p2fm 3;set __band -paal 1;__fillmode=NA();__fillon=NA();get __band -pfv __fillmode;get __band -pf __fillon;')
                    item['fill_mode'] = float(op.lt_float('__fillmode'))
                    item['fill_enabled'] = float(op.lt_float('__fillon'))
                    if item['fill_mode'] != 9 or item['fill_enabled'] != 1:
                        raise RuntimeError(f'Native between-curve fill readback failed: panel={index}, range={plot.lt_range()}, mode={item["fill_mode"]}, enabled={item["fill_enabled"]}')
                state['plots'].append(item)
            # Separate row-specific legends preserve the different palette mappings.
            if index in [1, 3]:
                n = len(plots) - 5
                entries = [f'\\l({n + i + 1}) p = {p:g}' for i, p in enumerate(P_VALUES)]
                legend_text = '  '.join(entries[:3]) + '\n' + '  '.join(entries[3:])
                legend = shared.set_label(layer, 'PLegend', legend_text, 14)
                layer.lt_exec('PLegend.attach=1;PLegend.background=0;')
                pw, ph = op.lt_float('page.width'), op.lt_float('page.height')
                left, top, width, height = POSITIONS[index]
                legend.set_float('left', pw * (left + width / 2) / 100 - legend.get_float('width') / 2)
                legend.set_float('top', ph * (top + 1.0) / 100)
                state['legend'] = {'text': legend.text, 'font': legend.get_int('font'),
                                   'size': legend.get_float('fsize'),
                                   'bounds_page_percent': [legend.get_float(key) / divisor * 100
                                       for key, divisor in [('left', pw), ('top', ph), ('width', pw), ('height', ph)]]}
                x, y, w, h = state['legend']['bounds_page_percent']
                if not (x >= left and y >= top and x + w <= left + width and y + h <= top + height):
                    raise RuntimeError('Returned legend is not fully inside its panel')
            readback.append(state)
        graph.activate()
        op.lt_exec('doc -uw;')
        dimensions = [float(op.lt_float(f'page.{v}')) / float(op.lt_float(f'page.res{a}')) * 2.54
                      for v, a in [('width', 'x'), ('height', 'y')]]
        if not np.allclose(dimensions, PAGE_CM, atol=.02):
            raise RuntimeError('Physical page dimensions failed')
        project = out / 'Fig4.opju'
        if not op.save(str(project)):
            raise RuntimeError('Origin project save failed')
        for extension in ['png', 'pdf', 'tif']:
            graph.save_fig(str(out / f'Fig4.{extension}'), width=4200 if extension != 'pdf' else 0)
        sizes = {f'Fig4.{ext}': (out / f'Fig4.{ext}').stat().st_size for ext in ['opju', 'png', 'pdf', 'tif']}
        if any(size <= 0 for size in sizes.values()):
            raise RuntimeError('Missing or empty export')
        if not op.open(str(project)):
            raise RuntimeError('Saved project reopen failed')
        saved = op.find_graph('Fig4')
        if saved is None or len(saved) != 4:
            raise RuntimeError('Saved project has no editable four-layer Fig4')
        for index, layer in enumerate(saved):
            if len(layer.plot_list()) != len(roles[index]):
                raise RuntimeError('Saved plot count differs')
            for plot, role in zip(layer.plot_list(), roles[index]):
                if role['kind'] == 'mean' and plot.get_int('pid') != 201:
                    raise RuntimeError('Saved mean plot is not scatter')
                if role['kind'] == 'sd_upper_fill':
                    layer.lt_exec(f'range __savedband={plot.lt_range()};get __savedband -pfv __savedmode;get __savedband -pf __savedfill;')
                    if op.lt_float('__savedmode') != 9 or op.lt_float('__savedfill') != 1:
                        raise RuntimeError('Saved between-curve fill did not persist')
            if layer.label('SampleNote'):
                raise RuntimeError('Unexpected session-count annotation')
            if bool(layer.label('PLegend')) != (index in [1, 3]):
                raise RuntimeError('Saved legend is not restricted to Returned panels')
        for name, address in saved_tables.items():
            sheet = op.find_sheet('w', address)
            if sheet is None:
                raise RuntimeError('Saved source worksheet missing')
            actual = sheet.to_df()
            expected = pd.read_csv(out / f'{name}.csv')
            if len(actual) != len(expected):
                raise RuntimeError('Saved table row count differs')
            for column in expected.select_dtypes(include='number').columns:
                if not np.allclose(actual[column], expected[column], atol=1e-12, equal_nan=True):
                    raise RuntimeError(f'Saved worksheet data differ: {name}/{column}')
        if args.route_evidence and not args.probe and evidence['origin_version'] != float(op.lt_float('@V')):
            raise RuntimeError('Origin version differs from the verified route probe')
        for source in plan['sources']:
            if shared.digest(source['path']) != source['sha256']:
                raise RuntimeError('Raw source changed during rendering')
        shared.write_json(out / 'origin_readback.json', {'status': 'passed',
            'experimental_probe': args.probe, 'origin_version': float(op.lt_float('@V')),
            'renderer_sha256': shared.digest(__file__), 'shared_module_sha256': shared.digest(shared.__file__),
            'route_evidence_path': str(Path(args.route_evidence).resolve()) if args.route_evidence else None,
            'route_evidence_sha256': shared.digest(args.route_evidence) if args.route_evidence else None,
            'layers': readback, 'page_cm': dimensions, 'artifact_sizes': sizes,
            'saved_project_reopened': True, 'saved_numeric_data_verified': True, 'visual_qa': 'pending'})
        saved.activate()
    shared.event('origin_complete', output=str(out))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'render', 'all'])
    p.add_argument('--human', default=str(shared.DEFAULT_HUMAN_WORKBOOK), help='Human trust-game XLSX; defaults to the project human_experiment_datas workbook')
    p.add_argument('--human-cache-dir', help='Reusable human cache; default: repository/human_experiment_datas')
    p.add_argument('--llm-session', action='append')
    p.add_argument('--output-dir')
    p.add_argument('--origin-python')
    p.add_argument('--reference-dir', help='Optional independent 50-round human mean validation')
    p.add_argument('--route-evidence', help='Passed isolated probe origin_readback.json')
    p.add_argument('--probe', action='store_true', help='Isolated experimental full-route verification')
    p.add_argument('--close-origin', action='store_true')
    return p


def main():
    args = parser().parse_args()
    if args.command in ['prepare', 'all']:
        if not args.human or not args.llm_session:
            raise ValueError('--human and --llm-session are required')
        first = Path(args.llm_session[0]).resolve()
        parent = first if first.is_dir() else first.parent
        out = Path(args.output_dir).resolve() if args.output_dir else parent / f'agent_rounds_Fig4_EditaPlot_{datetime.now():%Y%m%d_%H%M%S}'
        out.mkdir(parents=True, exist_ok=False)
        prepare(args, out)
    else:
        if not args.output_dir:
            raise ValueError('render requires a prepared --output-dir')
        out = Path(args.output_dir).resolve()
        if (out / 'Fig4.opju').exists():
            raise ValueError('Existing Origin project will not be overwritten')
    if args.command in ['render', 'all']:
        if args.origin_python:
            command = [args.origin_python, str(Path(__file__).resolve()), 'render', '--output-dir', str(out)]
            for name in ['probe', 'close_origin']:
                if getattr(args, name):
                    command.append('--' + name.replace('_', '-'))
            if args.route_evidence:
                command += ['--route-evidence', args.route_evidence]
            subprocess.run(command, check=True)
        else:
            render(args, out)
    snapshot = out / 'source'
    snapshot.mkdir(exist_ok=True)
    for name in ['fig4.py', 'fig3.py', 'human_data_cache.py', 'run_fig4.ps1', 'requirements_fig4.txt', 'README_fig4.md', 'test_fig4_data_contract.py', 'verify_fig4_delivery.py']:
        source = Path(__file__).resolve().parent / name
        if source.exists():
            shutil.copy2(source, snapshot / name)
    shared.write_json(out / 'source_manifest.json', {'main_script': 'fig4.py',
        'fig4_sha256': shared.digest(__file__), 'shared_module_sha256': shared.digest(shared.__file__),
        'human_cache_module_sha256': shared.digest(Path(__file__).resolve().parent/'human_data_cache.py'),
        'argv': sys.argv, 'created_at': datetime.now().astimezone().isoformat()})
    shared.event('complete', output=str(out))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        message = str(exc) if type(exc).__name__ not in ['com_error', 'COMError'] else 'Origin operation failed (private COM details omitted)'
        shared.event('failed', error_type=type(exc).__name__, message=message)
        raise SystemExit(1) from None
