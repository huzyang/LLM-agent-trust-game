"""Reproduce this batch's keyword-assisted, AI-reviewed terminal-language audit.

Run with the project's Python; inputs are read-only. Fixed semantic decisions below
are annotations, not a general classifier or independent human validation.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean

ANNOTATIONS = {
    (1, 3, 20, 'as_trustee'): 'remaining',
    (1, 15, 10, 'as_trustee'): 'remaining',
    (1, 16, 10, 'as_trustee'): 'remaining',
    (1, 17, 10, 'as_trustee'): 'ending',
    (1, 18, 10, 'as_trustee'): 'ending',
    (1, 20, 10, 'as_trustee'): 'ending',
    (2, 19, 12, 'as_investor'): 'remaining',
    (2, 20, 12, 'as_investor'): 'remaining',
    (3, 7, 6, 'as_investor'): 'ending',
    (3, 18, 37, 'as_investor'): 'ending',
    (3, 19, 37, 'as_investor'): 'remaining',
    (4, 5, 11, 'as_trustee'): 'remaining',
    (4, 8, 11, 'as_trustee'): 'remaining',
    (4, 9, 11, 'as_trustee'): 'ending',
    (5, 6, 36, 'as_trustee'): 'remaining',
}
PATTERNS = [
    r'\b(?:final|terminal|endgame|end-game|penultimate|finite|horizon|remaining)\b',
    r'\b(?:end|ends|ending|ended|finish|finished|conclude|concludes|concluding)\b',
    r'\blast\b',
    r'\b(?:no|without|little|limited|less|fewer|unlikely|not|never|won.t)\b.{0,65}\b(?:future|subsequent|again|rounds|retaliation|reputation)\b',
    r'\b(?:20|twenty)[- ]round\b|\bround\s*20\b|\btwenty\b',
    r'\bbackward\s+induction\b',
    r'终局|末轮|最终轮|最后一轮|倒数|剩余.{0,10}轮|即将结束|临近结束|有限轮|向后归纳',
]


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parents[2] / 'outputs' / '20261018_145435_396008_llm'
    parser.add_argument('--input', type=Path, default=default)
    args = parser.parse_args()
    root = args.input.resolve()
    out = root / 'terminal_bdi_audit_20261018'
    out.mkdir(exist_ok=True)
    regex = re.compile('|'.join(PATTERNS), re.I)
    with (root / 'agent_rounds.csv').open(encoding='utf-8-sig', newline='') as f:
        amounts = list(csv.DictReader(f))
    by_key = {(int(r['run_id']), int(r['round']), int(r['agent_id'])): r for r in amounts}
    assert len(by_key) == len(amounts) == 4900
    records, inventory = [], []
    prohibition = 'you do not know the total number of rounds in this experiment, and you must not assume that any given round is the final round.'
    for file in sorted(root.rglob('dialogue.json')):
        run = int(re.search(r'run_(\d+)', file.parent.name).group(1))
        text = file.read_text(encoding='utf-8')
        data = json.loads(text)
        lines = iter(i for i, l in enumerate(text.splitlines(), 1) if re.match(r'^\s*"content"\s*:', l))
        prompts = list(data['initial_sys_prompt'].values())
        for rnd, agents in data['dialogs'].items():
            t = int(rnd.split('_')[1])
            for agent, roles in agents.items():
                a = int(agent.split('_')[1])
                for role, obj in roles.items():
                    line = next(lines)
                    content = obj['content']
                    key = (run, t, a, role)
                    row = by_key[run, t, a]
                    label = ANNOTATIONS.get(key, 'none_detected')
                    assert row['agent_type'] == agent.split('_', 2)[2]
                    field = 'total_sent' if role == 'as_investor' else 'total_returned'
                    value = float(row[field])
                    history = [by_key[run, k, a] for k in range(max(1, t-3), t)]
                    baseline = mean(float(h[field]) for h in history) if history else None
                    received = float(row['total_received_send'])
                    ratio = value / received if role == 'as_trustee' and received > 0 else None
                    ratios = [float(h['total_returned'])/float(h['total_received_send']) for h in history if float(h['total_received_send']) > 0]
                    ratio_base = mean(ratios) if role == 'as_trustee' and ratios else None
                    delta = value-baseline if baseline is not None else None
                    dr = ratio-ratio_base if ratio is not None and ratio_base is not None else None
                    if label != 'none_detected':
                        evidence = next(l.strip() for l in content.splitlines() if re.search(r'remaining rounds|final rounds|to the end|near the end|before the experiment ends', l, re.I))
                    else:
                        evidence = ''
                    records.append(dict(run_id=run, p=row['proportion'], round=t, agent_id=a,
                        agent_type=row['agent_type'], role=role, keyword_candidate=bool(regex.search(content)),
                        annotation=label, current_round_terminal_judgment=False,
                        terminal_driven_strategy=False, expressed_action=('retain_more_balance_trust' if run == 4 and a == 11 else 'maintain_cooperation') if evidence else '',
                        evidence=evidence, actual_amount=value, baseline_previous_up_to_3=baseline,
                        delta_amount=delta, received_tripled=received if role == 'as_trustee' else None,
                        return_fraction=ratio, baseline_return_fraction=ratio_base, delta_return_fraction=dr,
                        corrected=row['investor_corrected' if role == 'as_investor' else 'trustee_corrected'],
                        parse_failed=row['investor_parse_failed' if role == 'as_investor' else 'trustee_parse_failed'],
                        source_file=str(file), source_line=line, content=content))
                    prompts.append(obj.get('prompt', ''))
        assert next(lines, None) is None
        inventory.append(dict(file=str(file), sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            messages=sum(r['run_id'] == run for r in records),
            prompts_with_exact_prohibition=sum(prohibition in p.lower() for p in prompts)))
    assert len(records) == 9800
    positives = [r for r in records if r['annotation'] != 'none_detected']
    assert len(positives) == len(ANNOTATIONS) == 15
    write_csv(out / 'all_reports.csv', records)
    write_csv(out / 'positive_evidence_and_behavior.csv', positives)
    write_csv(out / 'keyword_candidates.csv', [r for r in records if r['keyword_candidate']])
    summary = []
    for run in range(1, 6):
        for role in ['as_investor', 'as_trustee']:
            group = [r for r in records if r['run_id'] == run and r['role'] == role]
            found = [r for r in group if r['annotation'] != 'none_detected']
            summary.append(dict(run_id=run, p=group[0]['p'], role=role, reports=len(group),
                remaining=sum(r['annotation']=='remaining' for r in found),
                ending=sum(r['annotation']=='ending' for r in found), current_round_terminal=0,
                broad_rate=len(found)/len(group), agents_ever=len({r['agent_id'] for r in found}), agents=49))
    write_csv(out / 'summary_by_condition_role.csv', summary)
    time_rows = []
    for run in range(1, 6):
        for role in ['as_investor', 'as_trustee']:
            for t in range(1, 21):
                group = [r for r in records if (r['run_id'],r['role'],r['round'])==(run,role,t)]
                time_rows.append(dict(run_id=run,p=group[0]['p'],role=role,round=t,reports=len(group),
                    remaining=sum(r['annotation']=='remaining' for r in group),
                    ending=sum(r['annotation']=='ending' for r in group),current_round_terminal=0))
    write_csv(out / 'frequency_by_round.csv', time_rows)
    manifest = dict(input_root=str(root), inventory=inventory,
        csv_sha256=hashlib.sha256((root/'agent_rounds.csv').read_bytes()).hexdigest(),
        reports=len(records), candidate_reports=sum(r['keyword_candidate'] for r in records),
        counts=dict(Counter(r['annotation'] for r in records)),
        agents_ever=len({(r['run_id'],r['agent_id']) for r in positives}),
        annotation_method='Keyword-assisted semantic assessment by Codex; fixed decisions in source. No independent human annotation or inter-rater agreement. Non-candidates were not exhaustively manually reviewed.',
        patterns=PATTERNS, config=json.loads((root/'config.json').read_text(encoding='utf-8')))
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    report = '''# 终局相关 BDI 核查：20261018_145435_396008_llm

本批未告知总轮数，且没有加入禁止终局假设指令。五个 run 对应五个 p 条件，每条件一次实验；不能视为五次同条件独立重复，也不能用于估计禁止指令的效果。

## 结果

- 5 个 dialogue.json，20 轮×49代理×2角色×5条件，共9,800条生成报告。
- 宽口径相关表述15条（0.1531%），涉及7/245个条件内代理（2.8571%）。
- 其中“剩余轮次”9条（0.0918%），明确提及结束/最后几轮6条（0.0612%）。两类互斥；剩余轮次并不表示认为终局将至。
- 投资阶段5/4,900条，返还阶段10/4,900条。具体条件分布见 summary_by_condition_role.csv。
- 未检出明确认为当前轮可能/确定为最后一轮、此后不再互动，或据此调整策略的报告。这是本次筛查结果，不能证明绝对不存在。
- 第7轮出现“near the end of the experiment”，不能理解为模型准确知道第20轮结束；第20轮仍有“remaining rounds”。

## 行为对应与解释

严格终局判断未检出，因此不能在本批估计“终局判断组 vs 非终局判断组”的合作下降差异；相关比例为不适用，不应写成0%下降。

positive_evidence_and_behavior.csv列出15条宽口径表述及同一代理实际执行金额、前至多3轮基准、金额变化、返还比例变化、解析失败及规则修正标志。此表是补充描述，不能把泛化措辞作为严格终局判断的替代。

投资使用total_sent；返还使用total_returned，比例分母为total_received_send（已经三倍化，不再次乘3）；分母为0时记缺失。基准仅用前1—3轮，不含当前轮；返还比例基准取其中有效比例的均值。金额来自CSV执行记录，不直接采信BDI文字或字典。比较零变化时应允许数值容差。

表述多数主张维持合作；run004 agent11描述增加保留收益、平衡信任，但没有明确用“未来互动消失”解释策略。不能将其归为终局驱动的背叛。

6条ending表述中，5条当轮金额相对前3轮均值不变，另1条为run004第9轮agent11：执行返还28.20，高于基准约27.5867；返还比例1.0000，高于基准约0.999513。这6条没有观察到当轮合作下降；此为小量宽泛表述的描述，不是严格终局判断的检验。

特别注意：run004 agent11的3条阳性记录均有trustee_corrected=True。其文字意图与执行金额不完全一致。第9轮文字称返还22.6、每邻居5.65，但金额字典对四邻居均写22.6；实际执行总返还28.2。因此不能把执行结果当作未受约束的模型意图。15条宽口径记录中3条有规则修正，未发现解析失败；金额描述必须连同这些标志解释。

## 方法、局限与复现

只检索每个阶段新生成的content；不把阶段prompt中的历史内容重复计入。关键词/短语筛选后由Codex语义核查，标注决定固定在源码中；这是AI辅助初步审计，尚无独立人工复核及一致性评估。未命中文本未全部逐条人工核查，因而“未检出”不等同于真实发生率为零。正式发表前应人工复核候选并抽查未命中文本，冻结最终标签后重新汇总。

排除：last round表示上一轮、剩余资金、普通未来互惠、结束当前阶段或轮次、历史累计20轮、输出格式中的at last，以及否定终局判断的表达。标签remaining指泛称剩余轮次；ending指实验结束/最后几轮；均不计为当前轮终局判断。

9,800条是报告数量，245是条件内代理数量，均不是独立实验重复数。不做将轮次或代理当独立重复的显著性检验，不作因果推断。检索规则、源文件哈希与提示词精确句匹配结果见manifest.json。

主脚本：src/analysis/terminal_bdi_20261018.py。项目根目录运行：

```powershell
& '.\\.venv\\Scripts\\python.exe' -m src.analysis.terminal_bdi_20261018
```

输出写入本批目录下terminal_bdi_audit_20261018；重跑更新该分析目录，不修改原始数据。
'''
    (out/'终局相关BDI_核查报告.md').write_text(report,encoding='utf-8')
    print(json.dumps({k:manifest[k] for k in ['reports','candidate_reports','counts','agents_ever']},ensure_ascii=True))
    print(str(out))


if __name__ == '__main__':
    main()
