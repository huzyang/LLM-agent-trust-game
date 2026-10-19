"""MAIN FIGURE SCRIPT: prepare legacy-session data and render editable Fig. 2.

python -m src.analysis.fig2 all --input INPUT --output OUTPUT [--cache CACHE]
python -m src.analysis.fig2 render --output OUTPUT
Origin rendering needs an external Origin-capable Python in the Windows session.
"""
from __future__ import annotations
import argparse
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from . import fig3 as shared
from .fig2_prepare import prepare,PS,COLORS

PAGE=(32,34)
POSITIONS=[(10,9,36,19),(61,9,36,19),(10,41,36,19),(61,41,36,19),(10,75,36,18),(61,75,36,18)]
TITLES=['Entrusted','Returned','Entrusted: terminal judgment','Returned: terminal judgment','Entrusted: individual change','Returned: individual change']
YLABELS=['Mean entrusted amount (tokens)','Mean returned amount (tokens)','Fraction of BDI replies','Fraction of BDI replies','Entrusted change (tokens)','Change in returned fraction']

def label_at(op,layer,name,text,size,x,y,center=False):
    lab=shared.set_label(layer,name,text,size)
    layer.lt_exec(f'{name}.attach=1;{name}.background=0;')
    lab.set_float('left',op.lt_float('page.width')*x/100-(lab.get_float('width')/2 if center else 0))
    lab.set_float('top',op.lt_float('page.height')*y/100)
    return lab

