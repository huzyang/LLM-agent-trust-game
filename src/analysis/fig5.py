"""MAIN SCRIPT: immutable raw data -> 20-round wealth tables -> native Origin Fig. 5.

python -m src.analysis.fig5 prepare --llm-session <agent_rounds.csv>
python -m src.analysis.fig5 render --output-dir <prepared> --probe
After visual verification, render a fresh preparation with --route-evidence <probe report>.
"""
from __future__ import annotations
import argparse
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime
import numpy as np
import pandas as pd
try:
    from . import fig3 as shared
    from . import human_data_cache as cache
except ImportError:
    import fig3 as shared
    import human_data_cache as cache

P_VALUES = shared.P_VALUES
COLORS = {'LLM': ['#0072B2','#E69F00','#009E73','#CC79A7','#D55E00'],
          'Human': shared.HUMAN_COLORS}
GROUPS = ['Constrained','Free','Combined']
OFFSETS = [-.25,0,.25]
SYMBOLS = [1,3,2]
POSITIONS = [(10,18,35,29),(61,18,35,29),(10,63,35,29),(61,63,35,29)]
PANELS = [('LLM','wealth'),('Human','wealth'),('LLM','gini'),('Human','gini')]
PAGE_CM = (28,23)

def gini(values):
    x=np.sort(np.asarray(values,dtype=float))
    if not len(x) or not np.isfinite(x).all():
        raise ValueError('Gini requires finite wealth; no shifting or exclusion permitted')
    if np.all(x==0): return 0.
    if x.sum()<=0: raise ValueError('Nonpositive group total: Gini denominator needs scientific review')
    n=len(x)
    return float(2*np.dot(np.arange(1,n+1),x)/(n*x.sum())-(n+1)/n)

def read_human(path):
    import openpyxl
    book=openpyxl.load_workbook(path,data_only=True,read_only=True)
    rows=[]
    try:
        for sheet in book:
            m=re.fullmatch(r'TG (0|25|50|75|100)% free session(\d+)',sheet.title)
            if not m: continue
            iterator=sheet.iter_rows(values_only=True)
            columns=list(next(iterator)); idx={x:i for i,x in enumerate(columns)}
            for row in iterator:
                rd=row[idx['subsession.round_number']]
                if rd is None: continue
                sent,received,returned,back=[float(row[idx[x]]) for x in
                    ['player.send_T','player.receive_send_T','player.return_T','player.receive_return_T']]
                payoff=float(row[idx['player.payoff']])
                if not math.isclose(payoff,back-sent+3*received-returned,abs_tol=1e-8):
                    raise ValueError('Human payoff convention differs from the confirmed definition')
                flag=int(row[idx['player.is_node_player']])
                if flag not in [0,1]: raise ValueError('Unknown human role flag')
                rows.append({'population':'Human','session':'human_'+m[2],'p':int(m[1])/100,
                    'individual':int(row[idx['player.id_in_group']]),'round':int(rd),
                    'group':'Constrained' if flag else 'Free','round_payoff':payoff,
                    'accumulate_payoff':float(row[idx['player.accumulate_payoff']]),
                    'source_sheet':sheet.title})
    finally: book.close()
    return pd.DataFrame(rows)

def validate_records(d,rounds):
    keys=['population','session','p','individual']
    if d.duplicated(keys+['round']).any(): raise ValueError('Duplicate raw records')
    if not np.isfinite(d[['round_payoff','accumulate_payoff']].to_numpy()).all():
        raise ValueError('Missing or nonfinite payoff')
    if d.empty or not set(d.group).issubset({'Constrained','Free'}): raise ValueError('Unknown role')
    counts=d.groupby(keys)['round'].agg(['min','max','size'])
    if not ((counts['min']==1)&(counts['max']==rounds)&(counts['size']==rounds)).all():
        raise ValueError('Incomplete individual round history')
    if not d.groupby(keys).group.nunique().eq(1).all(): raise ValueError('Role changes across rounds')
    if not d.groupby(['population','session','p']).individual.nunique().eq(49).all():
        raise ValueError('Expected 49 individuals per session')
    if not d.loc[d.p==0,'group'].eq('Constrained').all() or not d.loc[d.p==1,'group'].eq('Free').all():
        raise ValueError('Endpoint population role mismatch')
    ordered=d.sort_values(keys+['round'])
    sums=ordered.groupby(keys).round_payoff.cumsum()
    if not np.allclose(sums,ordered.accumulate_payoff,atol=1e-7):
        raise ValueError('Recorded accumulated payoff differs from sum of round payoffs')

