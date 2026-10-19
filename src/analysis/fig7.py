"""MAIN SCRIPT: reuse Fig.7 directional summaries -> editable native Origin project.

Run with the existing Origin-capable external Python, from the repository root:
python -m src.analysis.fig7
Data preparation, if needed: python -m src.analysis.fig7_prepare
"""
import argparse
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from . import fig3 as shared

CODES = ['CC','CF','FC','FF']
COLORS = ['#0072B2','#E69F00','#009E73','#CC79A7']
SYMBOLS = [1,2,3,4]
POSITIONS = [(8,30,24,48),(40,30,24,48),(72,30,24,48)]
METRICS = ['entrusted_mean','returned_mean','return_ratio']
TITLES = ['Entrusted','Returned','Return-to-entrustment ratio']
YLABS = ['Entrusted amount (tokens)','Returned amount (tokens)',
         'Returned / (3 x entrusted)']
LIMITS = [(0,1.5,.5),(0,3,.5),(0,1,.25)]
PAGE = (36,13)


def prepare(root, out):
    analysis = root/'Fig7_interaction_analysis_20261019'
    manifest = json.loads((analysis/'manifest.json').read_text(encoding='utf-8'))
    for source in manifest['sources']:
        assert shared.digest(source['path']) == source['sha256'], 'Source changed; rerun preparation'
    d = pd.read_csv(analysis/'session_directional_summary.csv')
    out.mkdir(exist_ok=True)
    tables = []
    for panel, metric in enumerate(METRICS):
        columns = {}
        for index, code in enumerate(CODES):
            g = d[d.interaction == code]
            grouped = g.groupby('p')[metric].mean()
            x = g.p.to_numpy()+[-.027,-.009,.009,.027][index]
            # Display offsets separate overlapping session points; Y is unchanged.
            x = x + g.session.map({1:-.004,2:0,3:.004}).to_numpy()
            mx = grouped.index.to_numpy()+[-.027,-.009,.009,.027][index]
            columns[code+'RawX'] = pd.Series(x)
            columns[code+'RawY'] = pd.Series(g[metric].to_numpy())
            columns[code+'MeanX'] = pd.Series(mx)
            columns[code+'MeanY'] = pd.Series(grouped.to_numpy())
        frame = pd.DataFrame(columns)
        frame.to_csv(out/f'panel_{panel+1}.csv',index=False,encoding='utf-8-sig')
        tables.append(frame)
    plan = dict(figure='Fig. 7',approval='User requested retaining only panels a,b,c and first two findings; horizontal three-panel revision.',
        sources=manifest['sources'], summaries_path=str(analysis/'session_directional_summary.csv'),
        summary_sha256=shared.digest(analysis/'session_directional_summary.csv'),
        table_hashes={f'panel_{i+1}.csv':shared.digest(out/f'panel_{i+1}.csv') for i in range(3)},
        codes=dict(CC='constrained trustor, constrained trustee',CF='constrained trustor, free trustee',
                   FC='free trustor, constrained trustee',FF='free trustor, free trustee'),
        colors=dict(zip(CODES,COLORS)), rounds=[1,20],
        elements='Panels a-c only: three session points per condition and type, larger mean markers, dashed visual guides; no uncertainty intervals or significance tests.',
        return_ratio='Within-session sum(returned)/(3*sum(entrusted)); average of three session ratios. Not per-transfer mean or bounded proportion.',
        display_transforms='Deterministic horizontal offsets only; no Y jitter, smoothing, fitting or exclusions.',
        project_only=True, preview='Internal PNG for visual QA; no publication PDF/EPS exports.')
    shared.write_json(out/'analysis_plan.json',plan)
    return tables, plan


def label_at(op, layer, name, text, size, x, y, center=False):
    lab = shared.set_label(layer,name,text,size)
    layer.lt_exec(f'{name}.attach=1;{name}.background=0;')
    lab.set_float('left',op.lt_float('page.width')*x/100-(lab.get_float('width')/2 if center else 0))
    lab.set_float('top',op.lt_float('page.height')*y/100)
    return lab