def render(out):
    out=Path(out).resolve()
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    for item in plan['sources']:assert shared.digest(item['path'])==item['sha256'],'Raw source changed'
    tables=[]
    for i in range(6):
        name=f'panel_{chr(97+i)}.csv'
        assert shared.digest(out/name)==plan['table_hashes'][name],'Plot table changed'
        tables.append(pd.read_csv(out/name))
    preview=Path(tempfile.gettempdir())/'Fig2_sixpanel_20261019_preview.png'
    states=[];addresses={};plot_roles=[]
    with shared.origin_slot(),shared.isolated_origin(True) as op:
        graph=op.new_graph(template='Line');graph.name='Fig2'
        for i,frame in enumerate(tables):
            layer=graph[0] if i==0 else graph.add_layer()
            sheet=op.new_sheet('w',f'Panel{chr(65+i)}');sheet.from_df(frame)
            addresses[f'panel_{chr(97+i)}.csv']=sheet.lt_range(False)
            roles=[]
            def add(y,x,color,kind='scatter',symbol=2,fill=0,size=4,alpha=0):
                typ='l' if kind in ['line','zero'] else 's'
                p=layer.add_plot(sheet,y,x,type=typ);p.color=color
                if typ=='s':
                    p.set_cmd(f'-k {symbol}',f'-kf {fill}',f'-z {size}');p.transparency=alpha
                else:p.set_cmd('-w 450' if kind=='line' else '-w 300')
                roles.append(dict(x=x,y=y,type=typ,color=color,kind=kind,symbol=symbol if typ=='s' else None,fill=fill if typ=='s' else None))
                return p
            if i<4:
                for j in range(5):
                    add(f'P{j}','Round',COLORS[j],'line')
                    add(f'P{j}','Round',COLORS[j],symbol=j+1,size=3.7)
            else:
                add('ZeroY','ZeroX','#AAAAAA','zero')
                for j in range(5):
                    for k in range(4):
                        # Native set/get -kf is zero-based: 0 solid, 1 open.
                        # originpro.symbol_interior uses a different index scheme.
                        key=f'P{j}G{k}';symbol=2 if k<2 else 3;fill=0 if k%2 else 1
                        if not frame[key+'Y'].notna().any():continue
                        add(key+'Y',key+'X',COLORS[j],'individual',symbol,fill,3.5,65)
                        add(key+'MeanY',key+'MeanX',COLORS[j],'mean',symbol,fill,8,0)
            plot_roles.append(roles)
            shared.event('panel_built',panel=chr(97+i),plots=len(roles))
        # Numeric source tables remain editable and include all exclusions/groups.
        for name,sheet_name in [('round_summaries.csv','RoundSummary'),('behavior_summary.csv','BehaviorSummary'),('decision_data.csv','DecisionData'),('coding_counts.csv','CodingCounts'),('field_agreement.csv','FieldAgreement')]:
            sheet=op.new_sheet('w',sheet_name);sheet.from_df(pd.read_csv(out/name))
            addresses[name]=sheet.lt_range(False)
        graph.activate()
        op.lt_exec(f'page.updatetoprinter=0;page.kar=0;page.width=({PAGE[0]}/2.54)*page.resx;page.height=({PAGE[1]}/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'))
        for i,layer in enumerate(graph):
            layer.activate();left,top,width,height=POSITIONS[i]
            layer.lt_exec(f'layer.unit=1;layer.left={left};layer.top={top};layer.width={width};layer.height={height};layer.fixed=1;layer.factor=1;layer.maxpts=0;')
            if i<4:layer.axis('x').set_limits(0,20.5,5)
            else:layer.axis('x').set_limits(-.13,1.13,.25)
            if i==0:ylim=(0,5.3,1)
            elif i==1:ylim=(0,10,2)
            elif i<4:ylim=(0,1,.25)
            else:
                vals=np.concatenate([tables[i][r['y']].dropna().to_numpy() for r in plot_roles[i] if r['kind']=='individual'])
                step=1 if i==4 else .25
                low=np.floor(min(vals.min(),0)/step)*step;high=np.ceil(max(vals.max(),0)/step)*step
                ylim=(low-step*.12,high+step*.12,step)
            layer.axis('y').set_limits(*ylim)
            font=int(op.lt_float('font(Arial)'))
            for axis in ['x','y']:
                for key,val in [('showAxes',3),('showLabels',1),('ticks',5),('minorTicks',0),('atZero',0),('label.table',0),('label.type',1),('label.numFormat',1),('label.font',font),('label.rotate',0)]:layer.set_int(f'{axis}.{key}',val)
                layer.set_float(f'{axis}.label.pt',15);layer.set_float(f'{axis}.thickness',1)
            layer.axis('x').title='';layer.axis('y').title=YLABELS[i]
            for name in ['Legend','legend','xb']:
                lab=layer.label(name)
                if lab:layer.remove_label(lab)
            if i>=4:
                for key in ['showLabels','showlabel','label.show']:layer.set_int('x.'+key,0)
                for j,p in enumerate(PS):label_at(op,layer,f'PLabel{j}',f'{p:g}',15,left+width*(p+.13)/1.26,top+height+1,True)
            label_at(op,layer,'Panel',f'({chr(97+i)})',18,left-4,top-4.3)
            label_at(op,layer,'Heading',TITLES[i],17,left+width/2,top-4.3,True)
            label_at(op,layer,'XCaption','Round' if i<4 else 'Fraction of free agents, p',16,left+width/2,top+height+4.2,True)
            yl=layer.label('yl');layer.lt_exec('yl.font=font(Arial);yl.fsize=16;yl.attach=1;')
            yl.set_float('left',op.lt_float('page.width')*(left-6)/100-yl.get_float('width')/2)
            yl.set_float('top',op.lt_float('page.height')*(top+height/2)/100-yl.get_float('height')/2)
            if i==0:
                label_at(op,layer,'PKey','     '.join(f'\\l({j*2+2}) p = {p:g}' for j,p in enumerate(PS)),15,50,1.0,True)
            if i==4:
                label_at(op,layer,'GroupKey10',r'\l(3) R10: no detected judgment     \l(5) R10: judgment',15,50,66.8,True)
                label_at(op,layer,'GroupKey20',r'\l(7) R20: no detected judgment     \l(9) R20: judgment',15,50,69.3,True)
            layer.lt_exec('v1=NA();v2=NA();v3=NA();v4=NA();layer -x;')
            geo=[float(op.lt_float('layer.'+s)) for s in ['left','top','width','height']]
            cross=[float(op.lt_float(s)) for s in ['v3','v4','v1','v2']]
            assert np.allclose(geo,POSITIONS[i],atol=.03) and np.allclose(geo,cross,atol=.03)
            for r in plot_roles[i]:
                y=tables[i][r['y']].dropna()
                assert len(y)==0 or (y.min()>=ylim[0] and y.max()<=ylim[1])
            states.append(dict(geometry=geo,geometry_crosscheck=cross,layer_unit=1,xlim=list(layer.xlim),ylim=list(layer.ylim),font=font,plots=plot_roles[i]))
        graph.activate();op.lt_exec('doc -uw;')
        dims=[float(op.lt_float('page.'+v))/float(op.lt_float('page.res'+a))*2.54 for v,a in [('width','x'),('height','y')]]
        assert np.allclose(dims,PAGE,atol=.02)
        project=out/'Fig2_final.opju'
        if project.exists():project=out/f'Fig2_final_{datetime.now():%Y%m%d_%H%M%S}.opju'
        assert op.save(str(project))
        graph.save_fig(str(preview),width=2600)
        assert op.open(str(project));saved=op.find_graph('Fig2');assert len(saved)==6
        for i,layer in enumerate(saved):
            assert np.allclose(layer.xlim,states[i]['xlim']) and np.allclose(layer.ylim,states[i]['ylim'])
            assert len(layer.plot_list())==len(plot_roles[i])
            for axis in ['x','y']:
                assert layer.get_int(axis+'.label.font')==states[i]['font']
                assert np.isclose(layer.get_float(axis+'.label.pt'),15)
            for p,r in zip(layer.plot_list(),plot_roles[i]):
                assert list(p.color)==[int(r['color'][j:j+2],16) for j in [1,3,5]]
                if r['type']=='s':
                    assert p.get_int('pid')==201
                    for option,expected in [('-k',r['symbol']),('-kf',r['fill'])]:
                        assert p.layer.LT_execute(f'{{range rr={p.lt_range()};get rr {option} fig2symbolread;}}')
                        actual=float(op.lt_float('fig2symbolread'))
                        assert np.isfinite(actual) and actual==expected,(i,option,actual,expected)
            for name in ['Panel','Heading','XCaption','yl']:assert layer.label(name)
        for name,address in addresses.items():
            expected=pd.read_csv(out/name);actual=op.find_sheet('w',address).to_df()
            assert actual.shape==expected.shape,(name,actual.shape,expected.shape)
            for col in expected.select_dtypes(include='number').columns:
                assert np.allclose(actual[col].to_numpy(dtype=float),expected[col].to_numpy(dtype=float),equal_nan=True,atol=1e-10),(name,col)
        shared.write_json(out/'origin_readback.json',dict(status='passed',visual_qa='pending',origin_version=float(op.lt_float('@V')),
          project_path=str(project),project_sha256=shared.digest(project),project_bytes=project.stat().st_size,
          saved_project_reopened=True,native_editable_layers=6,numeric_tables_verified=True,page_cm=dims,layers=states,
          internal_preview=str(preview),renderer_sha256=shared.digest(__file__),project_only=True,text_coding_status=plan['status']))
        saved.activate()
    source=out/'source';source.mkdir(exist_ok=True)
    for name in ['fig2.py','fig2_prepare.py','fig2_screening.py','fig3.py','README_fig2.md']:
        shutil.copy2(Path(__file__).with_name(name),source/name)
    (source/'__init__.py').touch()
    shared.event('fig2_complete',output=str(out),project=str(project),preview=str(preview))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=['prepare','render','all'])
    ap.add_argument('--input',type=Path);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--cache',type=Path);ap.add_argument('--adjudication',type=Path)
    a=ap.parse_args()
    if a.stage in ['prepare','all']:
        if a.input is None:ap.error('--input is required for prepare/all')
        prepare(a.input,a.output,a.cache,a.adjudication)
    if a.stage in ['render','all']:render(a.output)

if __name__=='__main__':main()
