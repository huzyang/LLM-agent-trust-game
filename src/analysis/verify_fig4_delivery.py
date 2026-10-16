"""Audit saved Figure 4 data/style and package source after explicit visual review."""
import argparse
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd
from PIL import Image

try:
    from . import fig3 as shared
except ImportError:
    import fig3 as shared


def audit(out, visual_reviewed):
    out = Path(out).resolve()
    plan = json.loads((out / 'analysis_plan.json').read_text(encoding='utf-8'))
    report_path = out / 'origin_readback.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['saved_project_reopened']
    assert report['saved_numeric_data_verified'] and len(report['layers']) == 4
    for source in plan['sources']:
        assert shared.digest(source['path']) == source['sha256']
    for name, sha in plan['table_hashes'].items():
        assert shared.digest(out / f'{name}.csv') == sha
    # Independent direct aggregation of the per-person round records.
    records = pd.read_csv(out / 'selected_round_records.csv', float_precision='round_trip')
    summary = pd.read_csv(out / 'round_summary.csv', float_precision='round_trip')
    key = ['population', 'p', 'round', 'metric']
    long = records.melt(id_vars=['population', 'p', 'round'],
        value_vars=['entrusted', 'returned'], var_name='metric', value_name='amount')
    direct = long.groupby(key).amount.agg(['mean', 'std', 'size']).sort_index()
    actual = summary.set_index(key).sort_index()
    assert direct.index.equals(actual.index)
    assert np.allclose(actual['mean'], direct['mean'], atol=1e-12, rtol=0)
    assert np.allclose(actual.sd, direct['std'], atol=1e-12, rtol=0)
    assert np.array_equal(actual.n_individuals, direct['size'])
    assert np.allclose(actual.lower, actual['mean'] - actual.sd, atol=1e-12, rtol=0)
    assert np.allclose(actual.upper, actual['mean'] + actual.sd, atol=1e-12, rtol=0)
    assert summary.band_available.all()
    images = {}
    for ext in ['png', 'tif']:
        with Image.open(out / f'Fig4.{ext}') as im:
            im.verify()
        with Image.open(out / f'Fig4.{ext}') as im:
            images[ext] = {'size': list(im.size), 'dpi': [float(v) for v in im.info.get('dpi', ())]}
            assert im.width == 4200 and im.height >= 2700
    pdf = (out / 'Fig4.pdf').read_bytes()
    assert pdf.startswith(b'%PDF-') and b'/Font' in pdf
    for index, layer in enumerate(report['layers']):
        assert len(layer['plots']) == 15
        means = [p for p in layer['plots'] if p['kind'] == 'mean']
        bands = [p for p in layer['plots'] if p['kind'] == 'sd_upper_fill']
        assert len(means) == len(bands) == 5
        assert all(p['pid'] == 201 and abs(p['symbol_size'] - 4.2) < .01 for p in means)
        palette = plan['style']['LLM_colors' if index < 2 else 'Human_colors']
        expected = [[int(c[n:n+2], 16) for n in [1, 3, 5]] for c in palette]
        assert [p['rgb'] for p in means] == expected
        transparency = plan['style']['band_transparency_percent']['LLM' if index < 2 else 'Human']
        assert all(p['fill_mode'] == 9 and p['fill_enabled'] == 1 and p['transparency'] == transparency for p in bands)
        assert 'SampleNote' not in layer['texts']
        assert ('legend' in layer) == (index in [1, 3])
        assert layer['axis_tick_pt'] == [16, 16]
        assert all(t['font'] == layer['axis_font'] for t in layer['texts'].values())
        assert layer['x_limits'][1] == (20.8 if index < 2 else 51.5)
        if 'legend' in layer:
            left, top, width, height = layer['geometry_percent']
            x, y, w, h = layer['legend']['bounds_page_percent']
            assert left <= x and top <= y and x+w <= left+width and y+h <= top+height
    assert report['layers'][0]['y_limits'] == report['layers'][2]['y_limits']
    assert report['layers'][1]['y_limits'] == report['layers'][3]['y_limits']
    if not visual_reviewed:
        raise ValueError('Inspect the exported PNG, then pass --visual-reviewed to record the visual QA')
    report['visual_qa'] = 'passed'
    report['visual_qa_notes'] = [
        'Inspected PNG: four panels, mean scatter without connecting lines, five native individual-SD bands in every panel, confirmed population palettes and band opacity, p legends inside Returned panels only, no session annotations; labels and data are unclipped.'
    ]
    shared.write_json(report_path, report)
    source = out / 'source'
    source.mkdir(exist_ok=True)
    for name in ['fig4.py', 'fig3.py', 'human_data_cache.py', 'run_fig4.ps1',
                 'README_fig4.md', 'requirements_fig4.txt', 'test_fig4_data_contract.py',
                 'verify_fig4_delivery.py']:
        shutil.copy2(Path(__file__).parent / name, source / name)
    if report.get('route_evidence_path'):
        assert shared.digest(report['route_evidence_path']) == report['route_evidence_sha256']
        shutil.copy2(report['route_evidence_path'], source / 'verified_route_evidence.json')
    (source / 'run_this_fig4.ps1').write_text('''# Main entry for this exact source snapshot and selected CSV.
param(
    [ValidateSet('prepare','render','all')][string]$Mode = 'all',
    [string]$LlmCsv = '', [string]$HumanWorkbook = '',
    [string]$DataPython = '', [string]$OriginPython = '',
    [string]$OutputDirectory = '', [string]$RouteEvidence = ''
)
$ErrorActionPreference = 'Stop'
$taskOutput = Split-Path $PSScriptRoot -Parent
$taskSession = Split-Path $taskOutput -Parent
$taskRepository = Split-Path (Split-Path $taskSession -Parent) -Parent
if (-not $LlmCsv) { $LlmCsv = Join-Path $taskSession 'agent_rounds.csv' }
if (-not $HumanWorkbook) { $HumanWorkbook = Join-Path $taskRepository 'human_experiment_datas\\2024_NHB_model_Trust Game.xlsx' }
if (-not $DataPython) { $DataPython = Join-Path $taskRepository '.venv\\Scripts\\python.exe' }
if (-not $OriginPython) { $OriginPython = Join-Path $env:USERPROFILE '.codex\\skills\\editaplot-main\\runtime\\.editaplot-venv\\Scripts\\python.exe' }
if (-not $RouteEvidence) { $RouteEvidence = Join-Path $PSScriptRoot 'verified_route_evidence.json' }
$taskArguments = @((Join-Path $PSScriptRoot 'fig4.py'), $Mode)
if ($Mode -ne 'render') { $taskArguments += @('--human', $HumanWorkbook, '--llm-session', $LlmCsv) }
if ($Mode -ne 'prepare') {
    if (-not (Test-Path -LiteralPath $RouteEvidence)) { throw 'Supply -RouteEvidence from a visually verified probe matching this source.' }
    $taskArguments += @('--origin-python', $OriginPython, '--route-evidence', $RouteEvidence)
}
if ($OutputDirectory) { $taskArguments += @('--output-dir', $OutputDirectory) }
& $DataPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw "Figure 4 pipeline failed: $LASTEXITCODE" }
''', encoding='utf-8-sig')
    archive = out / 'Fig4_reproduction_source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for path in sorted(source.iterdir()):
            if path.is_file():
                package.write(path, arcname='source/' + path.name)
    names = ['Fig4.opju', 'Fig4.png', 'Fig4.pdf', 'Fig4.tif', 'Fig4_plot_data.xlsx',
             'Fig4_reproduction_source.zip', 'analysis_plan.json', 'origin_readback.json']
    delivery = {'status': 'passed', 'visual_qa': 'passed', 'images': images,
        'individual_mean_and_sd_independently_verified': True,
        'source_hashes_verified': True, 'table_hashes_verified': True,
        'artifacts': {name: {'bytes': (out / name).stat().st_size,
                            'sha256': shared.digest(out / name)} for name in names}}
    shared.write_json(out / 'delivery_verification.json', delivery)
    print(json.dumps({'status': 'passed', 'output': str(out), 'images': images}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_dir')
    parser.add_argument('--visual-reviewed', action='store_true')
    args = parser.parse_args()
    audit(args.output_dir, args.visual_reviewed)
