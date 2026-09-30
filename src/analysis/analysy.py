"""
analysis.py
信任博弈实验数据分析模块
功能：计算核心指标（基尼系数等）、存储绘图数据到Excel、生成论文风格图表
扩展功能：按proportion分组提取列值、绘制抖动散点+箱线图（复刻例图）
"""

# pyright: reportMissingModuleSource=false
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Dict, Optional
import logging
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
logger = logging.getLogger(__name__)

# 设置中文字体（避免图表中文乱码）
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


class TrustGameAnalyzer:
    """
    信任博弈实验分析器
    支持加载多个CSV文件（新格式），计算基尼系数等核心指标，
    存储绘图数据到Excel，并生成论文风格的可视化图表。
    """

    # 论文图表风格设置
    STYLE = {
        "figure.figsize": (10, 6),
        "axes.labelsize": 12,
        "axes.titlesize": 14,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "font.family": "sans-serif",
        "font.sans-serif": ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "axes.grid": True,
        "grid.linestyle": "--",
        "grid.alpha": 0.6,
    }

    def __init__(self, csv_paths: List[str]):
        """
        初始化分析器，加载并合并多个CSV文件
        """
        self.dfs = []
        for path in csv_paths:
            if os.path.exists(path):
                df = pd.read_csv(path)
                self.dfs.append(df)
                logger.info(f"已加载数据: {path}, 行数: {len(df)}")
            else:
                logger.warning(f"文件不存在: {path}")

        if not self.dfs:
            raise ValueError("未加载到任何有效数据文件")

        self.df = pd.concat(self.dfs, ignore_index=True)

        # 确保数值列类型正确
        numeric_cols = ['run_id', 'iteration', 'round', 'num_agents', 'proportion', 'agent_id', 'agent_type',
                        'neighbor_1_id', 'neighbor_2_id', 'neighbor_3_id', 'neighbor_4_id',
                        'sent_to_n1', 'sent_to_n2', 'sent_to_n3', 'sent_to_n4', 'total_sent',
                        'received_return_from_n1', 'received_return_from_n2', 'received_return_from_n3', 'received_return_from_n4', 'total_received_return',
                        'received_send_from_n1', 'received_send_from_n2', 'received_send_from_n3', 'received_send_from_n4', 'total_received_send',
                        'returned_to_n1', 'returned_to_n2', 'returned_to_n3', 'returned_to_n4', 'total_returned',
                        'trustor_payoff', 'trustee_payoff', 'round_payoff', 'accumulate_payoff']  # 'run_id', 'iteration',
        for col in numeric_cols:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce').fillna(0)

        logger.info(f"数据合并完成，总行数: {len(self.df)}，包含比例: {sorted(self.df['proportion'].unique())}")

        # 设置绘图风格
        sns.set_theme(style="whitegrid")
        plt.rcParams.update(self.STYLE)

        # 预计算熔化的单次发送/返还数据（用于例图复刻）
        self.melted_df = self._melt_send_return()

    # ----------------------------------------------------------------------
    # 1. 核心指标计算
    # ----------------------------------------------------------------------
    @staticmethod
    def gini_coefficient(values: np.ndarray) -> float:
        """计算基尼系数（仅非负值）"""
        values = values[values >= 0]
        if len(values) == 0 or np.sum(values) == 0:
            return 0.0
        sorted_vals = np.sort(values)
        n = len(sorted_vals)
        cumsum = np.cumsum(sorted_vals)
        # Gini = (2 * Σ(i * xi)) / (n * Σxi) - (n+1)/n
        gini = (2 * np.sum((np.arange(1, n+1) * sorted_vals)) - (n+1) * np.sum(sorted_vals)) / (n * np.sum(sorted_vals))
        return gini

    def compute_core_metrics(self, proportion: Optional[float] = None) -> Dict:
        """
        计算核心指标，可指定 proportion 筛选
        返回:
            - mean_invested: 平均委托金额 (total_sent / 4)
            - mean_returned: 平均返还金额 (total_returned / 4)
            - total_payoff_sum: 群体总收益（单轮总收益之和，或累加收益）
            - agent_final_payoffs: 每个智能体的最终累计收益（最后一轮的 accumulate_payoff）
            - gini: 基尼系数
            - round_metrics: 按轮次聚合的DataFrame（平均委托、返还、群体总收益）
        """
        df = self.df if proportion is None else self.df[self.df['proportion'] == proportion]
        if len(df) == 0:
            raise ValueError(f"未找到 proportion={proportion} 的数据")

        # 平均委托/返还金额（按交互记录）
        # total_sent 是发送给4个邻居的总和，取平均每次发送
        mean_invested = df['total_sent'].mean()
        # total_returned 是从4个邻居收到的返还总和，取平均每次返还
        mean_returned = df['total_returned'].mean()

        # 群体总收益：所有 agent 在最后一轮的 accumulate_payoff 之和
        # 每个 agent 的最终累计收益（取每个 agent 的最大 round 对应的 accumulate_payoff）
        final_payoffs = df.sort_values('round').groupby('agent_id')['accumulate_payoff'].last()
        total_payoff_sum = final_payoffs.sum()

        # 基尼系数基于最终累计收益
        gini = self.gini_coefficient(final_payoffs.values)

        # 按轮次聚合：平均委托、平均返还、每轮所有 agent 的 round_payoff 之和（群体单轮收益）
        round_metrics = df.groupby('round').agg(
            mean_invested=('total_sent', lambda x: x.mean()),
            mean_returned=('total_returned', lambda x: x.mean()),
            total_payoff=('round_payoff', 'sum')
        ).reset_index()

        return {
            'mean_invested': mean_invested,
            'mean_returned': mean_returned,
            'total_payoff_sum': total_payoff_sum,
            'agent_final_payoffs': final_payoffs,
            'gini': gini,
            'round_metrics': round_metrics,
        }

    def behavior_clustering(self, n_clusters: int = 3) -> pd.DataFrame:
        """
        行为表型聚类：对不同 proportion 分别聚类，得到每个 agent 在各比例下的行为表型
        输出三类：0=prosocial（亲社会）, 1=neutral（中性）, 2=antisocial（反社会）
        分类依据：聚类后按平均委托金额排序，高 -> prosocial(0)，中 -> neutral(1)，低 -> antisocial(2)

        Returns:
            DataFrame: 第一列是 agent_id，其他列是各 proportion 值（0, 0.25, 0.5, 0.75, 1）
                      单元格值为行为表型标签（0/1/2）
        """
        proportions = sorted(self.df['proportion'].unique())
        all_results = []

        for prop in proportions:
            df_prop = self.df[self.df['proportion'] == prop]
            if len(df_prop) == 0:
                logger.warning(f"proportion={prop} 无数据，跳过")
                continue

            # 提取每个 agent 作为投资者的平均行为
            agent_investor = df_prop.groupby('agent_id').agg(
                mean_invested=('total_sent', 'mean')
            ).reset_index()

            if len(agent_investor) < n_clusters:
                logger.warning(f"proportion={prop} 的 agent 数量({len(agent_investor)})少于聚类数({n_clusters})，跳过")
                continue

            # 标准化
            features = agent_investor[['mean_invested']].values
            scaler = StandardScaler()
            features_scaled = scaler.fit_transform(features)

            # K-means 聚类
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(features_scaled)
            agent_investor['cluster'] = labels

            # 根据平均委托金额排序确定标签含义：高->0(prosocial), 中->1(neutral), 低->2(antisocial)
            cluster_order = agent_investor.groupby('cluster')['mean_invested'].mean().sort_values(ascending=False).index.tolist()
            type_map = {cluster_order[i]: i for i in range(len(cluster_order))}

            agent_investor['phenotype'] = agent_investor['cluster'].map(type_map)

            # 只保留 agent_id 和 phenotype，重命名列为 proportion 值
            result_col = agent_investor[['agent_id', 'phenotype']].rename(columns={'phenotype': str(prop)})
            all_results.append(result_col)

            logger.info(f"proportion={prop} 行为聚类完成，各类别计数:\n{agent_investor['phenotype'].value_counts().to_dict()}")

        if not all_results:
            raise ValueError("没有任何 proportion 的数据可用于聚类")

        # 合并所有 proportion 的结果
        merged_df = all_results[0]
        for result in all_results[1:]:
            merged_df = pd.merge(merged_df, result, on='agent_id', how='outer')

        # 确保列顺序：agent_id, 0, 0.25, 0.5, 0.75, 1
        col_order = ['agent_id'] + [str(p) for p in proportions if str(p) in merged_df.columns]
        merged_df = merged_df[col_order]

        logger.info(f"行为聚类完成，共 {len(merged_df)} 个 agent，proportions: {proportions}")
        return merged_df
    # ----------------------------------------------------------------------
    # 2. 新增：按 proportion 分组提取列值
    # ----------------------------------------------------------------------
    def get_grouped_values_for_column(self, column_name: str) -> pd.DataFrame:
        """
        将指定列按 proportion 分组，返回各组所有值的垂直对齐 DataFrame。
        每列是一个 proportion，每行是该 proportion 下的一个原始值，
        不同组的行数可能不同，用 NaN 填充至最大行数。
        """
        groups = []
        proportions = sorted(self.df['proportion'].unique())
        for prop in proportions:
            values = self.df[self.df['proportion'] == prop][column_name].dropna().values
            groups.append(pd.Series(values, name=prop))
        # 按最大长度对齐
        max_len = max(len(g) for g in groups) if groups else 0
        aligned = []
        for g in groups:
            if len(g) < max_len:
                g = g.reindex(range(max_len))
            aligned.append(g)
        result = pd.concat(aligned, axis=1)
        # 列名保持为原始比例值
        return result

    # ----------------------------------------------------------------------
    # 3. 新增：绘制抖动散点 + 箱线图（无异常值）
    # ----------------------------------------------------------------------
    def plot_jitter_boxplot_for_column(self, column_name: str, output_path: str,
                                       jitter_strength: float = 0.02):
        """
        对指定列（数值型）按 proportion 分组，绘制抖动散点 + 箱线图（关闭异常值点）。
        横轴：proportion
        纵轴：column_name 的值
        散点添加横向 jitter 避免重叠。
        """
        df_plot = self.df[['proportion', column_name]].dropna()
        proportions = sorted(df_plot['proportion'].unique())
        plt.figure(figsize=(8, 6))

        # 准备箱线图数据
        box_data = [df_plot[df_plot['proportion'] == p][column_name].values for p in proportions]

        # 绘制箱线图（无异常值点）
        bp = plt.boxplot(box_data, positions=proportions, widths=0.15,
                         patch_artist=True, showfliers=False,
                         boxprops=dict(facecolor='lightblue', alpha=0.7),
                         medianprops=dict(color='red', linewidth=2),
                         whiskerprops=dict(color='black'),
                         capprops=dict(color='black'))

        # 添加抖动散点
        np.random.seed(42)  # 可重现的 jitter
        for p in proportions:
            vals = df_plot[df_plot['proportion'] == p][column_name].values
            jitter = np.random.uniform(-jitter_strength, jitter_strength, size=len(vals))
            x = p + jitter
            plt.scatter(x, vals, s=15, alpha=0.5, c='dimgray', edgecolors='none')

        plt.xlabel('Fraction of free players')
        plt.ylabel(column_name)
        plt.xticks(proportions, [f'{p:.2f}' for p in proportions])
        plt.grid(axis='y', linestyle='--', alpha=0.4)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()
        logger.info(f"已保存抖动箱线图: {output_path}")

    # ----------------------------------------------------------------------
    # 4. 熔化为单次发送/返还金额（用于复刻题图）
    # ----------------------------------------------------------------------
    def _melt_send_return(self) -> pd.DataFrame:
        """
        将 sent_to_n1~sent_to_n4 和 returned_to_n1~returned_to_n4 转换为长格式，
        每条记录代表一次单边交互（发送或返还）。
        返回 DataFrame 包含列：proportion, amount, type ('sent' or 'returned')
        """
        # 发送部分
        sent_cols = ['sent_to_n1', 'sent_to_n2', 'sent_to_n3', 'sent_to_n4']
        sent_long = pd.melt(self.df, id_vars=['proportion'], value_vars=sent_cols,
                            var_name='neighbor', value_name='amount')
        sent_long['type'] = 'sent'
        # 返还部分
        returned_cols = ['returned_to_n1', 'returned_to_n2', 'returned_to_n3', 'returned_to_n4']
        ret_long = pd.melt(self.df, id_vars=['proportion'], value_vars=returned_cols,
                           var_name='neighbor', value_name='amount')
        ret_long['type'] = 'returned'
        # 合并
        melted = pd.concat([sent_long, ret_long], ignore_index=True)
        # 删除缺失值
        melted = melted.dropna(subset=['amount'])
        return melted

    def plot_jitter_boxplot_from_melted(self, amount_type: str, output_path: str,
                                        jitter_strength: float = 0.02):
        """
        使用熔化的单次交互数据绘制抖动散点+箱线图。
        amount_type: 'sent' 或 'returned'
        """
        df_plot = self.melted_df[self.melted_df['type'] == amount_type]
        if df_plot.empty:
            logger.warning(f"没有找到类型为 {amount_type} 的数据")
            return
        proportions = sorted(df_plot['proportion'].unique())
        plt.figure(figsize=(8, 6))

        box_data = [df_plot[df_plot['proportion'] == p]['amount'].values for p in proportions]

        bp = plt.boxplot(box_data, positions=proportions, widths=0.15,
                         patch_artist=True, showfliers=False,
                         boxprops=dict(facecolor='lightblue', alpha=0.7),
                         medianprops=dict(color='red', linewidth=2),
                         whiskerprops=dict(color='black'),
                         capprops=dict(color='black'))

        np.random.seed(42)
        for p in proportions:
            vals = df_plot[df_plot['proportion'] == p]['amount'].values
            jitter = np.random.uniform(-jitter_strength, jitter_strength, size=len(vals))
            x = p + jitter
            plt.scatter(x, vals, s=15, alpha=0.5, c='dimgray', edgecolors='none')

        ylabel = 'Sent amount' if amount_type == 'sent' else 'Returned amount'
        plt.xlabel('Fraction of free players')
        plt.ylabel(ylabel)
        plt.xticks(proportions, [f'{p:.2f}' for p in proportions])
        plt.grid(axis='y', linestyle='--', alpha=0.4)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()
        logger.info(f"已保存 {amount_type} 抖动箱线图: {output_path}")

    # ----------------------------------------------------------------------
    # 5. 导出 Excel（原有功能 + 新增分组工作表）
    # ----------------------------------------------------------------------
    def export_plot_data_to_excel(self, output_excel_path: str):
        """
        将绘图所需的核心数据存储到 Excel 的一个工作簿中。
        新增：对 total_sent 和 total_returned 生成分组工作表（grouped_*）
        """
        proportions = sorted(self.df['proportion'].unique())
        summary_data = []
        round_invested_pivot = None
        round_returned_pivot = None
        round_payoff_pivot = None
        gini_list = []

        for prop in proportions:
            metrics = self.compute_core_metrics(proportion=prop)
            summary_data.append({
                'proportion': prop,
                'mean_invested': metrics['mean_invested'],
                'mean_returned': metrics['mean_returned'],
                'total_payoff_sum': metrics['total_payoff_sum'],
                'gini': metrics['gini']
            })
            gini_list.append({'proportion': prop, 'gini': metrics['gini']})

            # 构建轮次透视表
            round_df = metrics['round_metrics']
            round_df['proportion'] = prop
            # 合并各比例的轮次数据
            if round_invested_pivot is None:
                round_invested_pivot = round_df[['round', 'proportion', 'mean_invested']]
                round_returned_pivot = round_df[['round', 'proportion', 'mean_returned']]
                round_payoff_pivot = round_df[['round', 'proportion', 'total_payoff']]
            else:
                round_invested_pivot = pd.concat([round_invested_pivot, round_df[['round', 'proportion', 'mean_invested']]])
                round_returned_pivot = pd.concat([round_returned_pivot, round_df[['round', 'proportion', 'mean_returned']]])
                round_payoff_pivot = pd.concat([round_payoff_pivot, round_df[['round', 'proportion', 'total_payoff']]])

        # 透视表：行=round，列=proportion，值=指标
        if round_invested_pivot is not None:
            round_invested_table = round_invested_pivot.pivot(index='round', columns='proportion', values='mean_invested')
            round_returned_table = round_returned_pivot.pivot(index='round', columns='proportion', values='mean_returned')
            round_payoff_table = round_payoff_pivot.pivot(index='round', columns='proportion', values='total_payoff')
            # 重命名列
            round_invested_table.columns = [f'{c}' for c in round_invested_table.columns]
            round_returned_table.columns = [f'{c}' for c in round_returned_table.columns]
            round_payoff_table.columns = [f'{c}' for c in round_payoff_table.columns]
            round_invested_table.reset_index(inplace=True)
            round_returned_table.reset_index(inplace=True)
            round_payoff_table.reset_index(inplace=True)

        summary_df = pd.DataFrame(summary_data)
        gini_df = pd.DataFrame(gini_list)

        # 获取分组数据（total_sent 和 total_returned）
        grouped_sent = self.get_grouped_values_for_column('total_sent')
        grouped_returned = self.get_grouped_values_for_column('total_returned')

        # 执行行为聚类（默认3类）
        try:
            clustering_result = self.behavior_clustering(n_clusters=3)
            has_clustering = True
        except Exception as e:
            logger.warning(f"行为聚类失败: {e}")
            has_clustering = False

        with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
            summary_df.to_excel(writer, sheet_name='summary', index=False)
            if round_invested_table is not None:
                round_invested_table.to_excel(writer, sheet_name='round_mean_invested', index=False)
                round_returned_table.to_excel(writer, sheet_name='round_mean_returned', index=False)
                round_payoff_table.to_excel(writer, sheet_name='round_total_payoff', index=False)
            gini_df.to_excel(writer, sheet_name='gini_by_proportion', index=False)
            # 新增分组数据工作表
            grouped_sent.to_excel(writer, sheet_name='grouped_total_sent', index=False)
            grouped_returned.to_excel(writer, sheet_name='grouped_total_returned', index=False)
            # 新增行为聚类结果工作表
            if has_clustering:
                clustering_result.to_excel(writer, sheet_name='behavior_clustering', index=False)

        logger.info(f"绘图数据已导出至: {output_excel_path}")
        return output_excel_path

    def plot_figures(self, output_dir: str):
        """
        生成论文同款图表：
        - 图1: 委托金额随轮次变化（不同比例对比）
        - 图2: 返还金额随轮次变化
        - 图3: 基尼系数条形图
        - 图4: 个人最终累计收益分布箱线图
        """
        proportions = sorted(self.df['proportion'].unique())
        os.makedirs(output_dir, exist_ok=True)

        colors = sns.color_palette("Blues_d", n_colors=len(proportions))
        prop_labels = [f"{int(p*100)}%" for p in proportions]

        # 图1：委托金额演化
        plt.figure(figsize=(10, 6))
        for i, prop in enumerate(proportions):
            metrics = self.compute_core_metrics(proportion=prop)
            round_df = metrics['round_metrics']
            plt.plot(round_df['round'], round_df['mean_invested'],
                     marker='o', markersize=4, linewidth=1.5,
                     color=colors[i], label=f"自由{prop_labels[i]}")
        plt.xlabel("轮次")
        plt.ylabel("平均委托金额")
        plt.title("不同自由玩家比例下的平均委托金额演化")
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "invested_over_rounds.png"), dpi=150)
        plt.close()

        # 图2：返还金额演化
        plt.figure(figsize=(10, 6))
        for i, prop in enumerate(proportions):
            metrics = self.compute_core_metrics(proportion=prop)
            round_df = metrics['round_metrics']
            plt.plot(round_df['round'], round_df['mean_returned'],
                     marker='s', markersize=4, linewidth=1.5,
                     color=colors[i], label=f"自由{prop_labels[i]}")
        plt.xlabel("轮次")
        plt.ylabel("平均返还金额")
        plt.title("不同自由玩家比例下的平均返还金额演化")
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "returned_over_rounds.png"), dpi=150)
        plt.close()

        # 图3：基尼系数条形图
        ginis = [self.compute_core_metrics(proportion=prop)['gini'] for prop in proportions]
        plt.figure(figsize=(8, 5))
        bars = plt.bar(prop_labels, ginis, color=colors, edgecolor='black')
        plt.xlabel("自由玩家比例")
        plt.ylabel("基尼系数")
        plt.title("不同自由玩家比例下的财富不平等程度")
        y_max = max(ginis) * 1.2 if max(ginis) > 0 else 0.6
        plt.ylim(0, y_max)
        for bar, g in zip(bars, ginis):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                     f'{g:.3f}', ha='center', va='bottom', fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "gini_coefficient.png"), dpi=150)
        plt.close()

        # 图4：个人累计收益箱线图
        data_to_plot = [self.compute_core_metrics(proportion=prop)['agent_final_payoffs'].values for prop in proportions]
        plt.figure(figsize=(10, 6))
        plt.boxplot(data_to_plot, tick_labels=prop_labels, showmeans=True, meanline=True)
        plt.xlabel("自由玩家比例")
        plt.ylabel("个人累计收益")
        plt.title("不同自由玩家比例下的个人收益分布")
        plt.grid(axis='y', linestyle='--', alpha=0.6)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "personal_payoff_boxplot.png"), dpi=150)
        plt.close()

        logger.info(f"所有论文风格图表已保存至: {output_dir}")

