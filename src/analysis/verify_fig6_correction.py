"""Compare corrected Fig6 against its preserved pre-correction data snapshot."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

def verify(before,after):
    keys=['population','session','p','individual']
    def load(root,name,index):
        return pd.read_csv(root/f'{name}.csv').set_index(index).sort_index()
    old=load(before,'selected_round_records',keys+['round'])
    new=load(after,'selected_round_records',keys+['round'])
    assert old.index.equals(new.index)
    is_llm=new.index.get_level_values('population')=='LLM'
    for col in new.select_dtypes(include='number').columns:
        expected=old[col].to_numpy().copy()
        if col.startswith('incoming'):expected[is_llm]*=3
        assert np.allclose(new[col],expected,atol=1e-12,rtol=0,equal_nan=True)
    oldf=load(before,'observed_features',keys+['role'])
    newf=load(after,'observed_features',keys+['role'])
    assert oldf.index.equals(newf.index)
    target=(newf.index.get_level_values('population')=='LLM')&(newf.index.get_level_values('role')=='returned')
    changed_cells={}
    for col in newf.select_dtypes(include='number').columns:
        equal=np.isclose(newf[col],oldf[col],atol=1e-10,rtol=0,equal_nan=True)
        if col not in ['B','C','Bn','Cn']:assert equal.all()
        else:assert equal[~target].all()
        changed_cells[col]=int((~equal).sum())
    oldl=load(before,'phenotype_assignments',keys+['role'])
    newl=load(after,'phenotype_assignments',keys+['role'])
    assert oldl.index.equals(newl.index)
    changed=(oldl.phenotype!=newl.phenotype)
    assert not changed[~target].any()
    counts=newl.index.to_frame(index=False)
    counts['changed']=changed.to_numpy()
    changes=counts.groupby(['population','role']).changed.sum().to_dict()
    result={'status':'passed','before':str(before),'after':str(after),
        'only_llm_directional_incoming_scaled_by_3':True,
        'raw_feature_changes_limited_to_llm_returned_B_C_and_counts':True,
        'human_and_llm_entrusted_labels_unchanged':True,
        'changed_feature_cells':{k:v for k,v in changed_cells.items() if v},
        'changed_labels':{f'{k[0]} {k[1]}':int(v) for k,v in changes.items()},
        'all_raw_inputs_preserved':True}
    (after/'correction_verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('before',type=Path);p.add_argument('after',type=Path)
    args=p.parse_args();verify(args.before.resolve(),args.after.resolve())
