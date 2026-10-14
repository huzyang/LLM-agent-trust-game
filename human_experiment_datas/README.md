# 人类实验预处理数据

Fig. 3 和 Fig. 4 共用此目录。主入口：`src/analysis/human_data_cache.py`。

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

原始工作簿只读，不复制个人信息页。均值仍按现有方法计算；逐轮 SD 为独立场次均值之间的样本 SD（ddof=1），不是个体分散程度或均值 CI。缓存不添加拟合、平滑、异常值删除或统计检验；Fig. 3 的 CI 仍由原绘图流程按已确认口径计算。

提前准备默认 20、50 轮数据：

```powershell
python -m src.analysis.human_data_cache --human '人类原始工作簿.xlsx'
```

其他窗口通过 `--rounds 10 30` 请求；若清洗记录中有这些轮次就自动补齐。不能生成超出原始数据的轮次。路径可用 Python 的 `--human-cache-dir` 或 PowerShell 的 `-HumanCacheDirectory` 覆盖。

文件可以直接导入 Origin 或复制到新图的交付文件夹。两份原始文件若仅路径不同、内容哈希相同，会复用同一缓存。若要在另一台电脑复现，需要原始工作簿以核验来源。

生成的缓存子目录默认不进入 Git；源代码和本说明可以版本管理。数据验证报告见目录根部 `cache_verification.json`。
