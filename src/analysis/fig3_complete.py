"""MAIN: complete three-session Fig3, Fig4 LLM colours, tight PDF/EPS only.

Uses existing Fig3 scientific tables and tested native Origin box/point/CI route.
The renderer below is a static adaptation, not dynamic source execution.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
try:
    from . import fig3 as base
except ImportError:
    import fig3 as base

P_VALUES=base.P_VALUES
PANELS=base.PANELS
LLM_COLORS=['#0072B2','#E69F00','#009E73','#CC79A7','#D55E00']
HUMAN_COLORS=base.HUMAN_COLORS
digest,event,write_json=base.digest,base.event,base.write_json
origin_slot,isolated_origin=base.origin_slot,base.isolated_origin
style_layer,box_fill_color=base.style_layer,base.box_fill_color

def provenance(root,paths):
    records=[];configs=[]
    for source in paths:
        sha=digest(source)
        matches=[p for p in root.parent.glob('*/agent_rounds.csv') if digest(p)==sha]
        if len(matches)!=1:raise ValueError('Expected one hash-matching original run for each summary CSV')
        original=matches[0];config_path=original.parent/'config.json'
        cfg=json.loads(config_path.read_text(encoding='utf-8'));configs.append(cfg['params'])
        event_path=original.parent/'events.jsonl';models=set();n=0
        def collect(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k=='response_model' and isinstance(v,str):models.add(v)
                    elif isinstance(v,(dict,list)):collect(v)
            elif isinstance(obj,list):
                for value in obj:collect(value)
        with event_path.open(encoding='utf-8') as stream:
            for line in stream:
                entry=json.loads(line);collect(entry);n+=1
        if models!=set(cfg['params']['model_type_list']):raise ValueError('Response model differs from original run configuration')
        records.append({'selected_csv':str(source),'selected_csv_sha256':sha,'original_csv':str(original),
            'original_config':str(config_path),'config_sha256':digest(config_path),'configuration':cfg,
            'response_models':sorted(models),'event_lines_checked':n,'event_path':str(event_path)})
    if any(cfg!=configs[0] for cfg in configs[1:]):raise ValueError('Original run parameters differ; scientific review required')
    sidecar=root/'session_3_llm_trust_game'/'config.json'
    extra=json.loads(sidecar.read_text(encoding='utf-8'))
    return {'sessions':records,'original_parameters_equal':True,
        'copied_sidecar':str(sidecar),'copied_sidecar_sha256':digest(sidecar),
        'copied_sidecar_model':extra['params']['model_type_list'],
        'copied_sidecar_model_conflicts_with_original':extra['params']['model_type_list']!=configs[2]['model_type_list'],
        'decision':'Use selected immutable CSVs. Record original-run metadata and all response-model fields. Do not repair copied or original configuration files.'}

def prepare(args,out):
    root=Path(args.root).resolve();paths=[root/f'agent_rounds_session_{i}.csv' for i in [1,2,3]]
    if not all(p.is_file() for p in paths):raise FileNotFoundError('Three session CSVs are required')
    audit=provenance(root,paths)
    args.llm_session=[str(p) for p in paths];args.rounds=20;args.human_cache_dir=None
    plan=base.prepare(args,out)
    assert plan['counts']['LLM']['sessions']==3 and plan['counts']['Human']['sessions']==3
    assert plan['counts']['LLM']['individual_means']==735 and plan['counts']['Human']['individual_means']==735
    plan['figure']='Fig. 3 complete three-session reproduction'
    plan['palettes']['LLM']=LLM_COLORS
    plan['palette_provenance']='User: LLM p colours follow Fig4; Human colours retained.'
    plan['confirmed_choices']='Three supplied distinct LLM sessions plus three Human sessions; first20 rounds each; two rows x four columns; upper boxes and all individual means without CI; lower mean +/- conventional individual-level t95 CI; PDF/EPS only; tight margins.'
    plan['provenance_audit']=audit
    plan['export']={'formal_formats':['pdf','eps'],'margin':'tight tr.Margin=1','opaque_marks':True}
    for item in audit['sessions']:plan['sources'].append({'path':item['original_config'],'sha256':item['config_sha256'],'kind':'Hash-matched original run configuration'})
    plan['sources'].append({'path':audit['copied_sidecar'],'sha256':audit['copied_sidecar_sha256'],'kind':'Conflicting copied sidecar, preserved for audit only'})
    plan['axis_policy']='Within each row, populations share metric-specific limits. Upper includes every individual mean; lower includes all mean CI bounds.'
    write_json(out/'analysis_plan.json',plan);write_json(out/'provenance_audit.json',audit)
    (out/'Fig3_notes.md').write_text("""# Complete Figure3