# ----------------------------------------------------------------------
# 命令行使用示例
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import glob
    from src.utils import CommonUtils   # 请确保项目中有 CommonUtils，或直接指定路径

    # 数据目录（可根据实际情况修改）
    csv_dir = os.path.join(
        CommonUtils.get_project_root_path(),
        "outputs",
        "20260529_105859_deepseek-v4-flash_no_total_round-avg"
    )

    file_name = "averaged_3_runs_p-[0, 0.25, 0.5, 0.75, 1].csv"
    file_path = os.path.join(csv_dir, file_name)

    if not os.path.exists(file_path):
        # 尝试从当前目录查找
        if os.path.exists(file_name):
            file_path = file_name
        else:
            print(f"文件不存在: {file_path}")
            exit(1)

    analyzer = TrustGameAnalyzer([file_path])

    # 1. 导出 Excel（包含分组数据）
    analyzer.export_plot_data_to_excel(os.path.join(csv_dir, "averaged_3_runs_plot_data.xlsx"))

    # 2. 生成复刻例图的抖动散点+箱线图（基于单次发送/返还金额）
    fig_dir = os.path.join(csv_dir, "figures")
    if not os.path.exists(fig_dir):
        os.makedirs(fig_dir, exist_ok=True)
    analyzer.plot_jitter_boxplot_from_melted('sent', os.path.join(fig_dir, "sent_amount_plot.png"))
    analyzer.plot_jitter_boxplot_from_melted('returned', os.path.join(fig_dir, "returned_amount_plot.png"))

    # 3. 可选：直接对 total_sent 列生成抖动箱线图（作为补充）
    analyzer.plot_jitter_boxplot_for_column('total_sent', os.path.join(fig_dir, "total_sent_jitter.png"))
    analyzer.plot_jitter_boxplot_for_column('total_returned', os.path.join(fig_dir, "total_returned_jitter.png"))

    # 4. 生成原有的论文风格图表（轮次演化、基尼系数等）
    analyzer.plot_figures(fig_dir)

    print("所有分析和绘图完成！")