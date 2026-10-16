"""MAIN: six-factor behavioural phenotypes, native Origin Fig6, PDF/EPS only.

prepare --llm <CSV>; render --output-dir <prepared> --probe;
all --llm <CSV> --origin-python <exe> --route-evidence <passed probe report>.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
try:
    from . import fig3 as shared
    from . import human_data_cache as cache
except ImportError:
    import fig3 as shared
    import human_data_cache as cache

FACTORS=list('ABCDEF')
PHENOTYPES=['Prosocial','Neutral','Antisocial']
COLORS={'LLM':['#009E73','#E69F00','#D55E00'], 'Human':['#372334','#843B37','#F25A20']}
P_VALUES=shared.P_VALUES
PAGE_CM=(36,24)
POSITIONS=[(5,13,18.333333,27.5),(29,13,19,27.5),(55,13,18.333333,27.5),(79,13,19,27.5),
           (5,63,18.333333,27.5),(29,63,19,27.5),(55,63,18.333333,27.5),(79,63,19,27.5)]
PANELS=[(pop,role,kind) for pop in ['LLM','Human'] for role in ['entrusted','returned'] for kind in ['profile','fraction']]

def read_human(path):
    import openpyxl
    book=openpyxl.load_workbook(path,read_only=True,data_only=True)
    rows=[]
    try:
        for sheet in book:
            m=re.fullmatch(r'TG (0|25|50|75|100)% free session(\d+)',sheet.title)
            if not m:continue
            iterator=sheet.iter_rows(values_only=True);columns=list(next(iterator));ix={k:i for i,k in enumerate(columns)}
            for row in iterator:
                rd=row[ix['subsession.round_number']]
                if rd is None:continue
                item={'population':'Human','session':'human_'+m[2],'p':int(m[1])/100,
                    'individual':int(row[ix['player.id_in_group']]),'round':int(rd),
                    'entrusted':float(row[ix['player.send_T']]),'returned':float(row[ix['player.return_T']]),'source_sheet':sheet.title}
                for i,d in enumerate('LURD'):
                    for key,col,scale in [('sent','send',1),('back','receive_return',1),('incoming','receive_send',3)]:
                        item[f'{key}{i}']=float(row[ix[f'player.{col}_{d}']])*scale
                rows.append(item)
    finally:book.close()
    return pd.DataFrame(rows)

def validate(d,rounds):
    keys=['population','session','p','individual']
    assert not d.duplicated(keys+['round']).any()
    sizes=d.groupby(keys)['round'].agg(['min','max','size'])
    assert ((sizes['min']==1)&(sizes['max']==rounds)&(sizes['size']==rounds)).all()
    assert d.groupby(keys[:3]).individual.nunique().eq(49).all()
    amounts=['entrusted','returned']+[f'{k}{i}' for k in ['sent','back','incoming'] for i in range(4)]
    assert np.isfinite(d[amounts]).all().all() and (d[amounts]>=0).all().all()
    assert np.allclose(d.entrusted,d[[f'sent{i}' for i in range(4)]].sum(axis=1),atol=.021)

def human_cached(path):
    identity={'source_sha256':shared.digest(path),'reader_sha256':hashlib.sha256(inspect.getsource(read_human).encode()).hexdigest(),'schema':1}
    root=path.parent/f'trust_game_phenotypes_{identity["source_sha256"][:16]}_{identity["reader_sha256"][:16]}'
    root.mkdir(exist_ok=True);csv=root/'all_round_directional_records.csv';manifest=root/'source_manifest.json'
    with cache._lock(root/'.cache.lock'):
        old=cache._read_json(manifest)
        hit=old.get('identity')==identity and cache._valid_file(csv,old.get('table_sha256'))
        if hit:d=cache._read_csv(csv)
        else:
            d=read_human(path);validate(d,50)
            assert shared.digest(path)==identity['source_sha256']
            cache._write_csv(csv,d);cache._write_json(manifest,{'identity':identity,'table_sha256':shared.digest(csv),
                'rows':len(d),'participant_information':'not read','incoming_unit':'tokens after tripling'})
    validate(d,50);shared.event('human_phenotype_cache',status='hit' if hit else 'prepared',path=str(root))
    return d,{'status':'hit' if hit else 'prepared','path':str(root),**identity}

def features(records):
    result=[]
    for key,d in records.groupby(['population','session','p','individual'],sort=True):
        d=d.sort_values('round');sent=d.entrusted.to_numpy();ret=d.returned.to_numpy()
        outgoing=d[[f'sent{i}' for i in range(4)]].to_numpy()
        back=d[[f'back{i}' for i in range(4)]].to_numpy()
        incoming=d[[f'incoming{i}' for i in range(4)]].to_numpy()
        previous_sent=np.r_[np.nan,sent[:-1]]
        previous_received=np.r_[np.nan,incoming.sum(axis=1)[:-1]]
        # Entrusted(t) depends on neighbours' repayment in round t-1.
        good=np.r_[np.nan,(back[:-1]>=outgoing[:-1]-1e-9).sum(axis=1)]
        # Returned(t): previous-round trustor trends compare t-1 with t-2.
        trend=np.r_[np.nan,np.nan,(incoming[1:-1]>=incoming[:-2]-1e-9).sum(axis=1)]
        for role,values,prev,count in [('entrusted',sent,previous_sent,good),('returned',ret,previous_received,trend)]:
            masks=[np.ones(len(d),dtype=bool),prev>=4,prev<4,count<=1,count==2,count>=3]
            row=dict(zip(['population','session','p','individual'],key));row['role']=role
            for f,mask in zip(FACTORS,masks):
                row[f]=float(values[mask].mean()) if mask.any() else np.nan
                row[f+'n']=int(mask.sum())
            result.append(row)
    return pd.DataFrame(result)

def fit_phenotypes(feature_frame,method='individual_A'):
    from sklearn.cluster import KMeans
    rows=[];models=[]
    for (pop,role),d in feature_frame.groupby(['population','role'],sort=True):
        observed=d[FACTORS].to_numpy(dtype=float);filled=observed.copy();missing=~np.isfinite(observed)
        if method=='individual_A':filled=np.where(missing,observed[:,[0]],observed)
        elif method=='observed_column_median':
            for j in range(6):
                finite=np.isfinite(observed[:,j])
                replacement=float(np.median(observed[finite,j])) if finite.any() else None
                filled[~finite,j]=replacement if replacement is not None else observed[~finite,0]
        else:raise ValueError('Unknown imputation method')
        model=KMeans(n_clusters=3,random_state=42,n_init=50,algorithm='lloyd').fit(filled)
        order=np.argsort(model.cluster_centers_[:,0])[::-1]
        labels={int(k):PHENOTYPES[i] for i,k in enumerate(order)}
        copy=d.copy();copy['phenotype']=[labels[int(k)] for k in model.labels_]
        copy['n_missing']=missing.sum(axis=1)
        for j,f in enumerate(FACTORS):copy[f+'_input']=filled[:,j]
        rows.append(copy)
        models.append({'population':pop,'role':role,'imputation':method,'raw_units':'tokens, no standardization',
            'k':3,'random_state':42,'n_init':50,'n_individuals':len(d),
            'all_missing_factors':[FACTORS[j] for j in range(6) if missing[:,j].all()],
            'missing_individual_counts':{FACTORS[j]:int(missing[:,j].sum()) for j in range(6)},
            'cluster_centers_input':{labels[int(k)]:model.cluster_centers_[k].tolist() for k in order}})
    return pd.concat(rows,ignore_index=True),models

def summarise(labels):
    profile=[]
    for (pop,role,phen),d in labels.groupby(['population','role','phenotype']):
        for f in FACTORS:
            profile.append({'population':pop,'role':role,'phenotype':phen,'factor':f,
                'mean_observed':float(d[f].mean()) if d[f].notna().any() else np.nan,
                'n_observed':int(d[f].notna().sum()),'n_total':len(d),
                'n_condition_events':int(d[f+'n'].sum())})
    count=labels.groupby(['population','role','p','phenotype']).size().rename('n').reset_index()
    index=pd.MultiIndex.from_product([['LLM','Human'],['entrusted','returned'],P_VALUES,PHENOTYPES],names=['population','role','p','phenotype'])
    count=count.set_index(index.names).reindex(index,fill_value=0).reset_index()
    count['denominator']=count.groupby(['population','role','p']).n.transform('sum')
    count['fraction']=count.n/count.denominator
    return pd.DataFrame(profile),count

def human_analysis_cached(records,provenance):
    """Cache the newly requested 20-round factors, assignments and sensitivity fit."""
    import sklearn
    root=Path(provenance['path']);view=root/'rounds_20';view.mkdir(exist_ok=True)
    identity={'records_sha256':shared.digest(root/'all_round_directional_records.csv'),
        'rounds':20,'features_sha256':hashlib.sha256(inspect.getsource(features).encode()).hexdigest(),
        'fit_sha256':hashlib.sha256(inspect.getsource(fit_phenotypes).encode()).hexdigest(),'sklearn':sklearn.__version__}
    paths={name:view/(name+'.csv') for name in ['observed_features','phenotype_assignments','sensitivity_assignments']}
    manifest=view/'analysis_manifest.json'
    with cache._lock(root/'.cache.lock'):
        old=cache._read_json(manifest)
        hit=old.get('identity')==identity and all(cache._valid_file(path,old.get('hashes',{}).get(name)) for name,path in paths.items())
        if hit:
            feat,labels,alt=[cache._read_csv(paths[name]) for name in paths]
            models=old['models']
        else:
            feat=features(records);labels,models=fit_phenotypes(feat);alt,_=fit_phenotypes(feat,'observed_column_median')
            for path,d in zip(paths.values(),[feat,labels,alt]):cache._write_csv(path,d)
            cache._write_json(manifest,{'identity':identity,'hashes':{name:shared.digest(path) for name,path in paths.items()},'models':models})
    shared.event('human_phenotype_analysis_cache',status='hit' if hit else 'prepared',path=str(view))
    return feat,labels,alt,models,{'status':'hit' if hit else 'prepared','path':str(view),'identity':identity}

def make_tables(profiles,fractions):
    angles=np.pi/2-np.arange(6)*np.pi/3
    maxima={role: (5. if role=='entrusted' else float(math.ceil(profiles.loc[profiles.role==role,'mean_observed'].max()/2)*2)) for role in ['entrusted','returned']}
    tables={}
    for pop,role,kind in PANELS:
        if kind=='profile':
            result={};gx=[];gy=[]
            for r in [.25,.5,.75,1]:
                gx+=list(np.r_[np.cos(angles),np.cos(angles[0])]*r)+[np.nan]
                gy+=list(np.r_[np.sin(angles),np.sin(angles[0])]*r)+[np.nan]
            for a in angles:gx += [0.,float(np.cos(a)),np.nan];gy += [0.,float(np.sin(a)),np.nan]
            result['GridX']=pd.Series(gx);result['GridY']=pd.Series(gy)
            for i,phen in enumerate(PHENOTYPES):
                d=profiles[(profiles.population==pop)&(profiles.role==role)&(profiles.phenotype==phen)].set_index('factor').reindex(FACTORS)
                radial=d.mean_observed.to_numpy()/maxima[role];x=radial*np.cos(angles);y=radial*np.sin(angles)
                sx=[];sy=[]
                for j in range(6):
                    k=(j+1)%6
                    if np.isfinite(radial[[j,k]]).all():sx += [x[j],x[k],np.nan];sy += [y[j],y[k],np.nan]
                result[f'LineX{i}']=pd.Series(sx,dtype=float);result[f'LineY{i}']=pd.Series(sy,dtype=float)
                result[f'PointX{i}']=pd.Series(x);result[f'PointY{i}']=pd.Series(y)
            tables[f'{pop.lower()}_{role}_{kind}']=pd.DataFrame(result)
        else:
            # Midpoint boundaries between the five tested p levels; no interpolation.
            edges=np.array([0,.125,.375,.625,.875,1.])
            x=np.column_stack([edges[:-1],edges[1:]]).ravel();result={'p_step':x}
            pivot=fractions[(fractions.population==pop)&(fractions.role==role)].pivot(index='p',columns='phenotype',values='fraction').reindex(P_VALUES)
            cumulative=np.cumsum(pivot[PHENOTYPES].to_numpy(),axis=1)
            result['Top']=np.ones(10);result['ProNeutral']=np.repeat(cumulative[:,1],2)
            result['Prosocial']=np.repeat(cumulative[:,0],2);result['Zero']=np.zeros(10)
            tables[f'{pop.lower()}_{role}_{kind}']=pd.DataFrame(result)
    return tables,maxima

def prepare(args,out):
    import sklearn
    human_path=Path(args.human).resolve();llm_path=Path(args.llm).resolve()
    reuse=getattr(args,'reuse_fig3',None)
    if reuse:
        prior=json.loads((Path(reuse)/'analysis_plan.json').read_text(encoding='utf-8'))
        llm_sources=[s for s in prior['sources'] if s.get('kind')=='LLM CSV']
        assert len(llm_sources)==3
    else:llm_sources=[{'path':str(llm_path),'sha256':shared.digest(llm_path)}]
    sources=llm_sources+[{'path':str(human_path),'sha256':shared.digest(human_path)}]
    fields=['data_source','iteration','proportion','agent_id','round','total_sent','total_returned']+[f'{prefix}{i}' for prefix in ['sent_to_n','received_return_from_n','received_send_from_n'] for i in range(1,5)]
    parts=[]
    for index,source in enumerate(llm_sources,1):
        assert shared.digest(source['path'])==source['sha256']
        part=pd.read_csv(source['path'],usecols=fields,float_precision='round_trip')
        part['_session']=str(index)+'_iteration_'+part.iteration.astype(str)
        part['_source']=source['path'];parts.append(part)
    raw=pd.concat(parts,ignore_index=True);assert raw.data_source.eq('llm').all()
    llm=pd.DataFrame({'population':'LLM','session':'llm_'+raw['_session'],'p':raw.proportion,
        'individual':raw.agent_id,'round':raw['round'],'entrusted':raw.total_sent,'returned':raw.total_returned,'source_sheet':raw['_source']})
    for i in range(4):
        for target,source in [('sent','sent_to_n'),('back','received_return_from_n'),('incoming','received_send_from_n')]:llm[f'{target}{i}']=raw[f'{source}{i+1}']
    human,provenance=human_cached(human_path)
    records=pd.concat([llm, human[human['round'].between(1,20)]],ignore_index=True)
    validate(records,20)
    hf,hl,ha,hm,analysis_cache=human_analysis_cached(records[records.population=='Human'],provenance)
    lf=features(records[records.population=='LLM']);ll,lm=fit_phenotypes(lf);la,_=fit_phenotypes(lf,'observed_column_median')
    feat=pd.concat([hf,lf],ignore_index=True);labels=pd.concat([hl,ll],ignore_index=True)
    alt=pd.concat([ha,la],ignore_index=True);models=hm+lm
    profile,fraction=summarise(labels);_,alternative_fraction=summarise(alt)
    from sklearn.metrics import adjusted_rand_score
    sensitivity=[]
    for (pop,role),d in labels.groupby(['population','role']):
        a=alt[(alt.population==pop)&(alt.role==role)]
        sensitivity.append({'population':pop,'role':role,'comparison':'individual A vs observed-column median (all-missing factors fall back to individual A)',
            'label_agreement':float(np.mean(d.phenotype.to_numpy()==a.phenotype.to_numpy())),
            'adjusted_rand_index':float(adjusted_rand_score(d.phenotype,a.phenotype)),
            'n_individuals':len(d)})
    tables,radial_max=make_tables(profile,fraction)
    tables={'selected_round_records':records,'observed_features':feat,'phenotype_assignments':labels,
        'observed_profiles':profile,'phenotype_fractions':fraction,'sensitivity_assignments':alt,
        'sensitivity_fractions':alternative_fraction,**tables}
    for name,d in tables.items():d.to_csv(out/f'{name}.csv',index=False,encoding='utf-8-sig')
    with pd.ExcelWriter(out/'Fig6_plot_data.xlsx',engine='openpyxl') as writer:
        for name,d in tables.items():d.to_excel(writer,sheet_name=name[:31],index=False)
    shared.write_json(out/'clustering_models.json',models);shared.write_json(out/'missingness_sensitivity.json',sensitivity)
    for s in sources:assert shared.digest(s['path'])==s['sha256']
    plan={'figure':'Fig. 6','rounds':20,'purpose':'Describe observed behavioural profiles and phenotype composition across agency conditions in LLM and Human populations.',
        'sources':sources,'panels':PANELS,'colors':COLORS,'radial_max':radial_max,'human_cache':provenance,'human_analysis_cache':analysis_cache,
        'reused_fig3_source_manifest':str(reuse) if reuse else None,
        'n_sessions':records.groupby('population').session.nunique().to_dict(),
        'profile_titles':{'a':'Entrusted amount','c':'Returned amount','e':'Entrusted amount','g':'Returned amount'},
        'clustering':'Separate K=3 per population and role, pooling all p levels; raw six token-valued features; no standardization. Label clusters by descending centroid A.',
        'missing_policy':'User-approved individual A imputation in clustering only; radar profiles average observed values only. Conditional means with no events remain NA.',
        'returned_BC_units':'Previous-round total incoming after tripling; threshold 4 tokens.',
        'timing':'Entrusted D-F: back(t-1)>=sent(t-1) per edge. Returned D-F: incoming(t-1)>=incoming(t-2) per edge; no condition at t=1 or2.',
        'profile_semantics':'Unweighted mean of observed individual conditional means within phenotype, not imputed centroids; each factor has its own observed n.',
        'composition':'Counts pooled across individuals/sessions within p; fractions sum to 1. Midpoint step boundaries are display only.',
        'adaptation_not_exact_original':'Original six-factor Kmeans framework with explicitly approved missing-feature adaptation; original paper does not specify the missingness convention or all implementation details.',
        'versions':{'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__},
        'table_hashes':{name:shared.digest(out/f'{name}.csv') for name in tables}}
    shared.write_json(out/'analysis_plan.json',plan)
    (out/'Fig6_notes.md').write_text('''# Fig6: six-factor behavioural phenotypes (first version)

Main source: src/analysis/fig6.py. Both populations use rounds 1–20. Native Origin produces eight editable layers and exports only PDF/EPS as formal figures. Internal OPJU and PNG are isolated verification artifacts in the OS temporary folder; no reference pixels enter the figure. Output border uses Origin expGraph tr.Margin=1 (tight).

Six factors follow Fig3 and Extended Data Fig4 of Jia et al., Nature Human Behaviour 2025, doi:10.1038/s41562-025-02289-0, with explicit implementation choices recorded here rather than claiming exact recovery of their software. A = individual mean amount over rounds 1–20. Entrusted B/C = mean entrusted at t conditional on total sent at t-1 >=4/<4; D/E/F = mean entrusted at t when 0–1/2/3–4 neighbours returned >= the focal individual's edge-specific entrusted amount in t-1. Returned B/C = mean returned at t conditional on actual total tokens received at t-1 after tripling >=4/<4. Returned D/E/F = mean returned at t when 0–1/2/3–4 neighbouring trustors sent at t-1 >= their own sends at t-2; these use rounds 3–20 only. Supplement C repeats >=4 for C in one sentence; we use <4 as specified in the main Extended Data Fig4 caption. Exact timing and received-amount scale are implementation interpretations made explicit for review.

Kmeans: K=3, Euclidean raw token features, no scaling, random_state=42, n_init=50, Lloyd algorithm. Fit separately for each population and role across all five p conditions, never independently at each p. Missing conditional means are replaced by that individual's A solely for clustering, as approved. Order clusters by their A centroids: Prosocial (highest), Neutral, Antisocial (lowest). These are relative descriptive clusters within each population, not common absolute behavioural thresholds or validated psychological types; human and LLM labels need not denote equal action levels. K=3 is retained from the requested original framework, not re-established as optimal for this dataset.

The radar charts contain ONLY observed individual feature means averaged within the assigned phenotype. Unobserved conditional responses are not drawn or closed across a missing spoke; an asterisk on a factor label marks that at least one phenotype lacks that factor completely. Factor-specific observed n and event counts are in observed_profiles.csv. Imputation can influence membership; it does not invent observed profiles. Radial axes use the same raw-token maximum for LLM and Human within each role. Only plotting coordinates divide by this displayed radial maximum; clustering is unnormalized.

Composition charts show individual phenotype fractions by nominal p. Human identities include session to preserve all three experiments. Five p levels are shown as midpoint-bounded steps; changes within the intervening intervals were not measured. These are descriptive fractions, not independent experimental replications or inferential tests.

Palette: the Fig4 LLM palette supplies green #009E73 / orange #E69F00 / vermilion #D55E00 for Prosocial / Neutral / Antisocial. The Fig4 Human palette supplies dark purple #372334 / brown #843B37 / orange #F25A20 for the same ordered labels. Colour now encodes phenotype, not p. The same phenotype colour and symbol are used in the two roles of each population. Opaque fills are used for EPS compatibility.

Sensitivity: missingness_sensitivity.json compares individual-A imputation with an alternative observed-column median; a completely unobserved column retains the individual-A fallback. Report ARI and label agreement without treating the alternative as ground truth. Low agreement means the phenotype conclusion depends on the imputation convention. All measured amounts, all individuals, and correction flags in immutable sources are retained; no smoothing, exclusions, fits or invented sessions.

Caption: Behavioural profiles and phenotype composition during the first 20 rounds. Panels a–d show LLM agents and e–h show human participants. Entrusted profiles and fractions appear in columns 1–2; returned profiles and fractions appear in columns 3–4. Radar values summarize observed A–F factors for each phenotype; asterisks indicate wholly unobserved phenotype–factor combinations. Three descriptive clusters are derived from six behavioural features using Kmeans with the approved missing-feature rule. Step-filled areas show the fractions assigned to each phenotype at the five tested agency conditions; intermediate p values were not tested. See source-data tables for factor definitions, observed sample counts and sensitivity to imputation.
''',encoding='utf-8')
    shared.event('data_prepared',output=str(out),individual_role_rows=len(labels),sensitivity=sensitivity)

def label_at(op,layer,name,text,x,y,size=15,center=True):
    lab=shared.set_label(layer,name,text,size);layer.lt_exec(f'{name}.attach=1;')
    pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
    lab.set_float('left',pw*x/100-(lab.get_float('width')/2 if center else 0));lab.set_float('top',ph*y/100)
    return lab

def style(op,layer,index,plan,profile):
    pop,role,kind=PANELS[index];left,top,width,height=POSITIONS[index]
    layer.activate();layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.factor=1;layer.fixed=1;layer.maxpts=0;')
    for name in ['Legend','legend','xb','yl']:
        lab=layer.label(name)
        if lab:layer.remove_label(lab)
    font=int(op.lt_float('font(Arial)'))
    for a in ['x','y']:
        layer.set_int(a+'.label.font',font);layer.set_float(a+'.label.pt',15)
        for k,v in [('minorTicks',0),('atZero',0),('label.table',0),('label.type',1),('label.numFormat',1),('label.rotate',0)]:layer.set_int(a+'.'+k,v)
        layer.set_float(a+'.thickness',1);layer.set_float(a+'.tickthickness',1)
    if kind=='profile':
        layer.axis('x').set_limits(-1.3,1.3,.5);layer.axis('y').set_limits(-1.3,1.3,.5)
        for a in ['x','y']:
            layer.set_int(a+'.showAxes',0);layer.set_int(a+'.showLabels',0);layer.set_int(a+'.ticks',0)
        angles=np.pi/2-np.arange(6)*np.pi/3
        for j,f in enumerate(FACTORS):
            rows=profile[(profile.population==pop)&(profile.role==role)&(profile.factor==f)]
            missing=rows.n_observed.eq(0).any()
            label_at(op,layer,'Factor'+f,f+('*' if missing else ''),left+width*(.5+np.cos(angles[j])*1.22/2.6),top+height*(.5-np.sin(angles[j])*1.22/2.6)-1,15)
        for j,r in enumerate([.25,.5,.75,1]):
            label_at(op,layer,'Radial'+str(j),f'{r*plan["radial_max"][role]:g}',left+width*.52,top+height*(.5-r/2.6)+.4,11,False)
    else:
        layer.axis('x').set_limits(0,1,.25);layer.axis('y').set_limits(0,1,.25)
        for a in ['x','y']:
            layer.set_int(a+'.showAxes',3);layer.set_int(a+'.showLabels',1);layer.set_int(a+'.ticks',5)
        label_at(op,layer,'XCaption','Fraction of free players, p',left+width/2,top+height+6,15)
        yl=label_at(op,layer,'YCaption','Fraction of players',left-5,top+height/2,15)
        layer.lt_exec('YCaption.rotate=90;')
        pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
        yl.set_float('left',pw*(left-5)/100-yl.get_float('width')/2);yl.set_float('top',ph*(top+height/2)/100-yl.get_float('height')/2)
    label_at(op,layer,'Panel',f'({chr(97+index)})',left-1.8,top-4.7,17,False)
    title=('Entrusted amount' if role=='entrusted' else 'Returned amount') if kind=='profile' else f'{role.title()} phenotypes'
    label_at(op,layer,'Heading',title,left+width/2,top-4.7,15)
    layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
    geometry=[float(op.lt_float('layer.'+k)) for k in ['left','top','width','height']]
    cross=[float(op.lt_float(k)) for k in ['v3','v4','v1','v2']]
    assert layer.get_int('unit')==1 and np.allclose(geometry,POSITIONS[index],atol=.03) and np.allclose(geometry,cross,atol=.03)
    return {'population':pop,'role':role,'kind':kind,'geometry':geometry,'geometry_crosscheck':cross,
        'xlim':list(layer.xlim),'ylim':list(layer.ylim),'font':font}

def render(args,out):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    for s in plan['sources']:assert shared.digest(s['path'])==s['sha256']
    for name,sha in plan['table_hashes'].items():assert shared.digest(out/f'{name}.csv')==sha
    if not args.probe:
        ev=json.loads(Path(args.route_evidence).read_text(encoding='utf-8')) if args.route_evidence else {}
        assert ev.get('status')=='passed' and ev.get('visual_qa')=='passed' and ev.get('experimental_probe')
        assert ev['renderer_sha256']==shared.digest(__file__) and ev['shared_module_sha256']==shared.digest(shared.__file__)
    qa=Path(args.qa_dir).resolve() if args.qa_dir else Path(tempfile.gettempdir())/('Fig6_QA_'+out.name)
    qa.mkdir(parents=True,exist_ok=False)
    profile=pd.read_csv(out/'observed_profiles.csv');roles=[];addresses={}
    with shared.origin_slot(),shared.isolated_origin(not args.close_origin and (not args.probe or getattr(args,'project_only',False))) as op:
        if not args.probe:assert ev['origin_version']==float(op.lt_float('@V'))
        graph=op.new_graph(template='Line');graph.name='Fig6'
        for index,(pop,role,kind) in enumerate(PANELS):
            name=f'{pop.lower()}_{role}_{kind}';data=pd.read_csv(out/f'{name}.csv')
            sheet=op.new_sheet('w','Panel'+str(index));sheet.from_df(data);addresses[name]=sheet.lt_range(False)
            layer=graph[0] if index==0 else graph.add_layer();rr=[]
            def add(y,x,color,typ='l',kind='profile',symbol=2):
                p=layer.add_plot(sheet,y,x,type=typ);p.color=color
                p.set_cmd('-w 700' if kind=='profile' else '-w 350')
                if typ=='s':p.symbol_kind=symbol;p.symbol_interior=1;p.symbol_size=4.4
                rr.append({'kind':kind,'rgb':[int(color[j:j+2],16) for j in [1,3,5]],'range':p.lt_range(),'x':x,'y':y,'type':typ})
                return p
            if kind=='profile':
                add('GridY','GridX','#D0D0D0',kind='grid')
                for i,color in enumerate(COLORS[pop]):
                    add(f'LineY{i}',f'LineX{i}',color)
                    add(f'PointY{i}',f'PointX{i}',color,'s',symbol=[2,1,3][i])
            else:
                cols=['Top','ProNeutral','Prosocial','Zero']
                for i,col in enumerate(cols):
                    color=COLORS[pop][2-i] if i<3 else COLORS[pop][0]
                    add(col,'p_step',color,kind='area' if i<3 else 'baseline')
            roles.append(rr);shared.event('panel_built',panel=index+1,kind=kind)
        graph.activate();op.lt_exec(f'page.updatetoprinter=0;page.kar=0;page.width=({PAGE_CM[0]}/2.54)*page.resx;page.height=({PAGE_CM[1]}/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'));states=[]
        for index,layer in enumerate(graph):
            state=style(op,layer,index,plan,profile)
            if PANELS[index][2]=='fraction':
                for p in layer.plot_list()[:3]:
                    color='#'+''.join(f'{v:02X}' for v in p.color)
                    layer.lt_exec(f'range __fill={p.lt_range()};set __fill -pf 1;set __fill -pfv 9;set __fill -pfb color({color});set __fill -p2fb color({color});set __fill -pfm 1;set __fill -p2fm 1;set __fill -paal 1;')
                    p.transparency=0
            if index in [0,4]:
                pop=PANELS[index][0];entries=[f'\\l({3+2*i}) {phen}' for i,phen in enumerate(PHENOTYPES)]
                label_at(op,layer,'RowLegend',pop+':  '+'     '.join(entries),50,1 if index==0 else 52,15)
            state['texts']={}
            for name in ['Panel','Heading','RowLegend','XCaption','YCaption']+['Factor'+f for f in FACTORS]:
                lab=layer.label(name)
                if lab:
                    state['texts'][name]={'text':lab.text,'font':lab.get_int('font'),'size':lab.get_float('fsize')}
                    assert lab.get_int('font')==state['font']
            states.append(state)
        # Native axis-title names can be inherited across layers in Origin 2021;
        # ordinary named captions above avoid that shared-title behaviour.
        for layer in graph:
            for name in ['xb','yl','xt','yr']:
                lab=layer.label(name)
                if lab:layer.remove_label(lab)
        graph.activate();op.lt_exec('doc -uw;')
        project=out/'Fig6.opju' if getattr(args,'project_only',False) else qa/'Fig6_internal.opju';assert op.save(str(project))
        # Respect user format choice: PNG only inside temporary internal QA directory.
        for ext in ([] if getattr(args,'project_only',False) else ['pdf','eps']):
            command=f'expGraph -sw type:={ext} filename:="Fig6" path:="{out}" overwrite:=replace tr.Margin:=1 tr.SpeedMode:=2;'
            assert op.lt_exec(command)
            assert (out/f'Fig6.{ext}').stat().st_size>1000
        graph.save_fig(str(qa/'Fig6_preview.png'),width=4200)
        assert op.open(str(project));saved=op.find_graph('Fig6');assert len(saved)==8
        for index,layer in enumerate(saved):
            assert len(layer.plot_list())==len(roles[index])
            assert np.allclose(layer.xlim,states[index]['xlim']) and np.allclose(layer.ylim,states[index]['ylim'])
            states[index]['plots']=[]
            for plot,r in zip(layer.plot_list(),roles[index]):
                assert list(plot.color)==r['rgb']
                assert plot.get_int('pid')==(201 if r['type']=='s' else 200)
                if r['kind']=='area':
                    layer.lt_exec(f'range __r={plot.lt_range()};get __r -pfv __mode;get __r -pf __on;get __r -pfm __gradient;')
                    assert op.lt_float('__mode')==9 and op.lt_float('__on')==1 and op.lt_float('__gradient')==1 and plot.transparency==0
                states[index]['plots'].append({**r,'pid':plot.get_int('pid')})
            for name,expected in states[index]['texts'].items():
                lab=layer.label(name);assert lab and lab.text==expected['text'] and lab.get_int('font')==expected['font'] and math.isclose(lab.get_float('fsize'),expected['size'],abs_tol=.01)
        for name,address in addresses.items():
            actual=op.find_sheet('w',address).to_df();expected=pd.read_csv(out/f'{name}.csv')
            assert actual.shape==expected.shape
            assert np.allclose(actual.to_numpy(dtype=float),expected.to_numpy(dtype=float),atol=1e-10,equal_nan=True)
        if not getattr(args,'project_only',False):
            eps=(out/'Fig6.eps').read_bytes();assert eps.startswith(b'%!PS-Adobe') or b'%!PS-Adobe' in eps[:40]
            assert (out/'Fig6.pdf').read_bytes().startswith(b'%PDF-')
        shared.write_json(out/'origin_readback.json',{'status':'passed','experimental_probe':args.probe,
            'renderer_sha256':shared.digest(__file__),'shared_module_sha256':shared.digest(shared.__file__),
            'origin_version':float(op.lt_float('@V')),'layers':states,'saved_project_reopened':True,
            'saved_numeric_data_verified':True,'qa_directory':str(qa),'internal_project':str(project),
            'preview':str(qa/'Fig6_preview.png'),'formal_formats':['opju'] if getattr(args,'project_only',False) else ['pdf','eps'],'export_margin':'user manual export' if getattr(args,'project_only',False) else 'tight (tr.Margin=1)',
            'project_only':getattr(args,'project_only',False),
            'visual_qa':'pending','route_evidence':args.route_evidence})
        saved.activate()
    shared.event('origin_complete',output=str(out),preview=str(qa/'Fig6_preview.png'))

def snapshot(out,evidence=None):
    dest=out/'source';dest.mkdir(exist_ok=True)
    for name in ['fig6.py','fig3.py','human_data_cache.py','test_fig6_data_contract.py','verify_fig6_data.py','README_fig6.md','run_fig6.ps1']:
        path=Path(__file__).with_name(name)
        if path.exists():shutil.copy2(path,dest/name)
    if evidence:shutil.copy2(evidence,dest/'verified_route_evidence.json')
    shutil.make_archive(str(out/'Fig6_reproduction_source'),'zip',dest)
    shared.write_json(out/'source_manifest.json',{'main_script':'source/fig6.py','files':{p.name:shared.digest(p) for p in dest.iterdir() if p.is_file()},'argv':sys.argv})

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','render','all'])
    p.add_argument('--llm');p.add_argument('--human',default=str(shared.DEFAULT_HUMAN_WORKBOOK));p.add_argument('--output-dir')
    p.add_argument('--origin-python');p.add_argument('--probe',action='store_true');p.add_argument('--route-evidence')
    p.add_argument('--reuse-fig3',help='Reuse the three verified LLM source paths and hashes')
    p.add_argument('--project-only',action='store_true',help='Deliver editable Fig6.opju without PDF/EPS export')
    p.add_argument('--qa-dir');p.add_argument('--close-origin',action='store_true');args=p.parse_args()
    if args.command in ['prepare','all']:
        if not args.llm:p.error('--llm is required')
        out=Path(args.output_dir).resolve() if args.output_dir else Path(args.llm).resolve().parent/f'agent_rounds_Fig6_EditaPlot_{datetime.now():%Y%m%d_%H%M%S}'
        out.mkdir(parents=True,exist_ok=False);prepare(args,out)
    else:
        out=Path(args.output_dir).resolve()
        if (out/'Fig6.pdf').exists() or (out/'Fig6.opju').exists():raise ValueError('Existing formal figure will not be overwritten')
    if args.command in ['render','all']:
        if args.origin_python:
            cmd=[args.origin_python,str(Path(__file__).resolve()),'render','--output-dir',str(out)]
            if args.probe:cmd.append('--probe')
            if args.project_only:cmd.append('--project-only')
            if args.close_origin:cmd.append('--close-origin')
            if args.qa_dir:cmd+=['--qa-dir',args.qa_dir]
            if args.route_evidence:cmd+=['--route-evidence',args.route_evidence]
            subprocess.run(cmd,check=True)
        else:render(args,out)
    snapshot(out,args.route_evidence);shared.event('complete',output=str(out))

if __name__=='__main__':main()
