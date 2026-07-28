# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

df = pd.read_excel('data/real_training_data.xlsx')
print('=== Training Data Overview ===')
print(f'Total rows: {len(df)}')
print(f'Columns: {df.columns.tolist()}')
print()

opt = ['人工费','材料费','机械费','措施费','企业管理费','规费','利润','税金',
       '基础工程费','主体结构费','屋面工程费','外墙工程费',
       '混凝土总用量','钢筋总用量','砌块总用量']

print('=== Optional Fields: Zero vs Non-zero counts ===')
for f in opt:
    if f in df.columns:
        zeros = (df[f] == 0).sum()
        nonzeros = (df[f] != 0).sum()
        total_val = df[f].sum()
        print(f'  {f}: {zeros} zeros, {nonzeros} non-zero, sum={total_val:,.2f}')

print()
print('=== Source type distribution ===')
print(df['source_type'].value_counts().to_string())
print()
print('=== Data confidence distribution ===')
print(df['data_confidence'].value_counts().to_string())

# Show a sample row with most non-zero values
print()
print('=== Sample row (first type A with most data) ===')
type_a = df[df['source_type'] == 'A']
if len(type_a) > 0:
    row = type_a.iloc[0]
    for col in df.columns:
        print(f'  {col}: {row[col]}')