"""Fig. 2 data preparation: five legacy JSON sessions, transparent text coding.

MAIN ANALYSIS SCRIPT. See README_fig2.md. No Origin dependency.
The text labels are reproducible automated operational labels, not human coding.
Optional adjudication CSV overrides are applied with an audit trail.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

PS = [0, .25, .5, .75, 1]
COLORS = ['#0072B2','#E69F00','#009E73','#CC79A7','#D55E00']
LABELS = ['explicit_current','possible_adopted','no_detected_current','uncertain_or_conflicting']
POS = set(LABELS[:2])
END = re.compile(r'\b(?:final|last|terminal)[ -]round\b|\bno (?:future|further|more) (?:rounds?|interactions?|reciprocity|cooperation)\b|\bend[ -]?game\b|\bend of (?:the )?(?:game|experiment)', re.I)
CURRENT = re.compile(
 r'\b(?:this|current) (?:is |being |round is |round being )?(?:(?:indeed|the|a|likely|possibly|probably|perhaps|potentially|presumably|apparently) )*(?:final|last|terminal)[ -]round\b'
 r'|\b(?:this|it|current round|this round) (?:is )?(?:may be|might be|could be|seems to be|appears to be) (?:the |a )?(?:final|last)[ -]round\b'
 r'|\b(?:round \d+|we are|we.re|it is|it.s) (?:is |in |being )?(?:(?:the|likely|possibly|probably|perhaps) )*(?:final|last)[ -]round\b'
 r'|\b(?:given|being|as) the (?:final|last)[ -]round\b'
 r'|^(?:belief\s*:\s*)?in the final[ -]round\b'
 r'|\bno (?:future|further|more) (?:rounds?|interactions?|reciprocity|cooperation)\b', re.I)
POSS = re.compile(r'\b(?:likely|possibly|probably|perhaps|potentially|presumably|apparently) (?:the |a )?(?:final|last)[ -]round\b|\b(?:may|might|could|seems to|appears to) be (?:the |a )?(?:final|last)[ -]round\b|\b(?:if|assuming) (?:this is|it is|it.s) (?:the |a )?(?:final|last)[ -]round\b|\b(?:assuming|assumption).{0,45}(?:final|last)[ -]round', re.I)
REJECT = re.compile(r'\b(?:no|not any) (?:clear |explicit )?(?:indication|evidence|information).{0,55}(?:final|last)[ -]round|\b(?:do not|don.t|cannot|can.t) (?:expect|assume|conclude).{0,45}(?:final|last)[ -]round|\b(?:this is|it is|this round is) not (?:necessarily )?(?:the )?(?:final|last)[ -]round|\b(?:assume|assuming|given|since|now|but) (?:that )?(?:the )?(?:game|experiment) (?:continues|will continue)|\b(?:game|experiment) (?:unexpectedly )?(?:continues(?! (?:the )?(?:same )?pattern)|has continued|will continue)\b|\b(?:must|should) assume (?:the )?(?:game|experiment) (?:might |may )?continue\b', re.I)
UNCERT = re.compile(r'\b(?:do not know|don.t know|cannot be certain|no certainty|not sure|unsure|uncertain|without certainty|may or may not|whether this is)\b', re.I)
LINK = re.compile(r'\b(?:since|because|given|therefore|thus|hence|so|to maximize|no incentive|no strategic|no future|optimal|rational)\b', re.I)
ACTION = re.compile(r'\b(?:send|sending|invest\w*|return\w*|keep\w*|retain\w*|defect\w*|cooperat\w*|reciproc\w*|maintain\w*|continu\w*|withhold\w*|payoff\w*|profit\w*)\b', re.I)
HISTORY = re.compile(r'\b(?:previous|prior) (?:round|assumption)|\b(?:i|we|they|neighbors?) (?:had )?(?:thought|believed|assumed)|\b(?:round \d+|last round) (?:was|had been)|\b(?:was|were|had been) (?:the )?(?:final|last)[ -]round', re.I)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def code_text(text):
    """Conservative clause-level operational coding; retain ambiguity explicitly.

    Whole generated field is evaluated; prompts/history are never scanned.
    Labels do not use amounts, p, agent type or outcome changes.
    """
    clean=re.sub(r'[*_`]', '', text).replace('\u2019',"'")
    sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])|\n\s*\n',clean)
    positive=[];possible=[];rejected=[];ambiguous=[]
    for s in sentences:
        s=s.strip()
        if not END.search(s):
            if REJECT.search(s):rejected.append(s)
            continue
        if REJECT.search(s):
            # A negative clause may concern defection, rather than the endpoint.
            current=CURRENT.search(s);rejection=REJECT.search(s)
            if current and current.start()<rejection.start():ambiguous.append(s)
            rejected.append(s);continue
        if HISTORY.search(s) and not re.search(r'\bthis (?:is|final|last)|\bcurrent round\b',s,re.I):
            continue
        if not CURRENT.search(s):
            # Historical 'last round' alone is not an ambiguous current endpoint.
            if re.search(r'\bfinal[ -]round\b|\bterminal[ -]round\b',s,re.I):ambiguous.append(s)
            continue
        if POSS.search(s) or UNCERT.search(s):possible.append(s)
        else:positive.append(s)
    if positive and not rejected and not UNCERT.search(' '.join(positive)):
        label='explicit_current';reason='Unretracted explicit current-endpoint statement.'
    elif positive and rejected:
        label='uncertain_or_conflicting';reason='Current assertion and continuation/rejection coexist.'
    elif possible and not rejected and not UNCERT.search(' '.join(possible)) and any(LINK.search(s) and ACTION.search(s) for s in possible):
        label='possible_adopted';reason='Possible current endpoint is explicitly linked to strategy/payoff in the same sentence/paragraph.'
    elif possible or ambiguous:
        label='uncertain_or_conflicting';reason='Endpoint context is uncertain, hypothetical, unlinked, ambiguous or conflicting.'
    else:
        label='no_detected_current';reason='No qualifying current-endpoint statement detected; includes historical/generic/negated references.'
    evidence='\n\n'.join(dict.fromkeys(positive+possible+rejected+ambiguous))
    return dict(operational_label=label,positive=label in POS,evidence=evidence,coding_reason=reason,
                coding_source='automated_rules_v2',reviewer='',review_notes='')

def ensure_cache(input_dir, cache_dir):
    manifest_path=cache_dir/'manifest.json'
    if manifest_path.exists():
        m=json.loads(manifest_path.read_text(encoding='utf-8'))
        if len(m['inputs'])==5 and all(digest(input_dir/x['file'])==x['sha256'] for x in m['inputs']):
            if all((cache_dir/n).exists() for n in ['field_annotations_first_pass.csv','decision_behavior_correspondence.csv']):return m
    # The bundled legacy indexing module reconstructs allocations from raw JSON.
    from . import fig2_screening
    old=sys.argv[:]
    try:
        sys.argv=['fig2_screening','--input',str(input_dir),'--output',str(cache_dir)]
        fig2_screening.main()
    finally:sys.argv=old
    return json.loads(manifest_path.read_text(encoding='utf-8'))

def apply_adjudication(annotations, ad):
    """Apply explicit reviewer overrides; return the changed-field audit log."""
    assert not annotations.columns.duplicated().any()
    assert not ad.duplicated(['decision_id','field']).any()
    overrides=[]
    for _,r in ad.iterrows():
        if not r['reviewed_label']:continue
        assert r.reviewed_label in LABELS and r.reviewer and r.review_notes
        mask=(annotations.decision_id==r.decision_id)&(annotations.field==r.field)
        assert mask.sum()==1
        overrides.append(dict(**r.to_dict(),previous_label=annotations.loc[mask,'operational_label'].iloc[0]))
        annotations.loc[mask,['operational_label','positive','coding_source','reviewer','review_notes']]=[r.reviewed_label,r.reviewed_label in POS,'review_override',r.reviewer,r.review_notes]
    return overrides

def prepare(input_dir, out, cache_dir=None, adjudication=None):
    tests=regression_checks()
    input_dir=Path(input_dir).resolve();out=Path(out).resolve();out.mkdir(exist_ok=True,parents=True)
    cache_dir=Path(cache_dir).resolve() if cache_dir else out/'screening_cache'
    cache_dir.mkdir(exist_ok=True,parents=True)
    cache=ensure_cache(input_dir,cache_dir)
    annotations=pd.read_csv(cache_dir/'field_annotations_first_pass.csv',keep_default_na=False)
    decisions=pd.read_csv(cache_dir/'decision_behavior_correspondence.csv')
    assert len(annotations)==14400 and len(decisions)==7200
    assert not annotations.duplicated(['decision_id','field']).any()
    assert set(decisions.p)==set(PS)
    annotations=annotations.rename(columns={'evidence':'screening_evidence','reviewer':'screening_reviewer','review_notes':'screening_review_notes'})
    coding=pd.DataFrame([code_text(s) for s in annotations.text])
    annotations=pd.concat([annotations,coding],axis=1)
    assert not annotations.columns.duplicated().any()
    overrides=[]
    if adjudication:
        ad=pd.read_csv(adjudication,keep_default_na=False)
        overrides=apply_adjudication(annotations,ad)
    annotations.to_csv(out/'text_coding_all_fields.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(overrides).to_csv(out/'applied_overrides.csv',index=False,encoding='utf-8-sig')
    review=annotations.loc[(annotations.operational_label!='no_detected_current')|(annotations.keyword_candidate==True)].copy()
    review['reviewed_label']=''
    review.to_csv(out/'adjudication_template.csv',index=False,encoding='utf-8-sig')
    for field,prefix in [('BDI','BDI'),('reasoning_content','reasoning')]:
        rows=annotations.loc[annotations.field==field,['decision_id','operational_label','positive','coding_source']].rename(columns={x:prefix+'_'+x for x in ['operational_label','positive','coding_source']})
        decisions=decisions.merge(rows,on='decision_id',validate='one_to_one')
    decisions['BDI_group']=np.where(decisions.BDI_positive,'Judgment',np.where(decisions.BDI_operational_label=='no_detected_current','No detected judgment','Unresolved'))
    decisions.to_csv(out/'decision_data.csv',index=False,encoding='utf-8-sig')
    trajectory=decisions.groupby(['p','role','round']).agg(n=('agent_id','size'),mean_amount=('recorded_amount_total','mean'),
      BDI_count=('BDI_positive','sum'),reasoning_count=('reasoning_positive','sum'),
      unresolved_BDI=('BDI_group',lambda x:sum(x=='Unresolved'))).reset_index()
    trajectory['BDI_fraction']=trajectory.BDI_count/trajectory.n
    trajectory['reasoning_fraction']=trajectory.reasoning_count/trajectory.n
    assert (trajectory.n==36).all()
    trajectory.to_csv(out/'round_summaries.csv',index=False,encoding='utf-8-sig')
    beh=[]
    for p in PS:
        for role in ['as_investor','as_trustee']:
            for t in [10,20]:
                for group in ['No detected judgment','Judgment','Unresolved']:
                    g=decisions[(decisions.p==p)&(decisions.role==role)&(decisions['round']==t)&(decisions.BDI_group==group)]
                    vals=g.delta_amount.dropna();ratios=g.delta_return_ratio.dropna()
                    beh.append(dict(p=p,role=role,round=t,group=group,n=len(g),n_amount=len(vals),n_return_fraction=len(ratios),
                        mean_delta_amount=vals.mean() if len(vals) else np.nan,
                        mean_delta_return_fraction=ratios.mean() if len(ratios) else np.nan,
                        n_amount_decrease=sum(vals < -1e-8),n_ratio_decrease=sum(ratios < -1e-8),
                        mean_received=g.received_tripled_from_recorded_allocations.mean()))
    behavior=pd.DataFrame(beh)
    behavior.to_csv(out/'behavior_summary.csv',index=False,encoding='utf-8-sig')
    counts=annotations.groupby(['field','p','role','operational_label']).size().rename('count').reset_index()
    counts.to_csv(out/'coding_counts.csv',index=False,encoding='utf-8-sig')
    both=decisions.groupby(['p','role','BDI_positive','reasoning_positive']).size().rename('count').reset_index()
    both.to_csv(out/'field_agreement.csv',index=False,encoding='utf-8-sig')
    sensitivity=annotations.groupby(['p','role','round','field','operational_label']).size().unstack(fill_value=0).reindex(columns=LABELS,fill_value=0).reset_index()
    sensitivity['explicit_only']=sensitivity.explicit_current
    sensitivity['primary_operational_count']=sensitivity.explicit_current+sensitivity.possible_adopted
    sensitivity['if_all_unresolved_counted']=sensitivity.primary_operational_count+sensitivity.uncertain_or_conflicting
    sensitivity.to_csv(out/'coding_sensitivity.csv',index=False,encoding='utf-8-sig')
    contrasts=behavior[behavior.group.isin(['Judgment','No detected judgment'])].pivot(index=['p','role','round'],columns='group',values=['mean_delta_amount','mean_delta_return_fraction'])
    contrasts=pd.DataFrame({metric+'_judgment_minus_no_detected':contrasts[(metric,'Judgment')]-contrasts[(metric,'No detected judgment')] for metric in ['mean_delta_amount','mean_delta_return_fraction']}).reset_index()
    contrasts.to_csv(out/'descriptive_group_contrasts.csv',index=False,encoding='utf-8-sig')
    tables=[]
    for i,(role,metric) in enumerate([('as_investor','mean_amount'),('as_trustee','mean_amount'),('as_investor','BDI_fraction'),('as_trustee','BDI_fraction')]):
        columns={'Round':pd.Series(range(1,21))}
        for j,p in enumerate(PS):columns[f'P{j}']=trajectory[(trajectory.p==p)&(trajectory.role==role)].sort_values('round')[metric].reset_index(drop=True)
        tables.append(pd.DataFrame(columns))
    for role,metric in [('as_investor','delta_amount'),('as_trustee','delta_return_ratio')]:
        cols={}
        # Each p has four groups: round10 absent/present, round20 absent/present.
        for j,p in enumerate(PS):
            for k,(t,group) in enumerate([(10,'No detected judgment'),(10,'Judgment'),(20,'No detected judgment'),(20,'Judgment')]):
                g=decisions[(decisions.p==p)&(decisions.role==role)&(decisions['round']==t)&(decisions.BDI_group==group)].sort_values('agent_id')
                v=g[metric].dropna().to_numpy();x=p+[-.075,-.025,.025,.075][k]
                # Deterministic small horizontal offsets only; no change to values.
                offsets=np.linspace(-.012,.012,len(v)) if len(v)>1 else np.zeros(len(v))
                key=f'P{j}G{k}'
                cols[key+'X']=pd.Series(x+offsets);cols[key+'Y']=pd.Series(v)
                cols[key+'MeanX']=pd.Series([x] if len(v) else [],dtype=float)
                cols[key+'MeanY']=pd.Series([float(v.mean())] if len(v) else [],dtype=float)
        cols['ZeroX']=pd.Series([-.13,1.13]);cols['ZeroY']=pd.Series([0.,0.])
        tables.append(pd.DataFrame(cols))
    for i,table in enumerate(tables):table.to_csv(out/f'panel_{chr(97+i)}.csv',index=False,encoding='utf-8-sig')
    plan=dict(status='automated_operational_coding; not independently human-validated',figure='Fig. 2',
      approval='User confirmed six panels, BDI primary, reasoning supplementary, f return-fraction change.',
      sources=cache['inputs'],cache_path=str(cache_dir),cache_sha256={name:digest(cache_dir/name) for name in ['field_annotations_first_pass.csv','decision_behavior_correspondence.csv']},
      primary_field='BDI',supplementary_field='reasoning_content',primary_union=False,rounds=[1,20],agents_per_p=36,
      roles=dict(a='mean total entrusted',b='mean total returned',c='entrusted-stage current-terminal BDI fraction',d='returned-stage current-terminal BDI fraction',e='individual entrusted change',f='individual return-fraction change'),
      definitions=dict(positive=sorted(POS),unresolved='excluded from e/f comparisons; retained in c/d denominator',control='No qualifying current judgment detected by coding, not a validated negative cognition measure',baseline='Individual mean of preceding up-to-three rounds; at rounds10/20 exactly 3',return_fraction='recorded total returned / (3 * sum of neighbors recorded investment to individual); undefined for zero receipts',
      e_f='Rounds 10 and 20, separate within-p judgment groups; small points individual decisions, large markers arithmetic group mean; no independent-session errors or significance tests'),
      colors=dict(zip(map(str,PS),COLORS)),symbols='Round10 circle, Round20 triangle; unfilled no-detected judgment, filled judgment',
      replication='One supplied session per p; network dependence and repeated agents; descriptive only',
      exclusions='No outlier exclusions. Unresolved labels excluded from e/f. Undefined current or baseline return fractions omitted from f only and counted.',
      annotation_counts=annotations.groupby(['field','operational_label']).size().to_dict().__str__(),
      overrides_path=str(adjudication) if adjudication else None,overrides_sha256=digest(adjudication) if adjudication else None,
      table_hashes={f'panel_{chr(97+i)}.csv':digest(out/f'panel_{chr(97+i)}.csv') for i in range(6)},
      source_scripts={x:digest(Path(__file__).with_name(x)) for x in ['fig2_prepare.py','fig2_screening.py']},
      output_project_only=True)
    write_json(out/'analysis_plan.json',plan)
    write_json(out/'data_verification.json',dict(status='passed',decisions=len(decisions),text_fields=len(annotations),
      denominator_check=True,unique_keys=True,source_hash_check=True,classifier_regression_cases=tests,
      independent_human_annotation=False,unresolved_BDI=int(sum(annotations.loc[annotations.field=='BDI','operational_label']=='uncertain_or_conflicting'))))
    write_report(out,trajectory,behavior,annotations)
    print(json.dumps(dict(output=str(out),BDI_positive=int(decisions.BDI_positive.sum()),reasoning_positive=int(decisions.reasoning_positive.sum())),ensure_ascii=False),flush=True)
    return tables,plan

def regression_checks():
    cases=[('In the last round I sent 1.0 and will do so again.','no_detected_current'),
       ('This is the final round. I will return zero.','explicit_current'),
       ('Since this is likely the final round, returning nothing is rational.','possible_adopted'),
       ('This could be the final round, but I do not know. I will maintain trust.','uncertain_or_conflicting'),
       ('There is no indication this is the final round. I will continue.','no_detected_current'),
       ('There is no reason to deviate in this final round.','explicit_current'),
       ('In the final round, I will send zero.','explicit_current'),
       ('The final answer is {1: 0}.','no_detected_current'),
       ('This is the final round. But the game continues.','uncertain_or_conflicting'),
       ('In the previous round I thought this was the final round.','no_detected_current')]
    cases += [('Belief: This is the final round, but I must assume the game might continue.','uncertain_or_conflicting'),
              ('Belief: This final round of the experiment continues the same pattern.','explicit_current')]
    for text,expected in cases:
        actual=code_text(text)['operational_label'];assert actual==expected,(text,actual,expected)
    return len(cases)

def write_report(out,tr,be,ann):
    ranges={}
    for role in ['as_investor','as_trustee']:
        for t in [10,20]:
            v=tr[(tr.role==role)&(tr['round']==t)].BDI_count
            ranges[(role,t)]=f'{int(v.min())}–{int(v.max())}'
    comparisons={}
    for role,metric in [('as_investor','mean_delta_amount'),('as_trustee','mean_delta_return_fraction')]:
        v=be[(be.role==role)&be.group.isin(['Judgment','No detected judgment'])].pivot(index=['p','round'],columns='group',values=metric)
        diff=v['Judgment']-v['No detected judgment']
        comparisons[role]=(int(sum(diff<0)),len(diff),float(diff.min()),float(diff.max()))
    ne,nte,emin,emax=comparisons['as_investor'];nr,ntr,rmin,rmax=comparisons['as_trustee']
    lines=['# Fig. 2 重绘：方法、结果与图注草稿','','**状态：基于可复现自动文本编码的重绘；尚无独立人工逐条验证。图内计数是本报告所定义规则下的操作性指标，不应写成已经完成作者人工标注。**','',
    '## 数据与方法','','五个 p 各一份 JSON，每份36代理×20轮×两阶段，共7200次阶段决策。BDI和reasoning_content各7200条。只分析当轮新生成字段；不重复计入prompt历史。原始分配字典总和构成记录的个人总委托或总返还；没有新版执行修正标志，不能额外推定实际引擎修正。','',
    'BDI为主；reasoning_content单独补充，不使用两者并集。明确当前终局或不存在未来互动的未被撤回表述，编码为explicit_current；明确将当前可能是终局与行动/收益理由联系起来的表述，编码为possible_adopted。这两类合并作为图中的Judgment。历史回顾、一般讨论及明确否定不计。无法消解的假设、冲突和歧义单列uncertain_or_conflicting；未检出合格判断叫No detected judgment，不能声称已验证无终局认知。自动规则在全文运行；边界例与回归检查不能代替独立语义效度验证。','',
    'c、d每个点分子为合格BDI判断数、分母36；未决记录保留在分母中，故属于保守已检出比例，不把未决解释为阴性。e、f只展示10、20轮，未决记录不进入任一组。个人变化=当前值−此前3轮个人均值。f的返还比例=总返还/(当轮邻居发送给该代理的金额总和×3)；当前分母为0不定义，基线取前3轮有效比例的均值，前3轮均无有效值时也不定义。不填0。','',
    '每个p仅一个session，不能将五个条件当重复，也不能把相互作用的代理和重复轮次当独立实验。图不添加推断性p值、独立重复误差线或因果结论。e、f小点为个人决策、大点为组均值，横向位移只用于可读性。','',
    '## 第10、20轮主计数','','|p|委托10|委托20|返还10|返还20|','|---|---:|---:|---:|---:|']
    for p in PS:
        vals=[int(tr[(tr.p==p)&(tr.role==role)&(tr['round']==t)].BDI_count.iloc[0]) for role,t in [('as_investor',10),('as_investor',20),('as_trustee',10),('as_trustee',20)]]
        lines.append('|'+str(p)+'|'+'|'.join(f'{v}/36' for v in vals)+'|')
    lines+=['','## e、f的分组结果','','|p|阶段|轮次|组|n|有效比例变化n|金额变化均值|比例变化均值|','|---|---|---:|---|---:|---:|---:|---:|']
    for _,r in be.iterrows():
        lines.append(f'|{r.p:g}|{r.role}|{r["round"]}|{r.group}|{r.n}|{r.n_return_fraction}|{r.mean_delta_amount:.4f}|{r.mean_delta_return_fraction:.4f}|')
    lines+=['','## 新结果论述草稿（自动编码版本）','',
    f'在五个探索性session中，BDI终局判断主要集中于第10、20轮，但并非只发生在这两轮。按本次保守自动编码，第10轮委托阶段各条件检出{ranges[("as_investor",10)]}/36条，第20轮为{ranges[("as_investor",20)]}/36条；返还阶段分别为{ranges[("as_trustee",10)]}/36和{ranges[("as_trustee",20)]}/36条。应随标签复核重新生成这些范围，不能沿用旧稿的手工计数。','',
    f'将行为与同一代理此前三轮比较后，第10、20轮的p×轮次组合中，检出判断组的返还比例平均变化在{nr}/{ntr}个组合中低于未检出判断组，组间描述性差值范围为{rmin:.3f}至{rmax:.3f}（比例单位）。委托金额变化在{ne}/{nte}个组合中方向相同。组合不是独立重复；各组均值、有效n及例外条件应结合上表报告。','',
    f'These exploratory sessions contained current-terminal statements at rounds 10 and 20 and, less frequently, at other rounds. Under the conservative automated operational coding, detected judgments occurred in {ranges[("as_investor",10)]} of 36 trustor replies at round 10 and {ranges[("as_investor",20)]} at round 20; the corresponding trustee counts were {ranges[("as_trustee",10)]} and {ranges[("as_trustee",20)]}. Relative to each agent\'s preceding-three-round baseline, the detected-judgment group had a lower mean change in returned fraction than the no-detected-judgment group in {nr} of {ntr} condition-by-round comparisons (descriptive differences, {rmin:.3f} to {rmax:.3f}). Entrusted-amount changes followed the same ordering in {ne} of {nte} comparisons. These comparisons are dependent observations from one session per condition and do not establish causation. Labels remain subject to independent semantic validation.','',
    '## English Methods draft','',
    'We reanalysed five exploratory-session JSON records, one for each free-agent proportion (p = 0, 0.25, 0.5, 0.75 and 1), with 36 agents and 20 rounds per session. Generated BDI replies were the primary text source; reasoning_content was analysed separately. A reproducible, conservative automated coding procedure identified unretracted statements that the current round was terminal or that no future interaction remained, together with possible-current-endpoint statements explicitly linked to strategy or payoff reasoning. Historical references, general discussions and negated claims did not qualify. Ambiguous or conflicting statements were retained separately. These operational labels have not undergone independent human validation. Per-round fractions used all 36 replies in the corresponding session and stage as the denominator. Individual behavioural changes at rounds 10 and 20 were calculated relative to the preceding three rounds. The returned fraction was the recorded total returned divided by the tripled investment received in that round; ratios with zero denominators were undefined, and the baseline averaged available ratios from the preceding three rounds. Descriptive summaries were used because only one session was available per condition and agents interacted within a network.','',
    '## English figure legend draft','',
    '**Figure 2 | Temporal co-occurrence of expressed terminal-round judgments and cooperative behaviour in exploratory LLM sessions.** a,b, Population-average recorded total entrusted (a) and returned (b) amounts across 20 rounds. c,d, Fractions of BDI replies meeting the automated operational criteria for a current-terminal judgment in the trustor (c) and trustee (d) stages. Each denominator is 36 agent replies. e,f, Individual changes in total entrusted amount (e) and returned fraction (f) at rounds 10 and 20 relative to the preceding three rounds, grouped by free-agent proportion and detected judgment. Small points denote individual observations and large symbols denote group means. Circles and triangles indicate rounds 10 and 20; filled and open symbols indicate detected and no detected judgments, respectively. Unresolved text labels are excluded from e,f; undefined returned fractions are omitted from f, with group counts provided in source data. Colours indicate p consistently across panels. Each condition contains one recorded session; no independent-repeat uncertainty or inferential significance is shown. Automated text labels require independent semantic validation before being described as manually annotated evidence.','',
    '## 结果解释边界','','终局表述并不必然对应合作减少；应比较每个p、轮次和阶段的实际分组差异。结果最多支持表达的终局判断与行为变化的描述性对应，不能将它解释为终局推断导致了合作下降，也不能把reasoning_content当作内部认知状态的直接观测。旧稿“三次重复”、超过36的单次计数和与本数据不符的个体案例不能沿用。','',
    '## 复核与重现','','text_coding_all_fields.csv保留完整文本、原始JSON路径、行号和自动编码证据。adjudication_template.csv允许填写reviewed_label、reviewer和review_notes；主脚本使用--adjudication导入，并记录每次覆盖的旧标签。不得把空白复核列写成已人工验证。decision_data.csv保留金额、基线和缺失原因相关字段；round_summaries.csv和behavior_summary.csv为绘图前的完整统计。']
    (out/'Fig2_方法结果与图注.md').write_text('\n'.join(lines),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',required=True,type=Path);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--cache',type=Path);ap.add_argument('--adjudication',type=Path)
    a=ap.parse_args();prepare(a.input,a.output,a.cache,a.adjudication)

if __name__=='__main__':main()
