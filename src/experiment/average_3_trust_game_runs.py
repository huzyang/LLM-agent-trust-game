"""
计算 3 次独立重复博弈实验结果的逐行平均。

使用方法：
1. 把本脚本放到包含 3 个 csv 文件的文件夹中；
   或者修改下面的 INPUT_DIR 为你的文件夹路径。
2. 运行：python average_3_trust_game_runs.py
3. 输出文件默认为：averaged_3_runs.csv
"""
import os
from pathlib import Path
import pandas as pd

# ========== 1. 修改这里：输入文件夹路径 ==========
# 例：Windows 路径可写成 r"D:\your\folder\20260529_105859_deepseek-v4-flash_no_total_round-avg"
from src.utils import CommonUtils  # 请确保项目中有 CommonUtils，或直接指定路径

INPUT_DIR = Path(CommonUtils.get_project_root_path(),    "outputs", "20260529_105859_deepseek-v4-flash_no_total_round-avg")

# 如果该文件夹中只有这 3 个实验 csv，可以保持 *.csv
# 如果还有其他 csv，建议改成更精确的匹配模式
CSV_PATTERN = "*.csv"

OUTPUT_FILE = INPUT_DIR / "averaged_3_runs.csv"

# ========== 2. 固定不变的列 ==========
ID_COLS = [
    'run_id',
    'iteration',  # 这俩列不需要
    "round",
    "num_agents",
    "proportion",
    "agent_id",
    "neighbor_1_id",
    "neighbor_2_id",
    "neighbor_3_id",
    "neighbor_4_id",
]

# ========== 3. 需要计算 3 次实验平均值的列 ==========
AVG_COLS = [
    "sent_to_n1",
    "sent_to_n2",
    "sent_to_n3",
    "sent_to_n4",
    "total_sent",
    "received_return_from_n1",
    "received_return_from_n2",
    "received_return_from_n3",
    "received_return_from_n4",
    "total_received_return",
    "received_send_from_n1",
    "received_send_from_n2",
    "received_send_from_n3",
    "received_send_from_n4",
    "total_received_send",
    "returned_to_n1",
    "returned_to_n2",
    "returned_to_n3",
    "returned_to_n4",
    "total_returned",
    "trustor_payoff",
    "trustee_payoff",
    "round_payoff",
    "last_accumulate_payoff",
    "accumulate_payoff",
]


def main() -> None:
    csv_files = sorted(INPUT_DIR.glob(CSV_PATTERN))

    # 避免把输出文件再次读入
    csv_files = [p for p in csv_files if p.name != OUTPUT_FILE.name]

    if len(csv_files) != 3:
        raise ValueError(
            f"当前匹配到 {len(csv_files)} 个 csv 文件，但期望正好 3 个。\n"
            f"匹配到的文件：{[p.name for p in csv_files]}\n"
            f"请检查 INPUT_DIR 或 CSV_PATTERN。"
        )

    print("读取文件：")
    for p in csv_files:
        print(" -", p.name)

    dfs = [pd.read_csv(p) for p in csv_files]

    # 检查 3 个文件的行列结构是否一致
    base_shape = dfs[0].shape
    base_columns = list(dfs[0].columns)
    for i, df in enumerate(dfs[1:], start=2):
        if df.shape != base_shape:
            raise ValueError(f"第 {i} 个文件的形状 {df.shape} 与第 1 个文件 {base_shape} 不一致。")
        if list(df.columns) != base_columns:
            raise ValueError(f"第 {i} 个文件的列名或列顺序与第 1 个文件不一致。")

    # 检查指定的固定列是否逐行一致
    for col in ID_COLS:
        if col not in base_columns:
            raise KeyError(f"缺少固定列：{col}")
        for i, df in enumerate(dfs[1:], start=2):
            if not dfs[0][col].equals(df[col]):
                raise ValueError(f"固定列 {col} 在第 {i} 个文件中与第 1 个文件不一致。")

    # 检查平均列是否存在，并转换为数值
    for col in AVG_COLS:
        if col not in base_columns:
            raise KeyError(f"缺少需要平均的列：{col}")

    # 以第一个文件为基础：固定列保持不变；平均列替换为 3 个文件的均值
    result = dfs[0].copy()
    for col in AVG_COLS:
        values = pd.concat([df[col] for df in dfs], axis=1).apply(pd.to_numeric, errors="raise")
        result[col] = values.mean(axis=1)

    # 处理未被列入 ID_COLS 或 AVG_COLS 的列，例如 agent_type
    other_cols = [c for c in base_columns if c not in ID_COLS and c not in AVG_COLS]
    for col in other_cols:
        all_same = all(dfs[0][col].equals(df[col]) for df in dfs[1:])
        if not all_same:
            print(
                f"提示：列 {col!r} 不在平均列中，且 3 个文件的值不完全一致；"
                "输出中将默认保留第 1 个文件的该列值。"
            )

    result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n完成：已输出到 {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