def human_cached(path):
    sha=shared.digest(path)
    identity={'source_sha256':sha,'reader_sha256':hashlib.sha256(inspect.getsource(read_human).encode()).hexdigest(),
              'schema':1,'role_mapping':'is_node_player 1=Constrained, 0=Free'}
    root=path.parent/('trust_game_wealth_'+sha[:16]+'_'+identity['reader_sha256'][:16])
    root.mkdir(exist_ok=True)
    manifest=root/'source_manifest.json'; table=root/'all_round_payoffs.csv'
    with cache._lock(root/'.cache.lock'):
        old=cache._read_json(manifest)
        hit=old.get('identity')==identity and cache._valid_file(table,old.get('table_sha256'))
        if hit: d=cache._read_csv(table)
        else:
            d=read_human(path); validate_records(d,50)
            if shared.digest(path)!=sha: raise ValueError('Human input changed')
            cache._write_csv(table,d)
            cache._write_json(manifest,{'identity':identity,'table_sha256':shared.digest(table),
                'rows':len(d),'source_path':str(path),'participant_information':'not read or exported'})
    validate_records(d,50)
    shared.event('human_wealth_cache',status='hit' if hit else 'prepared',path=str(root))
    return d,{'status':'hit' if hit else 'prepared','path':str(root),'manifest':str(manifest),**identity}

def summarise(final):
    expanded=pd.concat([final,final.assign(group='Combined')],ignore_index=True)
    wealth=expanded.groupby(['population','p','group'],sort=True).accumulate_payoff.agg(
        n_individuals='size',mean='mean',sd='std',minimum='min',maximum='max').reset_index()
    session=[]
    for (pop,s,p,g),d in expanded.groupby(['population','session','p','group']):
        session.append({'population':pop,'session':s,'p':p,'group':g,
            'n_individuals':len(d),'gini':gini(d.accumulate_payoff)})
    session=pd.DataFrame(session)
    if not session.gini.between(-1e-12,1+1e-12).all():
        raise ValueError('Observed Gini outside 0–1: stop for user review; do not adjust wealth automatically')
    summary=session.groupby(['population','p','group']).gini.agg(
        n_sessions='size',mean='mean',minimum='min',maximum='max').reset_index()
    return expanded,wealth,session,summary

def shade(color,g):
    white=[.78,.45,.12][g]
    return '#'+''.join(f'{round(int(color[i:i+2],16)*(1-white)+255*white):02X}' for i in [1,3,5])

def plot_tables(expanded,wealth,sessions,summary):
    tables={}
    for pop,metric in PANELS:
        result={}
        for pi,p in enumerate(P_VALUES):
            for gi,g in enumerate(GROUPS):
                name=f'P{pi}G{gi}'
                center=pi+1+OFFSETS[gi]
                raw=expanded[(expanded.population==pop)&(expanded.p==p)&(expanded.group==g)]
                if raw.empty: continue
                if metric=='wealth':
                    row=wealth[(wealth.population==pop)&(wealth.p==p)&(wealth.group==g)].iloc[0]
                    vals=raw.accumulate_payoff.to_numpy()
                    # Display-only horizontal jitter; all measured Y values retained.
                    result[name+'RawX']=pd.Series(center+np.random.default_rng(5100+pi*3+gi).uniform(-.075,.075,len(vals)))
                    result[name+'RawY']=pd.Series(vals)
                    result[name+'MeanX']=pd.Series([center])
                    result[name+'MeanY']=pd.Series([row['mean']])
                    lo,hi=row['mean']-row.sd,row['mean']+row.sd
                    result[name+'ErrX']=pd.Series([center,center,np.nan,center-.045,center+.045,np.nan,center-.045,center+.045])
                    result[name+'ErrY']=pd.Series([lo,hi,np.nan,lo,lo,np.nan,hi,hi])
                else:
                    row=summary[(summary.population==pop)&(summary.p==p)&(summary.group==g)].iloc[0]
                    # Five X rows fix native column spacing; missing categories remain empty.
                    result[name+'BarX']=pd.Series(np.arange(1,6)+OFFSETS[gi])
                    y=np.full(5,np.nan);y[pi]=row['mean'];result[name+'BarY']=pd.Series(y)
                    ss=sessions[(sessions.population==pop)&(sessions.p==p)&(sessions.group==g)]
                    result[name+'SessionX']=pd.Series(center+np.linspace(-.04,.04,len(ss)) if len(ss)>1 else [center])
                    result[name+'SessionY']=pd.Series(ss.gini.to_numpy())
        tables[f'{pop.lower()}_{metric}']=pd.DataFrame(result)
    return tables

