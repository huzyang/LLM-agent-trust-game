"""MAIN SCRIPT: immutable llm_base JSON -> reproducible terminal-language screening.

This is a deterministic, conservative rule-assisted FIRST PASS, not validated
human annotation. Review flags and source evidence before publication.
Run: python analyze_llm_base.py [--input DIRECTORY] [--output DIRECTORY]
Only stdlib is required. Never includes prompt history as new generated text.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parent/'Zenodo公开材料'/'experiment_datas'/'llm_base'
ENDPOINT = r'(?:(?:final|last|terminal)[ -](?:round|interaction|turn)|end[ -]?game|no\s+(?:future|further|more)\s+(?:rounds?|interactions?|reciprocity|cooperation|consequences)|(?:game|experiment)\s+(?:ends|is over|is ending)|end of (?:the )?(?:game|experiment))'
CUE = re.compile(ENDPOINT+r'|\bremaining rounds?\b|\bfinal rounds\b|\b(?:near|nearing|towards?|to) the end\b|\bbackward induction\b|终局|最后一轮|最后几轮|临近结束', re.I)
NEGATIVE = re.compile(r'\b(?:not|isn.t|is not|was not|wasn.t)\s+(?:necessarily\s+)?(?:the\s+)?(?:final|last)\s+round|\bno\s+(?:clear\s+|explicit\s+)?(?:indication|evidence|reason).{0,75}(?:final|last)\s+round|\b(?:assume|assuming|since|now|but|and|experiment|game).{0,45}\b(?:continues|continuing|will continue)\b', re.I)
UNCERTAIN = re.compile(r'\b(?:if|might|may|could|possibly|possible|likely|perhaps|probably|assuming|assume|assumption|presumably|seems|appears|potentially|uncertain|unsure)\b|\b(?:not sure|do not know|don.t know|doesn.t specify|not specified|not explicitly|no explicit)\b|\?', re.I)
ASSERT = re.compile(
    r'\b(?:this|current)\s+(?:is|being|round is|round appears to be)\s+(?:indeed\s+|the\s+|a\s+)?(?:final|last|terminal)\s+(?:round|interaction)\b'
    r'|\b(?:this|current)\s+(?:(?:all-important|presumably|likely|possibly)\s+)?final[ -]round\b'
    r'|\b(?:we are|we.re|it is|it.s|we are now)\s+(?:in\s+)?(?:the\s+)?(?:final|last)[ -]round\b'
    r'|\b(?:since|as|because|given)\s+(?:it is\s+|it.s\s+|this is\s+)the\s+(?:final|last)[ -]round\b'
    r'|\bbeing\s+the\s+(?:final|last)[ -]round\b'
    r'|\bgiven\s+the\s+final[ -]round\b'
    r'|\b(?:no|there (?:is|are) no)\s+(?:future|further|more)\s+(?:rounds?|interactions?|reciprocity|cooperation|consequences)\b'
    r'|\b(?:game|experiment)\s+(?:ends after this round|is over|ends now)\b', re.I)
POSSIBLE = re.compile(
    r'\b(?:this(?: round)?|it|current round)\s+(?:is\s+)?(?:may be|might be|could be|possibly|likely|perhaps|probably|seems to be|appears to be)\s+(?:the\s+|a\s+)?(?:final|last)\s+round\b'
    r'|\bround\s*\d+[, ]{0,3}(?:is\s+)?(?:likely|possibly|probably|perhaps|may be|might be|could be)\s+(?:the\s+)?(?:final|last)\s+round\b'
    r'|\b(?:if|assuming)\s+(?:this is|it is|it.s)\s+(?:the\s+)?(?:final|last)\s+round\b',re.I)
GENERAL = re.compile(r'\b(?:previous|prior|last round|round\s*10|round\s*20).{0,60}\b(?:was|were|had|thought|believed|assumed|due to)\b|\b(?:in a|in the|during the)\s+(?:final|last)\s+round\b',re.I)
STRATEGY = re.compile(r'\b(?:send|sending|invest|investment|return|returning|keep|keeping|retain|retaining|defect|reciproc|cooperat|withhold|exploit|reputation|payoff|maximiz|minimiz|incentive|strategic benefit)\w*\b',re.I)
CAUSAL = re.compile(r'\b(?:since|because|therefore|thus|hence|so|given|no incentive|no strategic|no future|no consequence|no need|irrelevant|optimal|rational|maximize|minimize)\b',re.I)
DECREASE = re.compile(r'\b(?:send|sending|return|returning|invest|investing)\s+(?:nothing|zero|0\b|less|as little)|\b(?:reduce|reducing|decrease|defect|withhold|minimiz)\w*\b|\bkeep\s+(?:all|everything)\b',re.I)
MAINTAIN = re.compile(r'\b(?:maintain|continue|sustain|same|stick with|consistent|fairness|reciprocate)\w*\b',re.I)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_csv(path, rows):
    if not rows:
        path.write_text('',encoding='utf-8-sig');return
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def classify(text):
    # Split only at plausible sentence ends; decimals and token allocations
    # remain intact. Preserve complete paragraphs around uncertain language.
    sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z*])|\n\s*\n', text)
    hits=[];assertions=[];possible=[];rejections=[];broad=[]
    for s in sentences:
        if not CUE.search(s):
            # Retractions can occur in a later sentence without repeating the
            # endpoint keyword. Keep them when the same field has endpoint cues.
            if NEGATIVE.search(s) and re.search(r'\b(?:game|experiment)\b.{0,25}\b(?:continues|will continue|continuing)\b|\b(?:assume|assuming)\b.{0,30}\bcontinues\b',s,re.I):
                rejections.append(s)
            continue
        hits.append(s.strip())
        # 'final round payoff' alone can mean final computed round payoff.
        if NEGATIVE.search(s):
            rejections.append(s);continue
        if ASSERT.search(s):
            (possible if UNCERTAIN.search(s) else assertions).append(s)
        elif POSSIBLE.search(s):possible.append(s)
        elif re.search(r'remaining rounds|final rounds|near(?:ing)? the end|end of (?:the )?(?:experiment|game)',s,re.I):broad.append(s)
    if assertions or possible:
        label='asserted_current' if assertions else 'possible_current'
        if rejections:label='mixed_needs_review'
    elif rejections and hits:label='rejected_or_continuing'
    elif broad:label='broad_horizon'
    elif hits:label='other_endpoint_reference_needs_review'
    else:label='none_detected'
    positive=label in ['asserted_current','possible_current']
    evidence='\n\n'.join(hits+[s.strip() for s in rejections if s.strip() not in hits]) if hits else ''
    linked=positive and any(STRATEGY.search(s) and CAUSAL.search(s) for s in assertions+possible)
    direction=''
    if linked:
        s=' '.join(assertions+possible)
        down=bool(DECREASE.search(s));maintain=bool(MAINTAIN.search(s))
        direction='mixed_or_unclear' if down and maintain else 'reduction_candidate' if down else 'maintenance_candidate' if maintain else 'other_or_unclear'
    return dict(label=label,positive_candidate=positive,strategy_link_candidate=linked,
        strategy_direction_candidate=direction,evidence=evidence,keyword_candidate=bool(hits),
        review_required=bool(hits),human_label='',human_strategy_link='',reviewer='',review_notes='')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input',type=Path,default=DEFAULT)
    ap.add_argument('--output',type=Path,default=HERE)
    args=ap.parse_args();root=args.input.resolve();out=args.output.resolve();out.mkdir(exist_ok=True,parents=True)
    records=[];decisions=[];inventory=[];warnings=[]
    files=sorted(root.glob('*.json'))
    for path in files:
        raw=path.read_text(encoding='utf-8-sig');data=json.loads(raw)
        p=float(re.search(r'_p-([0-9.]+)_',path.name).group(1))
        lines=defaultdict(deque)
        for n,line in enumerate(raw.splitlines(),1):
            m=re.match(r'^\s*"(content|reasoning_content|resoning_content)"\s*:',line)
            if m:lines[m.group(1)].append(n)
        present=Counter();labels=Counter();n_decisions=0
        for rnd,agents in data['dialogs'].items():
            t=int(rnd.split('_')[1])
            for agent,roles in agents.items():
                a=int(agent.split('_')[1]);typ=agent.split('_',2)[2]
                for role,obj in roles.items():
                    n_decisions+=1
                    base=dict(file=path.name,p=p,round=t,agent_id=a,agent_type=typ,role=role,
                        decision_id=f'{path.stem}|{rnd}|{agent}|{role}')
                    result={}
                    for field in ['content','reasoning_content','resoning_content']:
                        if field not in obj:continue
                        present[field]+=1;line=lines[field].popleft();text=obj[field] or ''
                        info=classify(text);labels[field+'|'+info['label']]+=1
                        normalized='BDI' if field=='content' else 'reasoning_content'
                        result[normalized]=info
                        records.append(dict(**base,field=normalized,raw_field=field,source_line=line,
                            json_path=f'dialogs.{rnd}.{agent}.{role}.{field}',text_present=bool(text.strip()),
                            **info,text=text))
                    b=result.get('BDI',{});r=result.get('reasoning_content',{})
                    key='agent_invested_amounts' if role=='as_investor' else 'agent_returned_amounts'
                    allocation=data[key][rnd][agent]
                    amount=sum(float(v) for v in allocation.values())
                    prior=[]
                    previous_ratios=[]
                    for k in range(max(1,t-3),t):
                        prev=data[key].get(f'round_{k}',{}).get(agent)
                        if prev is not None:prior.append(sum(float(v) for v in prev.values()))
                        if role=='as_trustee' and prev is not None:
                            incoming=3*sum(float(allocation.get(str(a),0)) for allocation in data['agent_invested_amounts'][f'round_{k}'].values())
                            if incoming>0:previous_ratios.append(sum(float(v) for v in prev.values())/incoming)
                    baseline=mean(prior) if prior else None
                    received=3*sum(float(allocation.get(str(a),0)) for allocation in data['agent_invested_amounts'][rnd].values()) if role=='as_trustee' else None
                    ratio=amount/received if received is not None and received>0 else None
                    baseline_ratio=mean(previous_ratios) if previous_ratios else None
                    bp=b.get('positive_candidate',False);rp=r.get('positive_candidate',False)
                    decisions.append(dict(**base,BDI_label=b.get('label','missing'),reasoning_label=r.get('label','missing'),
                        BDI_positive_candidate=bp,reasoning_positive_candidate=rp,union_positive_candidate=bp or rp,
                        both_positive_candidate=bp and rp,BDI_only=bp and not rp,reasoning_only=rp and not bp,
                        BDI_strategy_link_candidate=b.get('strategy_link_candidate',False),reasoning_strategy_link_candidate=r.get('strategy_link_candidate',False),
                        recorded_amount_total=amount,baseline_previous_up_to_3=baseline,
                        delta_amount=amount-baseline if baseline is not None else None,
                        received_tripled_from_recorded_allocations=received,return_ratio=ratio,
                        baseline_return_ratio=baseline_ratio,
                        delta_return_ratio=ratio-baseline_ratio if ratio is not None and baseline_ratio is not None else None,
                        amount_table=key,execution_correction_status='not available in these JSON records'))
                    if role=='as_investor' and amount>5+1e-8:warnings.append(dict(**base,issue='recorded investment exceeds 5',amount=amount))
                    if role=='as_trustee' and amount>received+1e-8:warnings.append(dict(**base,issue='recorded return exceeds reconstructed receipt',amount=amount))
        assert all(not q for q in lines.values()),'Unmapped source fields'
        inventory.append(dict(file=path.name,path=str(path),sha256=sha(path),p=p,rounds=len(data['dialogs']),
            agents_per_round=sorted(set(len(a) for a in data['dialogs'].values())),decisions=n_decisions,
            field_counts=dict(present),label_counts=dict(labels),initial_prompt_count=len(data['initial_sys_prompt'])))
    assert len(decisions)==7200 and len(records)==14400
    save_csv(out/'field_annotations_first_pass.csv',records)
    save_csv(out/'candidate_review_queue.csv',[r for r in records if r['keyword_candidate']])
    save_csv(out/'decision_behavior_correspondence.csv',decisions)
    save_csv(out/'amount_warnings.csv',warnings)
    label_summary=[]
    for inv in sorted(inventory,key=lambda x:x['p']):
        for role in ['as_investor','as_trustee']:
            for field in ['BDI','reasoning_content']:
                rr=[r for r in records if r['p']==inv['p'] and r['role']==role and r['field']==field]
                counts=Counter(r['label'] for r in rr)
                label_summary.append(dict(p=inv['p'],role=role,field=field,n=len(rr),
                    **{k:counts[k] for k in ['asserted_current','possible_current','mixed_needs_review','broad_horizon','rejected_or_continuing','other_endpoint_reference_needs_review','none_detected']},
                    positive_candidate=sum(r['positive_candidate'] for r in rr),strategy_link_candidate=sum(r['strategy_link_candidate'] for r in rr)))
    save_csv(out/'summary_by_condition_role_field.csv',label_summary)
    frequency=[]
    for p in sorted(x['p'] for x in inventory):
        for role in ['as_investor','as_trustee']:
            for t in range(1,21):
                dd=[d for d in decisions if (d['p'],d['role'],d['round'])==(p,role,t)]
                frequency.append(dict(p=p,role=role,round=t,n_agents=len(dd),
                    **{k:sum(d[k] for d in dd) for k in ['BDI_positive_candidate','reasoning_positive_candidate','union_positive_candidate','both_positive_candidate','BDI_only','reasoning_only','BDI_strategy_link_candidate','reasoning_strategy_link_candidate']}))
    save_csv(out/'Fig2_round_counts_first_pass.csv',frequency)
    save_csv(out/'Fig2_round10_round20_first_pass.csv',[r for r in frequency if r['round'] in [10,20]])
    save_csv(out/'round10_round20_field_review.csv',[r for r in records if r['round'] in [10,20]])
    behavior=[]
    for p in sorted(x['p'] for x in inventory):
        for role in ['as_investor','as_trustee']:
            for t in [10,20]:
                for field in ['BDI','reasoning']:
                    for positive in [True,False]:
                        dd=[d for d in decisions if (d['p'],d['role'],d['round'],d[field+'_positive_candidate'])==(p,role,t,positive)]
                        changes=[d['delta_amount'] for d in dd if d['delta_amount'] is not None]
                        ratio_changes=[d['delta_return_ratio'] for d in dd if d['delta_return_ratio'] is not None]
                        behavior.append(dict(p=p,role=role,round=t,field=field,positive_candidate=positive,n=len(dd),
                            n_amount_decrease=sum(v < -1e-8 for v in changes),
                            mean_delta_amount=mean(changes) if changes else None,
                            n_valid_return_ratio=len(ratio_changes),n_ratio_decrease=sum(v < -1e-8 for v in ratio_changes),
                            mean_delta_return_ratio=mean(ratio_changes) if ratio_changes else None))
    save_csv(out/'round10_round20_behavior_first_pass.csv',behavior)
    means=[]
    for f in frequency:
        dd=[d for d in decisions if (d['p'],d['role'],d['round'])==(f['p'],f['role'],f['round'])]
        means.append(dict(p=f['p'],role=f['role'],round=f['round'],n_agents=len(dd),
            mean_recorded_amount=mean(d['recorded_amount_total'] for d in dd)))
    save_csv(out/'Fig2_amount_trajectories.csv',means)
    manifest=dict(status='first_pass_requires_review',method='Deterministic rules; semantic spot checks by Codex. Not exhaustive independent human annotation.',
        primary_counting_source='BDI',supplementary_counting_source='reasoning_content',primary_uses_field_union=False,
        counting_source_confirmation='User confirmed BDI primary and reasoning_content supplementary in chat.',
        script_sha256=sha(Path(__file__)),inputs=inventory,n_files=len(files),n_decisions=len(decisions),n_text_fields=len(records),
        keyword_candidates=sum(r['keyword_candidate'] for r in records),amount_warning_count=len(warnings),
        counting_unit='One agent x round x role. BDI and reasoning fields separate; union deduplicated at decision level.',
        replication='One provided file per p, 36 agents each, 20 rounds. No independent repeat estimate from this folder.',
        boundary='No causal interpretation; reasoning_content is generated text, not a direct measure of internal cognition. No inferential tests.',
        rules={k:v.pattern for k,v in [('cue',CUE),('negative',NEGATIVE),('asserted',ASSERT),('possible',POSSIBLE),('uncertain',UNCERTAIN),('strategy',STRATEGY),('causal',CAUSAL)]})
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    write_report(out,inventory,records,decisions,frequency,means,warnings)
    print(json.dumps({k:manifest[k] for k in ['n_files','n_decisions','n_text_fields','keyword_candidates','amount_warning_count']}))
    for r in frequency:
        if r['round'] in [10,20]:print(json.dumps(r))


def write_report(out,inventory,records,decisions,frequency,means,warnings):
    lines=['# Fig. 2 终局相关文本统计：llm_base', '',
        '**版本状态：规则辅助初筛，尚未完成逐条人工定稿。以下计数是候选数量，不应直接替换论文中人工判定的强/中终局推断数量。**', '',
        '## 数据范围', '',
        '本次5个JSON分别对应p=0、0.25、0.5、0.75、1，每个文件36代理、20轮、2角色。共7200次阶段决策，7200条BDI回复和7200条reasoning_content，共14400个文本字段。文件内没有resoning_content拼写字段；统计实际reasoning_content。各p只有一个提供的文件，不能据此重建三次独立重复的误差线。', '',
        '只计新生成字段，不把prompt中的历史BDI再次计入；同一代理同一轮的投资和返还分开。字段并集按同一阶段决策去重，不直接相加。初始提示词不用于终局判断计数。', '',
        '## 方法与标签', '',
        '- asserted_current：直接表达当前是终局或不再有未来互动的规则候选。',
        '- possible_current：表达当前可能为终局的规则候选；是否真正采纳这一假设仍需核查。',
        '- mixed_needs_review：同一字段既有肯定/可能表述，也有否定或继续互动表述；暂不计入上述候选阳性。',
        '- rejected_or_continuing：检出否定终局/继续互动表述，不能按关键词作为正向终局判断。',
        '- broad_horizon：剩余轮次、接近结束等宽泛表述。',
        '- other_endpoint_reference_needs_review：历史回顾、一般性终局策略讨论、final-round payoff等待判定表述。',
        '- none_detected：未命中检索规则，不等于经人工验证的阴性。', '',
        '阳性候选 = asserted_current + possible_current。strategy_link_candidate仅表示终局句内同时检出策略和连接理由的词，是待审查标记，不是已证实的因果推理。规则不能替代全段语义判读，尤其不能解决长推理中先假设后否定的所有情况。', '',
        'final answer/final output/最终金额不作为终局关键词；in the last round仅表示上一轮时不作为当前终局。对否定和冲突采取保守处理，但仍可能漏检或误检。', '',
        '所有候选均保存全文、文件名、JSON路径、源文件行号、规则证据和空白人工复核列；没有进行独立人工双标注或一致性估计。', '',
        '## 全20轮分类汇总', '',
        '| p | 字段 | 肯定当前终局候选 | 可能当前终局候选 | 冲突待审 | 宽泛结束 | 否定/继续 | 其他待审 | 未检出 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for inv in sorted(inventory,key=lambda x:x['p']):
        for field in ['BDI','reasoning_content']:
            counts=Counter(r['label'] for r in records if r['p']==inv['p'] and r['field']==field)
            vals=[counts[k] for k in ['asserted_current','possible_current','mixed_needs_review','broad_horizon','rejected_or_continuing','other_endpoint_reference_needs_review','none_detected']]
            lines.append('| '+str(inv['p'])+' | '+field+' | '+' | '.join(map(str,vals))+' |')
    lines += ['', '## 第10轮和第20轮：供Fig.2核查的候选计数', '',
        '每格分母为36名代理。任一字段为两个字段阳性候选的去重并集，不能视为独立测量的相加。', '',
        '| p | 角色 | 轮次 | BDI候选 | reasoning候选 | 两者均有 | 任一字段 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for r in frequency:
        if r['round'] in [10,20]:
            lines.append(f"| {r['p']} | {'投资' if r['role']=='as_investor' else '返还'} | {r['round']} | {r['BDI_positive_candidate']} | {r['reasoning_positive_candidate']} | {r['both_positive_candidate']} | {r['union_positive_candidate']} |")
    lines += ['', '## 个体对应：已核实的原文案例与不一致', '',
        '以下案例由Codex查看完整BDI及相邻金额记录，不代表全体候选已经语义复核。', '',
        '1. p=0.5，agent3_constrained，第10轮返还：BDI明确写“This is the final round (Round 10, stage 2)”及“With no future interactions, there is no strategic incentive to reciprocate”。记录总返还从第9轮6降为第10轮0。该案例可说明终局理由与同一代理返还下降相伴；返还比例及收到投资见逐决策表。',
        '2. p=0，agent5_constrained，第10轮投资：BDI写“Given it\'s the final round”并选择对所有邻居投资0；记录总投资从第9轮5降为0。',
        '3. p=0.5，agent32_constrained，第10轮：BDI认为第10轮为最后一轮，但仍投资5，与第9轮相同。终局判断不必然伴随合作下降。',
        '4. p=0.5，agent6_constrained，第10轮：BDI含“this final round”，但reasoning_content写“There is no indication the game is ending”；投资保持4。两个字段不能当作同一认知状态的等价测量。',
        '5. 当前这份p=0.5文件不支持原回复中“agent6_free和agent32_constrained均从5降为0”的两个案例：agent6在这里为constrained且4→4，agent32为5→5。需要确认旧案例来源；在当前文件范围内更新论述时应替换或移除，不能把不同运行同编号代理当作同一个体。', '',
        '## 金额对应分析的边界', '',
        'decision_behavior_correspondence.csv列出所有7200次决策的两个字段标签、并集、记录金额、前至多3轮均值及变化；返还阶段另列按邻居投资字典重建的三倍收到金额、返还比例和比例变化。round10_round20_behavior_first_pass.csv按规则候选分组给出下降次数和均值差，仅为待复核的描述。非候选组包括冲突和其他待审文本，不能称为已确认的无终局判断对照组。', '',
        '这些JSON未提供现代CSV中的修正/解析失败标记，因此将金额称为“记录表金额”，未声称完整重建原引擎执行及修正过程。金额约束异常数：'+str(len(warnings))+'。不作因果分析，不将代理或重复轮次当独立实验重复计算p值。', '',
        '## Fig.2及结果论述更新建议', '',
        '作者已确认：Fig.2以BDI回复为主要计数来源；reasoning_content单独作为补充。字段并集仅作补充核查，不并入主图。两个字段的一致/不一致情况单独报告。主图仍需以复核后冻结的BDI标签生成，不直接使用当前规则候选数。', '',
        '先对round10_round20_field_review.csv中的1440个字段进行全段复核并冻结标签，同时抽查未命中文本。任何“强/中/弱”对照均需重新定义，不能把本规则分类直接更名为旧人工标签。正式图使用确认后的计数；提供文件每p一次，图注不应写本批计数是三次重复的平均数量。', '',
        '现阶段可以稳妥陈述：在未提供总轮数的探索性实验记录中，部分代理在生成文本中将第10轮或第20轮视为终局；已核实的个体案例既包含投资/返还下降，也包含继续合作及字段间不一致。这些报告提供表达的理由与记录行为的对应证据，但不能作为内部认知状态的直接测量，亦不能独立证明群体下降的因果机制。', '',
        '本次没有修改论文正文、回复信或Origin Fig.2；先核定数据来源、标签和主要计数口径。', '',
        '## 文件与运行', '',
        '- analyze_llm_base.py：主脚本，标准库即可，默认读取相邻Zenodo公开材料中的llm_base。',
        '- field_annotations_first_pass.csv：14400条字段级记录、全文和来源位置。',
        '- candidate_review_queue.csv：检索候选及人工复核空列。',
        '- round10_round20_field_review.csv：优先复核第10/20轮两字段。',
        '- Fig2_round_counts_first_pass.csv：所有20轮逐条件、角色计数及字段并集。',
        '- Fig2_round10_round20_first_pass.csv：原Fig.2重点轮次。',
        '- Fig2_amount_trajectories.csv：20轮记录金额的群体均值。',
        '- summary_by_condition_role_field.csv：字段分类汇总。',
        '- manifest.json：原文件哈希、脚本哈希、规则、样本量与方法限制。', '',
        '运行：`python analyze_llm_base.py`；可用`--input`和`--output`指定路径。重跑更新分析目录内同名结果，不改原JSON。当前脚本不自动吸收人工修改列；人工定稿应另存锁定版本，并据其重新汇总。']
    (out/'Fig2_终局推理统计报告_初筛待复核.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
