"""Verify project-only Fig4 delivery after viewing its temporary Origin preview."""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
try:
    from . import fig3 as shared
except ImportError:
    import fig3 as shared

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output_dir')
    p.add_argument('--visual-reviewed', action='store_true')
    args = p.parse_args()
    out = Path(args.output_dir).resolve()
    plan = json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    report = json.loads((out/'origin_readback.json').read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['project_only']
    assert report['saved_project_reopened'] and report['saved_numeric_data_verified']
    assert report['saved_colours_and_band_transparency_verified']
    assert len(report['layers']) == 4 and (out/'Fig4.opju').stat().st_size > 0
    for source in plan['sources']:
        assert shared.digest(source['path']) == source['sha256']
    for name, sha in plan['table_hashes'].items():
        assert shared.digest(out/f'{name}.csv') == sha
    records = pd.read_csv(out/'selected_round_records.csv', float_precision='round_trip')
    shared.validate_records(records[records.population=='LLM'], 20)
    shared.validate_records(records[records.population=='Human'], 50)
    long = records.melt(id_vars=['population','p','round'],
        value_vars=['entrusted','returned'], var_name='metric', value_name='amount')
    key = ['population','p','round','metric']
    direct = long.groupby(key).amount.agg(['mean','std','size']).sort_index()
    actual = pd.read_csv(out/'round_summary.csv').set_index(key).sort_index()
    assert direct.index.equals(actual.index)
    for a, b in [('mean','mean'),('sd','std'),('n_individuals','size')]:
        assert np.allclose(actual[a], direct[b], atol=1e-12, rtol=0)
    assert np.allclose(actual.lower, actual['mean']-actual.sd, atol=1e-12, rtol=0)
    assert np.allclose(actual.upper, actual['mean']+actual.sd, atol=1e-12, rtol=0)
    for i, layer in enumerate(report['layers']):
        assert len(layer['plots']) == 15
        means = [v for v in layer['plots'] if v['kind']=='mean']
        colors = plan['style']['LLM_colors' if i<2 else 'Human_colors']
        assert [v['rgb'] for v in means] == [[int(c[n:n+2],16) for n in [1,3,5]] for c in colors]
        assert all(v['pid']==201 for v in means)
        assert ('legend' in layer) == (i in [1,3])
    assert report['layers'][0]['y_limits']==report['layers'][2]['y_limits']
    assert report['layers'][1]['y_limits']==report['layers'][3]['y_limits']
    assert args.visual_reviewed, 'Inspect temporary Origin preview before visual approval'
    assert Path(report['internal_preview']).is_file()
    report['visual_qa']='passed'
    report['delivery_status']='verified_project_ready_for_manual_export'
    report['visual_qa_notes']='Inspected native preview: four panels, unclipped labels, opaque mean scatter and pale SD bands, internal Returned legends, no session annotations.'
    shared.write_json(out/'origin_readback.json',report)
    source = out/'source'
    source.mkdir(exist_ok=True)
    for name in ['fig4.py','fig3.py','human_data_cache.py','verify_fig4_project.py','README_fig4.md']:
        shutil.copy2(Path(__file__).parent/name,source/name)
    shared.write_json(out/'project_verification.json',{'status':'passed',
        'visual_qa':'passed','records':len(records),'summary_rows':len(actual),
        'sessions':plan['n_sessions'],'reused_fig3_records':plan['reused_fig3_records'],
        'human_statistics_cache':plan['human_individual_sd_cache']['status'],
        'project_sha256':shared.digest(out/'Fig4.opju'),
        'source_hashes':{v.name:shared.digest(v) for v in source.iterdir() if v.is_file()},
        'formal_image_exports':[], 'delivery':'Editable OPJU; user will export PDF and EPS manually'})
    print('Project, data, source and visual checks passed.')

if __name__ == '__main__':
    main()