def prepare(args,out):
    llmpath=Path(args.llm_session).resolve(); humanpath=Path(args.human).resolve()
    sources=[{'path':str(p),'sha256':shared.digest(p)} for p in [llmpath,humanpath]]
    raw=pd.read_csv(llmpath,float_precision='round_trip')
    if not raw.data_source.eq('llm').all(): raise ValueError('Mixed or mock input')
    if not np.allclose(raw.round_payoff,raw.total_received_return-raw.total_sent+raw.total_received_send-raw.total_returned,atol=1e-8):
        raise ValueError('LLM payoff convention mismatch (received_send is already tripled)')
    llm=pd.DataFrame({'population':'LLM','session':raw.iteration.map(lambda i:f'llm_iteration_{i}'),
        'p':raw.proportion,'individual':raw.agent_id,'round':raw['round'],
        'group':raw.agent_type.map({'constrained':'Constrained','free':'Free'}),
        'round_payoff':raw.round_payoff,'accumulate_payoff':raw.accumulate_payoff,'source_sheet':llmpath.name})
    human,provenance=human_cached(humanpath)
    records=pd.concat([llm[llm['round'].between(1,20)],human[human['round'].between(1,20)]],ignore_index=True)
    validate_records(records,20)
    for _,d in records.groupby(['population','session']):
        if sorted(d.p.unique())!=P_VALUES: raise ValueError('Condition missing')
    final=records[records['round']==20].copy()
    expanded,wealth,sessions,summary=summarise(final)
    tables={'selected_round_records':records,'individual_wealth':final,'wealth_summary':wealth,
        'session_gini':sessions,'gini_summary':summary,**plot_tables(expanded,wealth,sessions,summary)}
    for name,d in tables.items():d.to_csv(out/f'{name}.csv',index=False,encoding='utf-8-sig')
    with pd.ExcelWriter(out/'Fig5_plot_data.xlsx',engine='openpyxl') as writer:
        for name,d in tables.items():d.to_excel(writer,sheet_name=name[:31],index=False)
    columns={}
    for label,names,primary,support in [
        ('LLM',list(raw.columns),{'accumulate_payoff'},{'iteration','round','proportion','agent_id','agent_type','data_source','round_payoff','total_received_return','total_sent','total_received_send','total_returned'}),
        ('Human_experiment_sheets',list(pd.read_excel(humanpath,sheet_name='TG 0% free session1',nrows=0).columns),{'player.accumulate_payoff'},{'player.id_in_group','player.is_node_player','subsession.round_number','player.payoff','player.send_T','player.return_T','player.receive_send_T','player.receive_return_T'})]:
        columns[label]=[{'column':x,'role':'render_primary' if x in primary else 'support_only' if x in support else 'retain_not_render'} for x in names]
    plan={'figure':'Fig. 5','purpose':'Compare individual accumulated wealth and within-session inequality across agency conditions and player types.',
        'rounds':20,'layout':PANELS,'groups':GROUPS,'colors':COLORS,'sources':sources,'column_roles':columns,
        'wealth':'One individual cumulative payoff at round 20; raw scatter, mean +/-1 sample SD (ddof=1). Human individuals pooled across sessions for descriptive mean/SD.',
        'gini':'Uncorrected empirical Gini within each session and group, then unweighted mean across sessions; points show actual session Ginis; no invented uncertainty. User approved retaining negative wealth unchanged if all observed Ginis remain in 0–1.',
        'negative_wealth':final.loc[final.accumulate_payoff<0,['population','session','p','individual','group','accumulate_payoff']].to_dict('records'),
        'observed_session_gini_range':[float(sessions.gini.min()),float(sessions.gini.max())],
        'group_absence':'No Free group at p=0; no Constrained group at p=1. Combined repeats observations intentionally and is not an additional sample.',
        'human_cache':provenance,'n_sessions':records.groupby('population').session.nunique().to_dict(),
        'table_hashes':{name:shared.digest(out/f'{name}.csv') for name in tables},
        'reference_adaptation':{'source':'User reference Extended Data Fig. 3 B,E','applied':['wealth scatter plus summaries','Gini grouped bars','three player groups'],
            'overridden':['two-column LLM/Human layout','20 rounds both populations','wealth SD instead of SEM','Fig4 p palettes instead of type colors'],
            'reference_pixels_or_digitized_values_used':False}}
    for s in sources:
        if shared.digest(s['path'])!=s['sha256']:raise ValueError('Input changed')
    shared.write_json(out/'analysis_plan.json',plan)
    (out/'Fig5_notes.md').write_text('''# Figure 5: wealth and inequality

Main executable source: `source/fig5.py`; preparation uses immutable raw records.
Both populations: rounds 1–20. Wealth is the sum of recorded round payoffs, cross-checked against round-20 accumulated payoff. No initial endowment is added. Human receive_send_T is pre-multiplier; LLM total_received_send is already tripled. The resulting payoff definitions agree.

Panels (a,b): individual wealth distributions with mean ±1 sample SD (ddof=1). Human mean/SD pool individuals across three sessions using (session,individual) identities; dispersion is not a confidence interval or uncertainty across independent repeats. Shapes (square, triangle, circle) and left-to-right offsets identify Constrained, Free and Combined. Combined intentionally repeats the two component samples.

Panels (c,d): Gini within each session and group, using the uncorrected empirical formula sum|xi-xj|/(2*n*sum(x)); bars are equally weighted means of session Ginis. Black points show individual session Ginis. No between-session uncertainty is estimated for a single LLM session. No pooling of human sessions before Gini computation, no finite-size correction, shifting, trimming or imputation. As explicitly approved, negative individual wealth is retained unchanged. With negative wealth this formula need not be bounded by 1; this workflow checks all observed coefficients and stops for user review if any fall outside 0–1. Nonpositive group totals also stop processing. Absent groups remain absent.

Colours encode nominal p and match Fig4 separately for LLM/Human; lighter/darker native column fills identify groups. All p categories remain explicitly labelled. Display-only deterministic horizontal jitter does not change wealth. No p-values or inferential claims. Comparisons are descriptive and the LLM and human experiments were not concurrently randomized. Actual human free-player fractions vary slightly across sessions.

Caption: Individual wealth and payoff inequality after the first 20 rounds of the networked trust game. LLM agents (a,c) and human participants (b,d) are divided into constrained players, free players and the combined population at each nominal fraction of free players. Wealth points show individual cumulative payoffs; black markers and intervals show the mean ±1 sample standard deviation. Gini bars show the mean of within-session coefficients; black markers show the observed coefficients for each session. Identical observations appear both in their player-type group and in the combined group. Negative cumulative payoffs are retained without truncation or shifting. Colours follow Fig4.
''',encoding='utf-8')
    shared.event('data_prepared',output=str(out),counts=records.groupby('population').size().to_dict(),minimum_wealth=float(final.accumulate_payoff.min()))

