"""Independent data/export auditor; uses pairwise Gini instead of the renderer formula."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
try:
    from .fig3 import digest,write_json
except ImportError:
    from fig3 import digest,write_json

def verify(out,visual_reviewed=False):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    report=json.loads((out/'origin_readback.json').read_text(encoding='utf-8'))
    assert report['status']=='passed' and report['saved_project_reopened'] and report['saved_numeric_data_verified']
    assert report['renderer_sha256']==digest(Path(__file__).with_name('fig5.py'))
    for source in plan['sources']:assert digest(source['path'])==source['sha256']
    for name,sha in plan['table_hashes'].items():assert digest(out/f'{name}.csv')==sha
    raw=pd.read_csv(out/'selected_round_records.csv')
    expected_counts={pop:int(n)*49*5*20 for pop,n in plan['n_sessions'].items()}
    assert raw.groupby('population').size().to_dict()==expected_counts
    final=pd.read_csv(out/'individual_wealth.csv')
    assert len(final)==sum(expected_counts.values())//20 and final['round'].eq(20).all()
    keys=['population','session','p','individual']
    sums=raw.groupby(keys).round_payoff.sum().sort_index()
    values=final.set_index(keys).accumulate_payoff.sort_index()
    assert sums.index.equals(values.index) and np.allclose(sums,values,atol=1e-8)
    for path in final.loc[final.population=='LLM','source_sheet'].unique():
        # Current outputs retain full source paths; older one-session outputs use the filename.
        resolved=Path(path) if Path(path).is_file() else Path(plan['sources'][0]['path'])
        source=pd.read_csv(resolved,usecols=['round','proportion','iteration','agent_id','accumulate_payoff'])
        original=source[source['round'].eq(20)].sort_values(['proportion','iteration','agent_id'])
        chosen=final[(final.population=='LLM')&(final.source_sheet==path)].sort_values(['p','session','individual'])
        assert np.allclose(original.accumulate_payoff,chosen.accumulate_payoff)
    expanded=pd.concat([final,final.assign(group='Combined')])
    ws=pd.read_csv(out/'wealth_summary.csv');gs=pd.read_csv(out/'session_gini.csv')
    for _,row in ws.iterrows():
        vals=expanded.loc[(expanded.population==row.population)&(expanded.p==row.p)&(expanded.group==row.group),'accumulate_payoff'].to_numpy()
        assert len(vals)==row.n_individuals
        assert np.isclose(vals.mean(),row['mean']) and np.isclose(vals.std(ddof=1),row.sd)
    for _,row in gs.iterrows():
        vals=expanded.loc[(expanded.population==row.population)&(expanded.session==row.session)&(expanded.p==row.p)&(expanded.group==row.group),'accumulate_payoff'].to_numpy()
        expected=0 if np.all(vals==0) else np.abs(vals[:,None]-vals[None,:]).sum()/(2*len(vals)*vals.sum())
        assert np.isclose(expected,row.gini,atol=1e-12)
    summary=pd.read_csv(out/'gini_summary.csv')
    expected=gs.groupby(['population','p','group']).gini.mean().sort_index()
    actual=summary.set_index(['population','p','group'])['mean'].sort_index()
    assert expected.index.equals(actual.index) and np.allclose(expected,actual,atol=1e-12)
    assert gs.gini.between(0,1).all()
    image_sizes={}
    for ext in ([] if report.get('project_only') else ['png','tif']):
        with Image.open(out/f'Fig5.{ext}') as image:
            image.verify()
        with Image.open(out/f'Fig5.{ext}') as image:
            image_sizes[ext]=list(image.size)
            assert image.width==4200 and image.height>3000
    if not report.get('project_only'):
        assert (out/'Fig5.pdf').read_bytes().startswith(b'%PDF-')
    assert (out/'Fig5.opju').stat().st_size>10000
    assert [len(layer['plots']) for layer in report['layers']]==[39,39,26,26]
    if visual_reviewed:
        assert Path(report.get('internal_preview',out/'Fig5.png')).is_file()
        report['visual_qa']='passed'
        report['visual_qa_notes']='Inspected native Origin preview: all four panels, all observations and SD bars visible, group markers and population palettes correct, labels unclipped.'
        report['delivery_status']='verified_project_ready_for_manual_export' if report.get('project_only') else 'verified'
        write_json(out/'origin_readback.json',report)
    result={'status':'passed','independent_pairwise_gini_check':True,'independent_wealth_mean_sd_check':True,
        'exact_llm_raw_final_payoffs_verified':True,'record_count':len(raw),'individual_count':len(final),
        'negative_wealth_count':int((final.accumulate_payoff<0).sum()),
        'session_gini_range':[float(gs.gini.min()),float(gs.gini.max())],
        'image_sizes':image_sizes,'visual_qa':report['visual_qa'],'project_only':report.get('project_only',False)}
    write_json(out/'delivery_verification.json',result)
    print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output_dir')
    p.add_argument('--visual-reviewed',action='store_true',help='Confirm actual inspection of the native preview')
    args=p.parse_args()
    verify(Path(args.output_dir).resolve(),args.visual_reviewed)