Main: src/analysis/fig3_complete.py. Three distinct LLM CSVs and three Human sessions; both use first20 rounds. Each upper point is one individual's mean of its20 round totals. There are147 individuals per p per population,735 per population,1470 individual means in total. Sessions are part of each identity; agent IDs shared between sessions are never collapsed. All records and corrected decisions are retained. Entrusted and returned are outgoing totals across four neighbours, not divided by four.

Layout: columns LLM Entrusted, Human Entrusted, LLM Returned, Human Returned. Upper panels contain native25–75% quartile boxes, individual means and horizontal mean marks, without CI. Lower panels show means and conventional95% t intervals across individual means: mean +/- t(.975,n-1)*sampleSD/sqrt(n), n=147 per p. These retain the previously approved Fig3 definition. They are NOT between-session confidence intervals and do not account for within-network dependence; no inferential claims or significance tests are made. Session means and between-session spread are supplied separately for audit.

LLM condition colours for p=0,.25,.5,.75,1 follow Fig4: #0072B2,#E69F00,#009E73,#CC79A7,#D55E00. Corresponding boxes and intervals use the same condition mapping. Human colours are unchanged. Opaque pale box fills and opaque symbols avoid EPS transparency problems; individual Y values are unchanged. Horizontal jitter is deterministic display only. LLM distribution symbols remain hollow circles; Human distribution symbols are filled. All points are retained. Within each row, LLM and Human share the same metric scale. Upper and lower ranges differ to distinguish individual dispersion from mean comparisons, without axis breaks.

Provenance: each summary CSV matches an original-run CSV byte-for-byte. All original parameter dictionaries and all recorded response_model fields agree on deepseek-flash. The copied session3 config instead says deepseek-v4-pro; it is inconsistent with its hash-matched original config and runtime response records, is preserved unchanged, and is not used to relabel the data. Details and original paths are in provenance_audit.json.

Formal image exports are PDF and EPS only, with Origin tight bounding margins. Internal editable OPJU/PNG verification artifacts are in the temporary QA directory recorded in origin_readback.json. Raw data remain unchanged. No smoothing, outlier removal, invented replication or alteration of summary values.