def style(op,graph,layer,index,limits):
    pop,metric=PANELS[index];left,top,width,height=POSITIONS[index]
    layer.activate();layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.fixed=1;layer.factor=1;layer.maxpts=0;')
    layer.axis('x').set_limits(.5,5.5,1);layer.axis('y').set_limits(*limits)
    font=int(op.lt_float('font(Arial)'))
    for a in ['x','y']:
        for k,v in [('showAxes',3),('showLabels',1),('ticks',5),('minorTicks',0),('atZero',0),('label.table',0),('label.type',1),('label.numFormat',1),('label.font',font),('label.rotate',0)]:layer.set_int(f'{a}.{k}',v)
        layer.set_float(f'{a}.label.pt',16);layer.set_float(f'{a}.thickness',1);layer.set_float(f'{a}.tickthickness',1)
    layer.axis('x').title='';layer.axis('y').title='Wealth (tokens)' if metric=='wealth' else 'Gini coefficient'
    for name in ['Legend','legend','xb']:
        lab=layer.label(name)
        if lab:layer.remove_label(lab)
    for key in ['showLabels','showlabel','label.show']:layer.set_int('x.'+key,0)
    pw,ph=op.lt_float('page.width'),op.lt_float('page.height')
    texts=[('Panel',f'({chr(97+index)})',left-3,top-5,19,False),
        ('Heading',pop,left+width/2,top-5,18,True)]
    if index>=2:texts.append(('XCaption','Fraction of free players, p',left+width/2,top+height+5,17,True))
    for i,p in enumerate(P_VALUES):texts.append((f'PLabel{i}',f'{p:g}',left+width*(i+.5)/5,top+height+1,16,True))
    for name,text,x,y,size,center in texts:
        lab=shared.set_label(layer,name,text,size);layer.lt_exec(f'{name}.attach=1;')
        lab.set_float('left',pw*x/100-(lab.get_float('width')/2 if center else 0));lab.set_float('top',ph*y/100)
    yl=layer.label('yl');layer.lt_exec('yl.font=font(Arial);yl.fsize=18;yl.attach=1;')
    yl.set_float('left',pw*(left-5.8)/100-yl.get_float('width')/2);yl.set_float('top',ph*(top+height/2)/100-yl.get_float('height')/2)
    layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
    geometry=[float(op.lt_float('layer.'+x)) for x in ['left','top','width','height']]
    cross=[float(op.lt_float(x)) for x in ['v3','v4','v1','v2']]
    if layer.get_int('unit')!=1 or not np.allclose(geometry,POSITIONS[index],atol=.03) or not np.allclose(geometry,cross,atol=.03):raise RuntimeError('Geometry failed')
    return {'population':pop,'metric':metric,'geometry':geometry,'geometry_crosscheck':cross,
        'limits':[list(layer.xlim),list(layer.ylim)],'fonts':[layer.get_int(a+'.label.font') for a in ['x','y']],
        'tick_sizes':[layer.get_float(a+'.label.pt') for a in ['x','y']]}

