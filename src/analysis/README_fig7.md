# Fig. 7 主脚本

1. 原始三组数据到定向交互统计：项目根目录运行

```powershell
& '.\.venv\Scripts\python.exe' -m src.analysis.fig7_prepare
```

2. 复用已有统计表到可编辑 Origin 项目：

```powershell
& 'C:\Users\Admin\.codex\skills\editaplot-main\runtime\.editaplot-venv\Scripts\python.exe' -m src.analysis.fig7
```

主脚本分别为 `fig7_prepare.py`、`fig7.py`。第二步需要物理 Windows、已安装 Origin 2021+、可调用外部 originpro 的 Python，以及当前交互用户会话。不要在沙箱限制下绕过 Origin 执行身份检查；按工具的精确命令审批流程运行。不附加或修改用户已有 Origin 项目。

输入：`outputs/llm_experiment_datas_summary/agent_rounds_session_1.csv` 至 `_3.csv`，不修改输入。

统计输出：`outputs/llm_experiment_datas_summary/Fig7_interaction_analysis_20261019`。

最终项目：`outputs/llm_experiment_datas_summary/Fig7_complete_Origin_20261019/Fig7_abc_final.opju`。这是仅保留a、b、c的横排三联图。旧`Fig7_final.opju`及`Fig7.opju`均为已被替代的四面板版本；以`origin_readback.json`的`project_path`识别最近一次核验项目。重复运行遇到同名项目时追加时间戳，避免覆盖打开的项目。

图形预览在临时目录，仅用于检查和展示；按照此前约定，不自动导出论文 PDF/EPS。

各条件、各组先汇总前20轮，再在三组实验之间求均值；小点为各组汇总值，大点或柱为三组均值。前三面板连线只作视觉引导。没有误差线、p值或独立连边假设。定向交互按投资方/受托方的顺序编码，返还取逆方向对应执行记录。

颜色表示CC/CF/FC/FF，不再表示p。p由横轴标识；用图例说明该语义变化。采用与Fig4同一组色值中的蓝/橙/青绿/紫红，并用四种形状辅助区分。

当前仅绘制a委托、b对应返还、c返还比。按作者要求删除原d投资差值贡献面板及相关发现；统计缓存中的旧分解列不导入当前项目。

绘图后会保存、重新打开 OPJU，并核对三个原生图层、各绘图数据表、坐标轴范围、字体、图元类型和颜色。`origin_readback.json`记录程序核验，`visual_qa`仅在查看实际 Origin 导出的预览后才能更新为passed。
