"""Independent first-version Fig6 data audit; no Origin automation or plotting."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

p=Path(sys.argv[1]);rec=pd.read_csv(p/'selected_round_records.csv');f=pd.read_csv(p/'observed_features.csv')
keys=['population','session','p','individual'];base=rec.sort_values(keys+['round']).copy();g=base.groupby(keys)
plan=json.loads((p/'analysis_plan.json').read_text(encoding='utf-8'))
expected_individuals=sum(plan['n_sessions'].values())*49*5
assert len(base)==expected_individuals*20 and len(f)==expected_individuals*2 and base.groupby(keys).size().eq(20).all()
base['prev_sent']=g.entrusted.shift()
incoming=[f'incoming{i}' for i in range(4)]
base['received']=base[incoming].sum(axis=1);base['prev_received']=base.groupby(keys).received.shift()
base['good_count']=(base[[f'back{i}' for i in range(4)]].to_numpy()>=base[[f'sent{i}' for i in range(4)]].to_numpy()-1e-9).sum(axis=1)
base['prev_good']=base.groupby(keys).good_count.shift()
lag1=base.groupby(keys)[incoming].shift();lag2=base.groupby(keys)[incoming].shift(2)
base['trend_count']=(lag1.to_numpy()>=lag2.to_numpy()-1e-9).sum(axis=1)
base.loc[base['round']<3,'trend_count']=np.nan
checks=0
for role,target,prev,count in [('entrusted','entrusted','prev_sent','prev_good'),('returned','returned','prev_received','trend_count')]:
    masks=[pd.Series(True,index=base.index),base[prev]>=4,base[prev]<4,base[count]<=1,base[count]==2,base[count]>=3]
    actual=f[f.role==role].set_index(keys).sort_index()
    for factor,mask in zip('ABCDEF',masks):
        sums=base.loc[mask].groupby(keys)[target].agg(['mean','size']).reindex(actual.index)
        assert np.allclose(actual[factor],sums['mean'],atol=1e-10,equal_nan=True)
        assert np.array_equal(actual[factor+'n'],sums['size'].fillna(0))
        checks+=len(actual)
labels=pd.read_csv(p/'phenotype_assignments.csv')
assert len(labels)==expected_individuals*2 and not labels.duplicated(keys+['role']).any()
for factor in 'ABCDEF':
    missing=labels[factor].isna()
    assert np.allclose(labels.loc[missing,factor+'_input'],labels.loc[missing,'A'])
    assert np.allclose(labels.loc[~missing,factor+'_input'],labels.loc[~missing,factor])
fractions=pd.read_csv(p/'phenotype_fractions.csv')
assert len(fractions)==60 and np.allclose(fractions.groupby(['population','role','p']).fraction.sum(),1)
for _,row in fractions.iterrows():
    group=labels[(labels.population==row.population)&(labels.role==row.role)&(labels.p==row.p)]
    assert row.n==group.phenotype.eq(row.phenotype).sum() and row.denominator==len(group)
profiles=pd.read_csv(p/'observed_profiles.csv')
for _,row in profiles.iterrows():
    group=labels[(labels.population==row.population)&(labels.role==row.role)&(labels.phenotype==row.phenotype)]
    values=group[row.factor].dropna()
    assert row.n_observed==len(values)
    assert (np.isnan(row.mean_observed) if not len(values) else np.isclose(row.mean_observed,values.mean()))
for pop in ['LLM','Human']:
    for role in ['entrusted','returned']:
        area=pd.read_csv(p/f'{pop.lower()}_{role}_fraction.csv')
        assert len(area)==10 and np.all(np.diff(area.p_step)>=0) and area.p_step.iloc[0]==0 and area.p_step.iloc[-1]==1
        assert np.allclose(area.Top,1) and np.allclose(area.Zero,0)
        assert (area.Prosocial>=0).all() and (area.ProNeutral>=area.Prosocial-1e-12).all() and (area.Top>=area.ProNeutral-1e-12).all()
        table=pd.read_csv(p/f'{pop.lower()}_{role}_profile.csv')
        for i,phen in enumerate(['Prosocial','Neutral','Antisocial']):
            observed=profiles[(profiles.population==pop)&(profiles.role==role)&(profiles.phenotype==phen)].set_index('factor').reindex(list('ABCDEF'))
            assert np.array_equal(table[f'PointX{i}'].iloc[:6].isna(),observed.mean_observed.isna())
plan=json.loads((p/'analysis_plan.json').read_text(encoding='utf-8'))
import hashlib
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
for source in plan['sources']:assert sha(source['path'])==source['sha256']
for name,expected in plan['table_hashes'].items():assert sha(p/f'{name}.csv')==expected
for source in plan['sources']:
    if source.get('kind')!='LLM CSV':continue
    mapping={'entrusted':'total_sent','returned':'total_returned'}
    for i in range(4):
        for target,origin in [('sent','sent_to_n'),('back','received_return_from_n'),('incoming','received_send_from_n')]:
            mapping[f'{target}{i}']=f'{origin}{i+1}'
    original=pd.read_csv(source['path'],usecols=['proportion','agent_id','round','total_received_send']+list(mapping.values()))
    original=original.sort_values(['proportion','agent_id','round'])
    selected=rec[(rec.population=='LLM')&(rec.source_sheet==source['path'])].sort_values(['p','individual','round'])
    assert len(original)==len(selected)
    for target,origin in mapping.items():
        scale=3 if target.startswith('incoming') else 1
        assert np.allclose(selected[target],scale*original[origin],atol=1e-12,rtol=0)
    assert np.allclose(selected[[f'incoming{i}' for i in range(4)]].sum(axis=1),original.total_received_send,atol=1e-8,rtol=0)
    # Independently anchor B/C to the post-tripling aggregate column, not to the conversion helper.
    receipt=pd.Series(original.total_received_send.to_numpy(),index=selected.index)
    work=selected.copy();work['receipt_total']=receipt
    work['previous_receipt_total']=work.groupby(keys).receipt_total.shift()
    actual=f[(f.population=='LLM')&(f.role=='returned')].set_index(keys)
    source_ids=work[keys].drop_duplicates().set_index(keys).index
    actual=actual.loc[source_ids]
    for factor,mask in [('B',work.previous_receipt_total>=4),('C',work.previous_receipt_total<4)]:
        direct=work[mask].groupby(keys).returned.agg(['mean','size']).reindex(actual.index)
        assert np.allclose(actual[factor],direct['mean'],atol=1e-10,equal_nan=True)
        assert np.array_equal(actual[factor+'n'],direct['size'].fillna(0))
result={'status':'passed','individuals':expected_individuals,'role_assignments':len(labels),'raw_records':len(base),
    'independently_recomputed_feature_cells':checks,'imputation_lineage_verified':True,
    'observed_only_profiles_verified':True,'fraction_counts_and_step_helpers_verified':True,
    'incoming_units_checked_against_raw_total_received_send':True,
    'returned_BC_independently_checked_using_post_tripling_aggregate':True}
(p/'data_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))