def render(args,out):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    for s in plan['sources']:
        if shared.digest(s['path'])!=s['sha256']:raise ValueError('Source hash mismatch')
    for name,sha in plan['table_hashes'].items():
        if shared.digest(out/f'{name}.csv')!=sha:raise ValueError('Plotting table modified')
    if not args.probe:
        ev=json.loads(Path(args.route_evidence).read_text(encoding='utf-8')) if args.route_evidence else {}
        if not(ev.get('status')=='passed' and ev.get('visual_qa')=='passed' and ev.get('experimental_probe') and ev.get('renderer_sha256')==shared.digest(__file__) and ev.get('shared_module_sha256')==shared.digest(shared.__file__)):
            raise ValueError('Formal render requires same-source verified probe evidence')
    wealth=pd.read_csv(out/'wealth_summary.csv');final=pd.read_csv(out/'individual_wealth.csv')
    low=min(0.,float((wealth['mean']-wealth.sd).min()),float(final.accumulate_payoff.min()))
    high=max(float((wealth['mean']+wealth.sd).max()),float(final.accumulate_payoff.max()))
    limwealth=(math.floor(low/50)*50,math.ceil((high+20)/50)*50,100)
    gs=pd.read_csv(out/'session_gini.csv');maxg=float(gs.gini.max())
    limgini=(0,max(.4,math.ceil((maxg+.04)*10)/10),.1)
    with shared.origin_slot(),shared.isolated_origin(not args.probe and not args.close_origin) as op:
        if not args.probe and ev.get('origin_version')!=float(op.lt_float('@V')):
            raise ValueError('Origin version differs from verified probe')
        graph=op.new_graph(template='Line');graph.name='Fig5';sheet_ranges={};roles=[]
        for i,(pop,metric) in enumerate(PANELS):
            layer=graph[0] if i==0 else graph.add_layer()
            data=pd.read_csv(out/f'{pop.lower()}_{metric}.csv')
            wks=op.new_sheet('w',f'Plot{i}');wks.from_df(data);sheet_ranges[f'{pop.lower()}_{metric}']=wks.lt_range(False)
            rr=[]
            def add(y,x,kind,color,typ='l',symbol=2,size=4,trans=0,fill=None):
                plot=layer.add_plot(wks,y,x,type=typ);plot.color=color
                if typ=='s':plot.symbol_kind=symbol;plot.symbol_interior=1;plot.symbol_size=size;plot.transparency=trans
                else:plot.set_cmd('-w 650')
                if typ=='c':plot.set_cmd('-vg 82',f'-pfb color({fill})','-pfm 0')
                visible_color=fill if typ=='c' else color
                rr.append({'kind':kind,'x':x,'y':y,'rgb':[int(visible_color[j:j+2],16) for j in [1,3,5]],'type':typ,'symbol':symbol if typ=='s' else None})
                return plot
            for pi,p in enumerate(P_VALUES):
                for gi,g in enumerate(GROUPS):
                    base=f'P{pi}G{gi}';color=COLORS[pop][pi]
                    if base+('RawY' if metric=='wealth' else 'BarY') not in data:continue
                    if metric=='wealth':
                        add(base+'RawY',base+'RawX','individual',color,'s',SYMBOLS[gi],2.6,65)
                        add(base+'ErrY',base+'ErrX','mean_sd','#202020')
                        add(base+'MeanY',base+'MeanX','mean','#202020','s',SYMBOLS[gi],4.6)
                    else:
                        add(base+'BarY',base+'BarX','gini_bar',color,'c',fill=shade(color,gi))
                        add(base+'SessionY',base+'SessionX','session_gini','#202020','s',SYMBOLS[gi],3.8)
            roles.append(rr);shared.event('panel_built',panel=i+1,plot_count=len(rr))
        for name in ['individual_wealth','wealth_summary','session_gini','gini_summary']:
            wks=op.new_sheet('w',name[:12]);wks.from_df(pd.read_csv(out/f'{name}.csv'));sheet_ranges[name]=wks.lt_range(False)
        graph.activate();op.lt_exec(f'page.updatetoprinter=0;page.kar=0;page.width=({PAGE_CM[0]}/2.54)*page.resx;page.height=({PAGE_CM[1]}/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'))
        states=[]
        for i,layer in enumerate(graph):
            state=style(op,graph,layer,i,limwealth if i<2 else limgini)
            if i<2:
                # Mean samples are black; shape identifies role and legends remain editable.
                plots=layer.plot_list();samples=[]
                for gi in range(3):
                    candidates=[j+1 for j,r in enumerate(roles[i]) if r['kind']=='mean' and f'G{gi}MeanY' in r['y']]
                    samples.append(f'\\l({candidates[0]}) {GROUPS[gi]}')
                legend=shared.set_label(layer,'GroupLegend','  '.join(samples),13)
                layer.lt_exec('GroupLegend.attach=1;GroupLegend.background=0;')
                pw,ph=op.lt_float('page.width'),op.lt_float('page.height');left,top,width,height=POSITIONS[i]
                legend.set_float('left',pw*(left+width/2)/100-legend.get_float('width')/2)
                legend.set_float('top',ph*8.0/100)
            states.append(state)
        graph.activate();op.lt_exec('doc -uw;')
        dims=[float(op.lt_float('page.'+v))/float(op.lt_float('page.res'+a))*2.54 for v,a in [('width','x'),('height','y')]]
        if not np.allclose(dims,PAGE_CM,atol=.02):raise RuntimeError('Page size differs')
        project=out/'Fig5.opju'
        if not op.save(str(project)):raise RuntimeError('Save failed')
        for ext in ['png','pdf','tif']:graph.save_fig(str(out/f'Fig5.{ext}'),width=4200 if ext!='pdf' else 0)
        if not op.open(str(project)):raise RuntimeError('Reopen failed')
        saved=op.find_graph('Fig5')
        if len(saved)!=4:raise RuntimeError('Four native layers missing')
        for i,layer in enumerate(saved):
            if [layer.get_int(a+'.label.font') for a in ['x','y']]!=states[i]['fonts'] or not np.allclose([layer.get_float(a+'.label.pt') for a in ['x','y']],states[i]['tick_sizes']):
                raise RuntimeError('Saved axis typography differs')
            if not np.allclose(list(layer.xlim),states[i]['limits'][0]) or not np.allclose(list(layer.ylim),states[i]['limits'][1]):
                raise RuntimeError('Saved axis scales differ')
            plots=layer.plot_list()
            if len(plots)!=len(roles[i]):raise RuntimeError('Plot count differs after reopen')
            states[i]['plots']=[]
            for plot,role in zip(plots,roles[i]):
                actual={'pid':plot.get_int('pid'),'range':plot.lt_range(),'rgb':list(plot.color)}
                if actual['rgb']!=role['rgb']:raise RuntimeError(f'Saved color differs: panel={i}, role={role}, actual={actual}')
                if role['type']=='s':
                    actual['symbol']=plot.symbol_kind
                    if actual['pid']!=201 or actual['symbol']!=role['symbol']:raise RuntimeError('Scatter shape differs')
                if role['type']=='c' and actual['pid']!=203:raise RuntimeError('Gini bar is not native column')
                states[i]['plots'].append({**role,**actual})
        for name,address in sheet_ranges.items():
            actual=op.find_sheet('w',address).to_df();expected=pd.read_csv(out/f'{name}.csv')
            if len(actual)!=len(expected):raise RuntimeError('Saved worksheet rows differ')
            for column in expected.select_dtypes(include='number'):
                if not np.allclose(actual[column],expected[column],atol=1e-10,equal_nan=True):raise RuntimeError('Saved worksheet data differ')
        sizes={f'Fig5.{ext}':(out/f'Fig5.{ext}').stat().st_size for ext in ['opju','png','pdf','tif']}
        if min(sizes.values())<=0:raise RuntimeError('Empty export')
        shared.write_json(out/'origin_readback.json',{'status':'passed','experimental_probe':args.probe,
            'origin_version':float(op.lt_float('@V')),'renderer_sha256':shared.digest(__file__),
            'shared_module_sha256':shared.digest(shared.__file__),'layers':states,'page_cm':dims,
            'artifact_sizes':sizes,'saved_project_reopened':True,'saved_numeric_data_verified':True,'visual_qa':'pending'})
        saved.activate()
    shared.event('origin_complete',output=str(out))