def render(tables, plan, out):
    preview = Path(tempfile.gettempdir())/'Fig7_abc_Origin_20261019_preview.png'
    with shared.origin_slot(), shared.isolated_origin(True) as op:
        graph=op.new_graph(template='Line');graph.name='Fig7'
        roles=[];addresses={};states=[]
        for i, table in enumerate(tables):
            layer=graph[0] if i==0 else graph.add_layer()
            wks=op.new_sheet('w',f'Panel{i+1}');wks.from_df(table)
            addresses[f'panel_{i+1}.csv']=wks.lt_range(False)
            rr=[]
            def add(y,x,kind,color,typ='s',symbol=1,size=4):
                p=layer.add_plot(wks,y,x,type=typ);p.color=color
                if typ=='s':
                    p.symbol_kind=symbol;p.symbol_interior=1;p.symbol_size=size
                    if kind=='session':p.transparency=25
                else:p.set_cmd('-w 500','-d 2')
                rr.append(dict(x=x,y=y,kind=kind,type=typ,color=color,symbol=symbol if typ=='s' else None))
                return p
            for j,code in enumerate(CODES):
                add(code+'MeanY',code+'MeanX','visual_guide',COLORS[j],'l')
                add(code+'RawY',code+'RawX','session',COLORS[j],symbol=SYMBOLS[j],size=3.7)
                add(code+'MeanY',code+'MeanX','mean',COLORS[j],symbol=SYMBOLS[j],size=6)
            roles.append(rr)
            shared.event('panel_built',panel=i+1)
        summary=pd.read_csv(plan['summaries_path'])
        summary=summary.drop(columns=['mean_gap_contribution','baseline_p0_CC_mean','transfer_weight','wealth_sum'])
        wks=op.new_sheet('w','SessionSummary');wks.from_df(summary)
        summary_address=wks.lt_range(False)
        graph.activate()
        op.lt_exec(f'page.updatetoprinter=0;page.kar=0;page.width=({PAGE[0]}/2.54)*page.resx;page.height=({PAGE[1]}/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'))
        for i,layer in enumerate(graph):
            layer.activate();left,top,width,height=POSITIONS[i]
            layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.fixed=1;layer.factor=1;layer.maxpts=0;')
            layer.axis('x').set_limits(-.075,1.075,.25)
            layer.axis('y').set_limits(*LIMITS[i])
            font=int(op.lt_float('font(Arial)'))
            for axis in ['x','y']:
                for key,value in [('showAxes',3),('showLabels',1),('ticks',5),('minorTicks',0),('atZero',0),('label.table',0),('label.type',1),('label.numFormat',1),('label.font',font),('label.rotate',0)]:layer.set_int(f'{axis}.{key}',value)
                layer.set_float(f'{axis}.label.pt',16);layer.set_float(f'{axis}.thickness',1)
            layer.axis('x').title='';layer.axis('y').title=YLABS[i]
            for name in ['Legend','legend','xb']:
                lab=layer.label(name)
                if lab:layer.remove_label(lab)
            for key in ['showLabels','showlabel','label.show']:layer.set_int('x.'+key,0)
            label_at(op,layer,'Panel',f'({chr(97+i)})',19,left-3,top-12)
            label_at(op,layer,'Heading',TITLES[i],18,left+width/2,top-12,True)
            for j,p in enumerate([0,.25,.5,.75,1]):
                label_at(op,layer,f'PLabel{j}',f'{p:g}',16,left+width*(p+.075)/1.15,top+height+2,True)
            label_at(op,layer,'XCaption','Fraction of free players, p',17,left+width/2,top+height+9,True)
            yl=layer.label('yl');layer.lt_exec('yl.font=font(Arial);yl.fsize=17;yl.attach=1;')
            yl.set_float('left',op.lt_float('page.width')*(left-6)/100-yl.get_float('width')/2)
            yl.set_float('top',op.lt_float('page.height')*(top+height/2)/100-yl.get_float('height')/2)
            if i==0:
                text='    '.join(f'\\l({j*3+3}) {code}' for j,code in enumerate(CODES))
                label_at(op,layer,'TypeLegend',text,16,50,2,True)
                label_at(op,layer,'LegendKey','First letter: trustor; second: trustee.  C: constrained; F: free.',14,50,12,True)
            layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
            geo=[float(op.lt_float('layer.'+s)) for s in ['left','top','width','height']]
            cross=[float(op.lt_float(s)) for s in ['v3','v4','v1','v2']]
            assert np.allclose(geo,POSITIONS[i],atol=.03) and np.allclose(geo,cross,atol=.03)
            # All points must be inside the registered plotting bounds.
            vals=np.concatenate([tables[i][c].dropna().to_numpy() for c in tables[i] if c.endswith('RawY')])
            assert vals.min()>=LIMITS[i][0] and vals.max()<=LIMITS[i][1], (i,vals.min(),vals.max())
            states.append(dict(geometry=geo,geometry_crosscheck=cross,xlim=list(layer.xlim),ylim=list(layer.ylim),
                font=font,tick_sizes=[layer.get_float(a+'.label.pt') for a in ['x','y']],plots=roles[i]))
        graph.activate();op.lt_exec('doc -uw;')
        dims=[float(op.lt_float('page.'+v))/float(op.lt_float('page.res'+a))*2.54 for v,a in [('width','x'),('height','y')]]
        assert np.allclose(dims,PAGE,atol=.02)
        project=out/'Fig7_abc_final.opju'
        # Keep previous editable deliveries intact, including open/locked ones.
        if project.exists():
            project=out/f'Fig7_abc_final_{datetime.now():%Y%m%d_%H%M%S}.opju'
        assert op.save(str(project))
        graph.save_fig(str(preview),width=2400)
        assert op.open(str(project))
        saved=op.find_graph('Fig7');assert len(saved)==3
        for i,layer in enumerate(saved):
            assert np.allclose(layer.xlim,states[i]['xlim']) and np.allclose(layer.ylim,states[i]['ylim'])
            assert [layer.get_int(a+'.label.font') for a in ['x','y']]==[states[i]['font']]*2
            assert np.allclose([layer.get_float(a+'.label.pt') for a in ['x','y']],states[i]['tick_sizes'])
            assert len(layer.plot_list())==len(roles[i])
            for p,r in zip(layer.plot_list(),roles[i]):
                assert list(p.color)==[int(r['color'][j:j+2],16) for j in [1,3,5]]
                if r['type']=='s':assert p.get_int('pid')==201 and p.symbol_kind==r['symbol']
            for name in ['Panel','Heading','XCaption','yl']:
                assert layer.label(name)
        for name,address in addresses.items():
            actual=op.find_sheet('w',address).to_df();expected=pd.read_csv(out/name)
            assert actual.shape==expected.shape
            assert np.allclose(actual.to_numpy(dtype=float),expected.to_numpy(dtype=float),equal_nan=True,atol=1e-10)
        actual=op.find_sheet('w',summary_address).to_df()
        for col in summary.select_dtypes(include='number'):
            assert np.allclose(actual[col],summary[col],atol=1e-10,equal_nan=True)
        shared.write_json(out/'origin_readback.json',dict(status='passed',visual_qa='pending',
            origin_version=float(op.lt_float('@V')),saved_project_reopened=True,
            saved_numeric_data_verified=True,page_cm=dims,layers=states,internal_preview=str(preview),
            renderer_sha256=shared.digest(__file__),project_path=str(project),project_bytes=project.stat().st_size,
            project_only=True,route='Three native line/scatter panels a-c; project-only delivery as previously requested.'))
        saved.activate()
    print(str(preview),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path(__file__).resolve().parents[2]/'outputs'/'llm_experiment_datas_summary')
    args=parser.parse_args();root=args.input.resolve()
    out=root/'Fig7_complete_Origin_20261019'
    tables,plan=prepare(root,out)
    render(tables,plan,out)
    source=out/'source';source.mkdir(exist_ok=True)
    for name in ['fig7.py','fig7_prepare.py','fig3.py','README_fig7.md']:
        shutil.copy2(Path(__file__).with_name(name),source/name)
    shared.event('origin_complete',output=str(out))


if __name__=='__main__':main()
