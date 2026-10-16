"""Independent raw-data and native-readback audit for the complete three-session Fig3."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import t
try:
    from .fig3 import digest,write_json
except ImportError:
    from fig3 import digest,write_json

def verify(out):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    audit=json.loads((out/'provenance_audit.json').read_text(encoding='utf-8'))
    raw_parts=[]
    for i,s in enumerate(audit['sessions'],1):
        assert digest(s['selected_csv'])==s['selected_csv_sha256']==digest(s['original_csv'])
        d=pd.read_csv(s['selected_csv']);assert len(d)==4900
        d['population']='LLM';d['session']=d.iteration.map(lambda n:f'llm_{i}_iteration_{int(n)}')
        d=d.rename(columns={'proportion':'p','agent_id':'individual','total_sent':'entrusted','total_returned':'returned'})
        raw_parts.append(d)
    llm=pd.concat(raw_parts,ignore_index=True)
    ids=['population','session','p','individual']
    expected=llm.groupby(ids)[['entrusted','returned']].mean().sort_index()
    means=pd.read_csv(out/'individual_means.csv')
    actual=means[means.population=='LLM'].set_index(ids)[['entrusted','returned']].sort_index()
    assert expected.index.equals(actual.index) and np.allclose(expected,actual,atol=1e-12)
    records=pd.read_csv(out/'selected_round_records.csv')
    assert len(records)==29400 and len(means)==1470
    assert records.groupby(ids)['round'].agg(['min','max','size']).eq([1,20,20]).all().all()
    assert means.groupby(['population','p']).size().eq(147).all()
    assert means.groupby('population').session.nunique().eq(3).all()
    all_expected=records.groupby(ids)[['entrusted','returned']].mean().sort_index()
    assert np.allclose(all_expected,means.set_index(ids)[['entrusted','returned']].sort_index(),atol=1e-12)
    summary=pd.read_csv(out/'summary.csv')
    for _,r in summary.iterrows():
        vals=means.loc[(means.population==r.population)&(means.p==r.p),r.metric].to_numpy()
        half=t.ppf(.975,len(vals)-1)*vals.std(ddof=1)/np.sqrt(len(vals))
        assert len(vals)==r.n_individuals==147 and r.n_sessions==3
        assert np.isclose(vals.mean(),r['mean'],atol=1e-12)
        assert np.isclose(half,r.ci95_half_width,atol=1e-12)
        assert np.allclose(np.quantile(vals,[.25,.5,.75]),r[['q1_linear','median','q3_linear']].to_numpy(dtype=float),atol=1e-12)
    for source in plan['sources']:assert digest(source['path'])==source['sha256']
    for name,sha in plan['table_hashes'].items():assert digest(out/f'{name}.csv')==sha
    report_path=out/'origin_readback.json';native=None
    if report_path.exists():
        native=json.loads(report_path.read_text(encoding='utf-8'))
        assert native['status']=='passed' and native['saved_all_numeric_data_verified'] and native['saved_scatter_colours_verified']
        assert len(native['layers'])==8
        llm_colors=['#0072B2','#E69F00','#009E73','#CC79A7','#D55E00']
        for index in [0,2,4,6]:
            plots=native['layers'][index]['plots']
            selected=plots[5:10] if index<4 else [plots[3+3*i] for i in range(5)]
            assert [x['rgb'] for x in selected]==[[int(c[j:j+2],16) for j in [1,3,5]] for c in llm_colors]
        for index in [0,2,4,6]:assert np.allclose(native['layers'][index]['y_limits'],native['layers'][index+1]['y_limits'])
    result={'status':'passed','three_raw_llm_csvs_verified':True,'raw_records':len(records),'individual_means':len(means),
        'individuals_per_population_p':147,'sessions_per_population':3,'mean_quartile_ci_recomputation':True,
        'source_and_table_hashes_verified':True,'native_readback_checked':native is not None,
        'visual_qa':native.get('visual_qa') if native else 'pending'}
    write_json(out/'data_verification.json',result);print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output_dir');a=p.parse_args();verify(Path(a.output_dir).resolve())