def snapshot(out,evidence=None):
    dest=out/'source';dest.mkdir(exist_ok=True)
    for name in ['fig5.py','fig3.py','human_data_cache.py','test_fig5_data_contract.py','verify_fig5_delivery.py','README_fig5.md','run_fig5.ps1']:
        source=Path(__file__).parent/name
        if source.exists():shutil.copy2(source,dest/name)
    if evidence:shutil.copy2(evidence,dest/'verified_route_evidence.json')
    shutil.make_archive(str(out/'Fig5_reproduction_source'),'zip',dest)
    shared.write_json(out/'source_manifest.json',{'main_script':'source/fig5.py','renderer_sha256':shared.digest(__file__),
        'files':{p.name:shared.digest(p) for p in dest.iterdir() if p.is_file()},'argv':sys.argv})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','render','all'])
    parser.add_argument('--llm-session');parser.add_argument('--human',default=str(shared.DEFAULT_HUMAN_WORKBOOK))
    parser.add_argument('--output-dir');parser.add_argument('--probe',action='store_true')
    parser.add_argument('--route-evidence');parser.add_argument('--close-origin',action='store_true')
    parser.add_argument('--origin-python',help='External Python with originpro; required by all if preparation uses another environment')
    args=parser.parse_args()
    if args.command in ['prepare','all']:
        if not args.llm_session:parser.error('--llm-session is required')
        out=Path(args.output_dir).resolve() if args.output_dir else Path(args.llm_session).resolve().parent/f'agent_rounds_Fig5_EditaPlot_{datetime.now():%Y%m%d_%H%M%S}'
        out.mkdir(parents=True,exist_ok=False);prepare(args,out)
    else:
        out=Path(args.output_dir).resolve()
        if (out/'Fig5.opju').exists():raise ValueError('Existing project is not overwritten')
    if args.command in ['render','all']:
        if args.command=='all' and args.origin_python:
            command=[args.origin_python,str(Path(__file__).resolve()),'render','--output-dir',str(out)]
            if args.probe:command.append('--probe')
            if args.close_origin:command.append('--close-origin')
            if args.route_evidence:command+=['--route-evidence',args.route_evidence]
            subprocess.run(command,check=True)
        else:render(args,out)
    snapshot(out,args.route_evidence);shared.event('complete',output=str(out))

if __name__=='__main__':main()