Caption: Distributions and means of entrusted and returned amounts over the first20 rounds. Columns compare LLM agents and human participants for each behavioural metric. Upper panels show individual20-round means, quartile boxes and mean marks. Lower panels show population means with conventional95% t intervals across individual means. Three sessions contribute49 individuals each per condition; individuals interacting within a session are dependent, so these intervals are descriptive and do not estimate between-session uncertainty. Colours encode the nominal fraction of free players.
""",encoding='utf-8')

def render(args, out):
    plan=json.loads((out/'analysis_plan.json').read_text(encoding='utf-8'))
    for source in plan['sources']:
        if digest(source['path']) != source['sha256']:
            raise ValueError('Input hash changed since preparation')
    for name, sha in plan['table_hashes'].items():
        if digest(out/f'{name}.csv') != sha:
            raise ValueError('Prepared table hash changed')
    if not args.probe:
        evidence=json.loads(Path(args.route_evidence).read_text(encoding='utf-8')) if args.route_evidence else {}
        assert evidence.get('status')=='passed' and evidence.get('visual_qa')=='passed' and evidence.get('experimental_probe')
        assert evidence.get('renderer_sha256')==digest(__file__) and evidence.get('shared_module_sha256')==digest(base.__file__)
    qa=Path(tempfile.gettempdir())/('Fig3_Complete_QA_'+out.name)
    qa.mkdir(parents=True,exist_ok=False)
    summary=pd.read_csv(out/'summary.csv')
    long=pd.read_csv(out/'individual_means_long.csv')
    event('origin_render_start', mode='isolated', experimental_probe=args.probe)
    with origin_slot(), isolated_origin(not args.close_origin and not args.probe) as op:
        if not args.probe:assert evidence['origin_version']==float(op.lt_float('@V'))
        ticks=op.new_sheet('w','Ticks')
        ticks.from_list(0,[1,2,3,4,5],'Center')
        ticks.from_list(1,['0','0.25','0.5','0.75','1'],'p')
        saved_tables={}
        for table in ['individual_means','summary','session_summary','between_session_summary','round_means']:
            sheet=op.new_sheet('w',table.replace('_','').title()[:20])
            sheet.from_df(pd.read_csv(out/f'{table}.csv'))
            saved_tables[table]=sheet.lt_range(False)
        pages=[]
        roles=[]
        for row in range(2):
            for col,(pop,metric) in enumerate(PANELS):
                colors=LLM_COLORS if pop=='LLM' else HUMAN_COLORS
                rows=summary[(summary.population==pop)&(summary.metric==metric)].sort_values('p')
                if row==0:
                    # Native Origin box plot, linked to the individual-average worksheet.
                    raw=pd.read_csv(out/f'{pop.lower()}_{metric}_wide.csv')
                    wks=op.new_sheet('w',f'{pop}{metric.title()}')
                    wks.from_df(raw)
                    wks.cols_axis('yyyyy')
                    wks.activate()
                    command=f'plotgboxraw irng:={wks.lt_range(False)}!1:5 num:=1 g1:="Long Name" sort:=0 theme:="Box_Dashed Whisker Thick Median";'
                    if not op.lt_exec(command):
                        raise RuntimeError('Origin box graph creation failed')
                    graph=op.find_graph()
                    layer=graph[0]
                    layer.group(False)
                    boxes=layer.plot_list()
                    if len(boxes)!=5: raise RuntimeError('Expected five native boxes')
                    for i,(plot,color) in enumerate(zip(boxes,colors),1):
                        plot.color=color
                        plot.set_cmd(f'-pfb color({box_fill_color(color)})',f'-pbc color({color})','-pbw 0.7')
                        plot.transparency=0
                        plot.symbol_size=0  # Native outlier symbols hidden; overlay retains every observation exactly once.
                        layer.set_int(f'plot{i}.boxchart.type',1)
                        # Origin 2021 modern box-range enum (separate Box Style):
                        # native BCBT_25_75=2, LabTalk's 1-based boxRange=3.
                        # Older web documentation included No Box in this enum;
                        # do not use that obsolete numbering on the tested host.
                        layer.set_int(f'plot{i}.boxchart.boxRange',3)
                        layer.set_int(f'plot{i}.boxchart.line',1)
                        layer.set_float(f'plot{i}.boxchart.width',52)
                    helper=pd.DataFrame()
                    for i,p in enumerate(P_VALUES):
                        values=raw.iloc[:,i].dropna().to_numpy()
                        helper[f'X{i}']=pd.Series(i+1+np.random.default_rng(20261011+i).uniform(-.16,.16,len(values)))
                        helper[f'Y{i}']=pd.Series(values)
                    pts=op.new_sheet('w',f'{pop}{metric.title()}Pts')
                    pts.from_df(helper)
                    pts.cols_axis('xy'*5)
                    for i,color in enumerate(colors):
                        plot=layer.add_plot(pts,2*i+1,2*i,type='s')
                        plot.color=color
                        plot.symbol_kind=2
                        plot.symbol_interior=0 if pop=='LLM' else 1
                        plot.symbol_size=3.5 if pop=='LLM' else 3.2
                        plot.transparency=0
                    # Explicit mean line, independently editable and unambiguous.
                    meanpoints=pd.DataFrame({f'X{i}':pd.Series([i+.77,i+1.23]) for i in range(5)})
                    for i,value in enumerate(rows['mean']): meanpoints[f'Y{i}']=[value,value]
                    meansheet=op.new_sheet('w',f'{pop}{metric.title()}Mean')
                    meansheet.from_df(meanpoints)
                    for i,color in enumerate(colors):
                        plot=layer.add_plot(meansheet,f'Y{i}',f'X{i}',type='l')
                        plot.color='#245B9A' if pop=='LLM' else color
                        plot.set_cmd('-w 900')
                    kind='box_distribution'
                else:
                    event('lower_panel_start', column=col)
                    graph=op.new_graph(template='Line')
                    layer=graph[0]
                    data=pd.DataFrame({'Center':range(1,6),'p':P_VALUES,
                        'Mean':rows['mean'].to_numpy(),'CI95':rows.ci95_half_width.to_numpy()})
                    wks=op.new_sheet('w',f'{pop}{metric.title()}CI')
                    wks.from_df(data)
                    event('lower_table_imported', column=col)
                    wks.cols_axis('xxyy')
                    connector=layer.add_plot(wks,'Mean','Center',type='l')
                    connector.color='#333333'
                    connector.set_cmd('-w 600','-d 1')
                    event('lower_connector_ready', column=col)
                    for i,color in enumerate(colors):
                        one=op.new_sheet('w',f'CI{col}{i}')
                        center, mean, half = float(i+1), float(rows['mean'].iloc[i]), float(rows.ci95_half_width.iloc[i])
                        # Editable worksheet-linked interval/cap primitives avoid
                        # Origin 2021's unstable one-row add_plot(colyerr) route.
                        one.from_df(pd.DataFrame({'PointX':[center,np.nan,np.nan,np.nan,np.nan,np.nan],
                            'PointY':[mean,np.nan,np.nan,np.nan,np.nan,np.nan],
                            'IntervalX':[center,center,np.nan,np.nan,np.nan,np.nan],
                            'IntervalY':[mean-half,mean+half,np.nan,np.nan,np.nan,np.nan],
                            'CapX':[center-.065,center+.065,np.nan,center-.065,center+.065,np.nan],
                            'CapY':[mean-half,mean-half,np.nan,mean+half,mean+half,np.nan]}))
                        one.cols_axis('xyxyxy')
                        for y,x in [('IntervalY','IntervalX'),('CapY','CapX')]:
                            interval=layer.add_plot(one,y,x,type='l')
                            interval.color=color
                            interval.set_cmd('-w 650')
                        plot=layer.add_plot(one,'PointY','PointX',type='s')
                        plot.color=color
                        plot.symbol_kind=2
                        plot.symbol_interior=1
                        plot.symbol_size=5.0
                    kind='mean_ci'
                graph.name=f'Panel{row*4+col+1}'
                pages.append(graph)
                roles.append({'population':pop,'metric':metric,'kind':kind,'upper_ci':False if row==0 else None})
                event('panel_built', panel=graph.name, population=pop, metric=metric)
        expression='+char(10)$+'.join(f'"{page.name}"' for page in pages)
        if not op.lt_exec(f'merge_graph option:=specified graphs:={expression} keep:=1 arrange:=0 row:=2 col:=4 groupgraph:=1 linkarrange:=0 labeltext:=none;'):
            raise RuntimeError('Origin eight-panel merge failed')
        graph=op.find_graph()
        graph.name='Fig3'
        if len(graph)!=8: raise RuntimeError('Expected eight editable graph layers')
        # 36 x 20 cm working canvas; final resizing should preserve legibility.
        graph.activate()
        op.lt_exec('page.updatetoprinter=0;page.kar=0;page.width=(36/2.54)*page.resx;page.height=(20/2.54)*page.resy;doc -uw;')
        graph.set_int('background',op.ocolor('#FFFFFF'))
        limits={}
        mean_limits={}
        for metric in ['entrusted','returned']:
            maxval=float(long.loc[long.metric==metric,'amount'].max())
            maxci=float(summary.loc[summary.metric==metric,'ci95_high'].max())
            upper=max(maxval,maxci)
            step=1 if metric=='entrusted' else 2 if upper<=16 else 5
            limits[metric]=(0, math.ceil(upper/step)*step+step*.15, step)
            mean_step=1 if metric=='entrusted' else 2 if maxci<=16 else 5
            mean_limits[metric]=(0, math.ceil(maxci/mean_step)*mean_step+mean_step*.15, mean_step)
        readback=[]
        for i,(layer,role) in enumerate(zip(graph,roles)):
            row,col=divmod(i,4)
            # Same limits for human/LLM of each metric; no axis breaks.
            heading=f"{role['population']} | {role['metric'].title()}"
            position=(6.4+24.1*col,10.5+46.5*row,17.8,31.0)
            state=style_layer(op,graph,layer,position,(limits if row==0 else mean_limits)[role['metric']],chr(97+i),heading,row==1)
            state.update(role)
            state['plots']=[{'range':p.lt_range(),'pid':p.get_int('pid'),
                'rgb':list(p.color),'line_width':p.get_float('line.width')} for p in layer.plot_list()]
            if row==0 and len(state['plots'])!=15:
                raise RuntimeError('Upper panel must contain 5 boxes, 5 scatters and 5 mean lines')
            if row==0:
                state['native_box_ranges']=[plot.get_int('boxchart.boxRange') for plot in layer.plot_list()[:5]]
                state['box_fill_colors']=[box_fill_color(color) for color in (LLM_COLORS if role['population']=='LLM' else HUMAN_COLORS)]
                if state['native_box_ranges']!=[3]*5:
                    raise RuntimeError('Origin box range is not the 25th--75th percentiles')
            readback.append(state)
        graph.activate()
        op.lt_exec('doc -uw;')
        opju=qa/'Fig3_internal.opju'
        if not op.save(str(opju)): raise RuntimeError('Origin project save failed')
        for ext in ['pdf','eps']:
            assert op.lt_exec(f'expGraph -sw type:={ext} filename:="Fig3" path:="{out}" overwrite:=replace tr.Margin:=1 tr.SpeedMode:=2;')
        graph.save_fig(str(qa/'Fig3_preview.png'),width=4200)
        artifact_sizes={f'Fig3.{ext}':(out/f'Fig3.{ext}').stat().st_size for ext in ['pdf','eps']}
        if any(size<=0 for size in artifact_sizes.values()): raise RuntimeError('Empty export')
        write_json(out/'origin_readback.json',{'status':'pending_saved_project_check',
            'origin_version':float(op.lt_float('@V')),'graph':'Fig3','layers':readback,
            'artifact_sizes':artifact_sizes,'visual_qa':'pending'})
        # Reopen the SAVED OPJU, then verify layer counts and source worksheets.
        if not op.open(str(opju)): raise RuntimeError('Saved OPJU reopen failed')
        saved=op.find_graph('Fig3')
        if saved is None or len(saved)!=8: raise RuntimeError('Saved graph not editable/reopenable')
        for layer in list(saved)[:4]:
            if [plot.get_int('boxchart.boxRange') for plot in layer.plot_list()[:5]]!=[3]*5:
                raise RuntimeError('Saved quartile-box range did not persist')
        expected=pd.read_csv(out/'individual_means.csv')
        saved_sheet=op.find_sheet('w',saved_tables['individual_means'])
        if saved_sheet is None: raise RuntimeError('Saved individual-average workbook missing')
        actual=saved_sheet.to_df()
        if len(actual)!=len(expected): raise RuntimeError('Saved individual table row count differs')
        for col in ['entrusted','returned']:
            if not np.allclose(actual[col],expected[col],atol=1e-12): raise RuntimeError('Saved individual means differ')
        write_json(out/'origin_readback.json',{'status':'passed','experimental_probe':args.probe,
            'origin_version':float(op.lt_float('@V')),'graph':'Fig3','layers':readback,
            'artifact_sizes':artifact_sizes,'saved_project_reopened':True,
            'saved_numeric_data_verified':True,'visual_qa':'pending'})
        for name,address in saved_tables.items():
            expected_table=pd.read_csv(out/f'{name}.csv');actual_table=op.find_sheet('w',address).to_df()
            assert len(expected_table)==len(actual_table)
            for column in expected_table.select_dtypes(include='number'):
                assert np.allclose(expected_table[column],actual_table[column],atol=1e-12,equal_nan=True)
        for index,layer in enumerate(saved):
            population=PANELS[index%4][0];colors=LLM_COLORS if population=='LLM' else HUMAN_COLORS
            plots=layer.plot_list()
            targets=plots[5:10] if index<4 else [plots[3+3*i] for i in range(5)]
            for plot,color in zip(targets,colors):
                assert plot.get_int('pid')==201 and list(plot.color)==[int(color[j:j+2],16) for j in [1,3,5]]
        report=json.loads((out/'origin_readback.json').read_text(encoding='utf-8'))
        report.update(renderer_sha256=digest(__file__),shared_module_sha256=digest(base.__file__),
            qa_directory=str(qa),preview=str(qa/'Fig3_preview.png'),internal_project=str(opju),
            saved_all_numeric_data_verified=True,saved_scatter_colours_verified=True,
            route_evidence=args.route_evidence,export_margin='tight tr.Margin=1',formal_formats=['pdf','eps'])
        write_json(out/'origin_readback.json',report)
        for source in plan['sources']:
            if digest(source['path'])!=source['sha256']:raise RuntimeError('Source changed during Origin rendering')
        saved.activate()
    event('origin_complete', output=str(out))

def snapshot(out,evidence=None):
    dest=out/'source';dest.mkdir(exist_ok=True)
    for name in ['fig3_complete.py','fig3.py','human_data_cache.py','README_fig3_complete.md','run_fig3_complete.ps1']:
        source=Path(__file__).with_name(name)
        if source.exists():shutil.copy2(source,dest/name)
    if evidence:shutil.copy2(evidence,dest/'verified_route_evidence.json')
    shutil.make_archive(str(out/'Fig3_reproduction_source'),'zip',dest)
    write_json(out/'source_manifest.json',{'main_script':'source/fig3_complete.py','files':{p.name:digest(p) for p in dest.iterdir() if p.is_file()},'argv':sys.argv})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','render','all']);parser.add_argument('--root')
    parser.add_argument('--human',default=str(base.DEFAULT_HUMAN_WORKBOOK));parser.add_argument('--output-dir')
    parser.add_argument('--origin-python');parser.add_argument('--probe',action='store_true')
    parser.add_argument('--route-evidence');parser.add_argument('--close-origin',action='store_true');args=parser.parse_args()
    if args.command in ['prepare','all']:
        if not args.root:parser.error('--root is required')
        out=Path(args.output_dir).resolve() if args.output_dir else Path(args.root).resolve()/f'Fig3_complete_EditaPlot_{datetime.now():%Y%m%d_%H%M%S}'
        out.mkdir(parents=True,exist_ok=False);prepare(args,out)
    else:
        out=Path(args.output_dir).resolve()
        if (out/'Fig3.pdf').exists():raise ValueError('Existing formal figures will not be overwritten')
    if args.command in ['render','all']:
        if args.origin_python:
            command=[args.origin_python,str(Path(__file__).resolve()),'render','--output-dir',str(out)]
            if args.probe:command.append('--probe')
            if args.route_evidence:command+=['--route-evidence',args.route_evidence]
            if args.close_origin:command.append('--close-origin')
            subprocess.run(command,check=True)
        else:render(args,out)
    snapshot(out,args.route_evidence);event('complete',output=str(out))

if __name__=='__main__':main()
