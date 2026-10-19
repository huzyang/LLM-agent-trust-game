"""Prepare directional edge summaries for Fig. 7; no plotting or raw-data edits.

Run from the repository: .venv\\Scripts\\python.exe -m src.analysis.fig7_prepare
CC/CF/FC/FF indicate trustor type then trustee type. Return follows the
opposite direction and is paired with that original entrusted transfer.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path(__file__).resolve().parents[2] / 'outputs' / 'llm_experiment_datas_summary')
    args = parser.parse_args()
    root = args.input.resolve()
    out = root / 'Fig7_interaction_analysis_20261019'
    out.mkdir(exist_ok=True)
    frames, sources = [], []
    for session in range(1, 4):
        path = root / f'agent_rounds_session_{session}.csv'
        df = pd.read_csv(path)
        assert len(df) == 4900
        assert not df.duplicated(['proportion', 'round', 'agent_id']).any()
        lookup = df.set_index(['proportion', 'round', 'agent_id'])
        rows = []
        for r in df.to_dict('records'):
            p, t, i = r['proportion'], r['round'], r['agent_id']
            assert np.isclose(sum(r[f'sent_to_n{k}'] for k in range(1, 5)), r['total_sent'])
            assert np.isclose(3 * sum(r[f'received_send_from_n{k}'] for k in range(1, 5)), r['total_received_send'])
            for k in range(1, 5):
                j = r[f'neighbor_{k}_id']
                target = lookup.loc[(p, t, j)]
                reverse = [h for h in range(1, 5) if target[f'neighbor_{h}_id'] == i]
                assert len(reverse) == 1
                h = reverse[0]
                send, back = r[f'sent_to_n{k}'], r[f'received_return_from_n{k}']
                assert np.isclose(send, target[f'received_send_from_n{h}'])
                assert np.isclose(back, target[f'returned_to_n{h}'])
                source_type, target_type = r['agent_type'], target['agent_type']
                code = ('C' if source_type == 'constrained' else 'F') + ('C' if target_type == 'constrained' else 'F')
                rows.append(dict(session=session, p=p, round=t, trustor_id=i, trustee_id=j,
                    trustor_type=source_type, trustee_type=target_type, interaction=code,
                    undirected_type='CF' if code in ['CF', 'FC'] else code,
                    entrusted=send, returned=back,
                    edge_wealth=2*send, zero_send=send == 0,
                    return_when_zero=back if send == 0 else 0,
                    investor_corrected=r['investor_corrected'], trustee_corrected=target['trustee_corrected']))
        edge = pd.DataFrame(rows)
        assert len(edge) == 19600
        check = edge.groupby('p').agg(entrusted=('entrusted','sum'), returned=('returned','sum'), wealth=('edge_wealth','sum'))
        totals = df.groupby('proportion')[['total_sent','total_returned','round_payoff']].sum()
        assert np.allclose(check.entrusted, totals.total_sent)
        assert np.allclose(check.returned, totals.total_returned)
        assert np.allclose(check.wealth, totals.round_payoff)
        frames.append(edge)
        sources.append(dict(session=session,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    edges = pd.concat(frames, ignore_index=True)

    def aggregate(keys):
        g = edges.groupby(keys, observed=True)
        result = g.agg(n_transfers=('entrusted','size'), entrusted_sum=('entrusted','sum'),
            returned_sum=('returned','sum'), entrusted_mean=('entrusted','mean'),
            returned_mean=('returned','mean'), wealth_sum=('edge_wealth','sum'),
            zero_send_count=('zero_send','sum'), returned_on_zero_send=('return_when_zero','sum')).reset_index()
        # Ratio of sums: includes returns received on zero-send ties; undefined
        # only if the entire group has zero entrusted amount. Not bounded to 1.
        result['return_ratio'] = result.returned_sum / (3 * result.entrusted_sum.replace(0, np.nan))
        return result

    directional = aggregate(['session','p','interaction'])
    undirected = aggregate(['session','p','undirected_type'])
    temporal = aggregate(['session','p','round','interaction'])
    totals = aggregate(['session','p'])
    baseline = totals[totals.p == 0].set_index('session').entrusted_mean
    directional['transfer_weight'] = directional.n_transfers / (196*20)
    directional['baseline_p0_CC_mean'] = directional.session.map(baseline)
    directional['mean_gap_contribution'] = directional.transfer_weight * (directional.entrusted_mean-directional.baseline_p0_CC_mean)
    for (s,p), group in directional.groupby(['session','p']):
        current = totals[(totals.session==s)&(totals.p==p)].iloc[0]
        assert np.isclose(group.mean_gap_contribution.sum(), current.entrusted_mean-baseline[s])
    metrics = ['entrusted_mean','returned_mean','return_ratio','mean_gap_contribution']
    across = directional.groupby(['p','interaction'])[metrics].agg(['mean','std','count']).reset_index()
    across.columns = ['_'.join(filter(None, c)) if isinstance(c,tuple) else c for c in across.columns]
    for name, frame in [('directional_transfers',edges),('session_directional_summary',directional),
                        ('session_three_edge_summary',undirected),('round_directional_summary',temporal),
                        ('session_population_summary',totals),('across_session_summary',across)]:
        frame.to_csv(out/f'{name}.csv',index=False,encoding='utf-8-sig')
    manifest = dict(sources=sources,rows=14700,directed_transfers=len(edges),rounds=[1,20],
        checks=['Unique agent-round keys','Reciprocal neighbor mapping', 'Transfer-to-receipt equality',
                'Return-to-received-return equality','Tripled receipt units','Population wealth = twice total entrusted',
                'Mean gap decomposition sums exactly to population mean gap'],
        inferential_tests='None; three sessions, shared agents and repeated edges are dependent observations.')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# Fig. 7 定向交互初步分析', '',
        'CC、CF、FC、FF的首字母表示投资方，第二字母表示受托方；C=受限，F=自由。返还金额为受托方沿反方向返还给原投资方的执行金额。', '',
        '每组实验分别先对前20轮全部对应定向连边计算均值，再对三组结果汇总均值和样本SD。不存在的交互类型不补零。跨组统计是描述性的，不将连边或轮次作为独立重复。', '',
        '## 平均金额与返还比', '',
        '| p | 类型 | 委托均值（三组均值） | 返还均值（三组均值） | 返还总量/三倍委托总量（三组比值均值） |',
        '|---|---|---:|---:|---:|']
    for r in across.to_dict('records'):
        lines.append(f"| {r['p']} | {r['interaction']} | {r['entrusted_mean_mean']:.4f} | {r['returned_mean_mean']:.4f} | {r['return_ratio_mean']:.4f} |")
    lines += ['', '## 解释与限制', '',
        '返还比是组内总量之比，不是逐笔返还率的算术平均。由于本实验受托方将返还平均分配给邻居，零投资的邻居也可能收到返还；因此该指标不表示资金来源追踪，也不必限制在0–1。零投资返还金额及次数已单列保存。', '',
        '按照当前净收益定义，每条定向投资产生2倍投资额的群体净收益。返还是内部转移，群体求和抵消；财富分解只用于核对会计关系，不能证明返还对后续投资的因果作用。', '',
        'mean_gap_contribution = 该类定向交互权重 ×（该类委托均值 − 同组p=0的CC委托均值）。各类贡献之和等于该条件相对p=0的群体每笔委托均值差。此为描述性分解，p=0基准不是随机干预下的反事实。', '',
        'p=0.25每组仅3条自由—自由无向连边（6条定向连边），解释其均值时需保留三组点及样本范围。三组各条件类型数量相同，不代表网络布局完全独立；应核对种子和布局，不声称三次独立拓扑重复。', '',
        '规则修正可能影响执行金额；directional_transfers.csv保留投资方投资修正标记及受托方返还修正标记。本文汇总描述引擎执行的交互行为。', '',
        '推荐Fig.7先用三面板呈现委托、对应返还及返还比，每条件四类定向交互，以三组实验点及均值展示。需要进一步解释财富时另加委托差值贡献面板。颜色方案、布局与是否纳入人类对照待确认，当前未生成Origin项目。', '',
        '复现：项目根目录运行 `.\\.venv\\Scripts\\python.exe -m src.analysis.fig7_prepare`。重跑覆盖本分析目录内同名分析文件，不修改原始数据。']
    (out/'Fig7_统计口径与初步结果.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(across.to_string(index=False))
    print('OUTPUT',out)


if __name__ == '__main__':
    main()
