#!/usr/bin/env python
# coding: utf-8

"""
信任博弈数据分析脚本
- 分别处理 sent_amount 和 returned_amount
- 去重规则：同一 round, proportion, trustor_id, 金额值 只保留一条
- 计算各 proportion 分组的箱线图统计量
- 生成散点 jitter 数据
- 保存到 plot_data.xlsx 的两个 sheet 中
- 绘制 sent_amount 的复刻图（散点+箱线图，无异常值）
"""
import os
import numpy as np
from src.utils import CommonUtils
import pandas as pd

# 默认 CSV 文件路径
csv_dir = os.path.join(
    CommonUtils.get_project_root_path(),
    "outputs",
    "20260509_Char-BDI_deepseek-v4-flash_trust_game"
)
# 读取数据（请确保文件路径正确）
file_name = "20260509_142151_trust_game_p-[0, 0.25,0.5,0.75,1]_pair_data_v2.xlsx"
file_path = os.path.join(csv_dir, file_name)
df = pd.read_excel(file_path)  # 实际为 xlsx 格式，使用 read_excel

def process_column(df, col_name):
    """
    对指定列进行去重和分组处理
    - 去重：按 ['round', 'proportion', 'trustor_id', col_name] 保留第一条
    - 按 proportion 分组，收集该列的所有值（保持原顺序）
    - 返回每个 proportion 对应的值列表（长度可能不同）
    """
    # 去重
    deduped = df.drop_duplicates(subset=['round', 'proportion', 'trustor_id', col_name])
    # 按 proportion 分组并收集值
    grouped = deduped.groupby('proportion')[col_name].apply(list).to_dict()
    # 转换为 DataFrame（不同长度的列表自动填充 NaN）
    result_df = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in grouped.items()]))
    # 按 proportion 升序排列列
    result_df = result_df.reindex(sorted(result_df.columns), axis=1)
    return result_df

# 处理 sent_amount 和 returned_amount
df_sent = process_column(df, 'sent_amount')
df_return = process_column(df, 'returned_amount')

# 保存到 Excel 文件
output_path = os.path.join(csv_dir, 'plot_data.xlsx')

if os.path.exists(output_path):
    # 如果文件已存在，读取现有数据并追加新 sheet
    with pd.ExcelFile(output_path) as existing_file:
        existing_sheets = {sheet: pd.read_excel(existing_file, sheet_name=sheet)
                          for sheet in existing_file.sheet_names}

    with pd.ExcelWriter(output_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        # 保留原有的 sheets
        for sheet_name, sheet_data in existing_sheets.items():
            if sheet_name not in ['group_sent', 'group_return']:
                sheet_data.to_excel(writer, sheet_name=sheet_name, index=False)

        # 写入或更新新的 sheets
        df_sent.to_excel(writer, sheet_name='group_sent', index=False)
        df_return.to_excel(writer, sheet_name='group_return', index=False)
else:
    # 文件不存在，直接创建
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df_sent.to_excel(writer, sheet_name='group_sent', index=False)
        df_return.to_excel(writer, sheet_name='group_return', index=False)

print(f"数据已保存至 {output_path}")