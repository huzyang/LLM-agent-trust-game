# 人类实验预处理数据

Fig. 3 和 Fig. 4 共用此目录。主入口：`src/analysis/human_data_cache.py`。

信任博弈人类原始数据：`human_experiment_datas/2024_NHB_model_Trust Game.xlsx`（相对于项目根目录）。Fig. 3、Fig. 4 的 Python 和 PowerShell 入口及 `nhb_analysis.py` 均以此为默认路径；可传入参数指定其他工作簿。

每份工作簿按原始文件 SHA256 和处理代码版本建立独立子目录。原始数据变化或处理规则变化会生成新目录，旧版本保留。每个目录存放完整、清洗过的逐人逐轮记录，以及 `rounds_20`、`rounds_50` 等窗口的表格。

每个窗口提供：

- `selected_round_records.csv`：所选轮次逐人记录。
- `individual_means.csv`、`individual_means_long.csv`：每名参与者在该窗口内的均值。
- `entrusted_individual_wide.csv`、`returned_individual_wide.csv`：箱线图宽表，每列一个 p。
- `session_summary.csv`、`between_session_summary.csv`：场次汇总及场次间差异。
- `round_means.csv`：每个独立场次中 49 人的逐轮均值。
- `round_summary.csv`：场次逐轮均值的平均和样本 SD。
- `entrusted_round_wide.csv`、`returned_round_wide.csv`：均值、SD 和上下界宽表，适合导入 Origin。
- `table_manifest.json`：每张表的哈希、轮次和统计说明。

读取时核验原始工作簿与缓存表的哈希。缺表或损坏时优先从完整清洗记录补算；完整清洗记录损坏时重新读取工作簿。仅在首次或来源改变时解析 Excel；每次读取仍检查原始文件哈希，避免使用过时缓存。已有的来源目录不会被另一份工作簿覆盖。

原始工作簿只读，不复制个人信息页。上列通用 `round_summary.csv` 的逐轮 SD 仍为场次均值之间的样本 SD（ddof=1），不是个体分散程度或均值 CI。缓存不添加拟合、平滑、异常值删除或统计检验；Fig. 3 的 CI 仍由原绘图流程按已确认口径计算。

2026-10-15 确认的新版 Fig. 4 改为逐轮个体金额均值 ±1 SD。`fig4.py` 在对应 `rounds_50` 目录增补 `fig4_individual_round_summary.csv`（147 名参与者的逐轮均值、个体样本 SD 和上下界）及 `fig4_session_round_means.csv`（场次均值审计表）。`fig4_individual_sd_manifest.json` 单独记录清洗记录哈希、统计函数版本及表哈希。首次生成后重复使用；它们与旧的场次间 SD 表分别命名，避免混用。

提前准备默认 20、50 轮数据：

```powershell
python -m src.analysis.human_data_cache --human 'human_experiment_datas/2024_NHB_model_Trust Game.xlsx'
```

其他窗口通过 `--rounds 10 30` 请求；若清洗记录中有这些轮次就自动补齐。不能生成超出原始数据的轮次。路径可用 Python 的 `--human-cache-dir` 或 PowerShell 的 `-HumanCacheDirectory` 覆盖。

文件可以直接导入 Origin 或复制到新图的交付文件夹。两份原始文件若仅路径不同、内容哈希相同，会复用同一缓存。若要在另一台电脑复现，需要原始工作簿以核验来源。

生成的缓存子目录默认不进入 Git；源代码和本说明可以版本管理。数据验证报告见目录根部 `cache_verification.json`。

2026-10-16 新增 Fig. 5 财富缓存：`src/analysis/fig5.py` 在 `trust_game_wealth_<source hash>_<reader hash>` 子目录存放 `all_round_payoffs.csv` 和 `source_manifest.json`。包含15张 TG 实验表的逐人50轮收益、累计收益和实际角色；`player.is_node_player=1` 表示 Constrained，0 表示 Free。只在缓存缺失或源文件/读取规则变更时解析完整实验表；读取时核对源文件和缓存哈希，并验证累计收益等于逐轮收益累加。它不改动 Fig. 3/4 缓存。当前 Fig. 5 只取前20轮；负累计收益按用户确认原值保留。Gini 先按场次和群体计算，再等权汇总场次，不把三场人类实验拼接后计算 Gini。

2026-10-16 新增 Fig. 6 行为表型缓存：`src/analysis/fig6.py` 在 `trust_game_phenotypes_<source hash>_<reader hash>` 子目录保存逐人逐轮、逐方向的委托/收到返还/收到委托金额，`incoming` 统一为乘三倍后的实际收到金额。`rounds_20` 存放六特征实测值、表型分类和另一种缺失填补规则下的分类。`analysis_manifest.json` 绑定原始记录哈希、特征函数、聚类函数与 scikit-learn 版本；命中时不重新计算人类特征与聚类。无观测条件保留 NA 和事件数0；仅聚类输入按用户确认用该个体 A 填补。雷达图只汇总实测条件均值。原始数据和既有缓存保持只读。
