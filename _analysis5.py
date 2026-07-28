# -*- coding: utf-8 -*-
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl
from collections import Counter

base = r'd:\工程造价预测AI项目模板'
dirs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])

# Collect all section names from 表-08 across all projects
all_sections = Counter()
project_count = 0
for d in dirs[:5]:  # Check first 5 projects
    target_path = os.path.join(base, d)
    xlsx_files = [f for f in os.listdir(target_path) if f.endswith('.xlsx') and not f.startswith('~$') and '项目信息' not in f]
    if not xlsx_files:
        continue
    wb_path = os.path.join(target_path, xlsx_files[0])
    try:
        wb = openpyxl.load_workbook(wb_path, read_only=True, data_only=True)
        t08_sheets = [s for s in wb.sheetnames if '表-08' in s and 'F.1.1' in s]  # Only F.1.1 type
        for sheet_name in t08_sheets:
            ws = wb[sheet_name]
            for row in ws.iter_rows(values_only=True):
                if row and len(row) >= 3:
                    name = str(row[2]).strip() if row[2] else ''
                    if name and ('工程' in name or '分部' in name) and len(name) < 30:
                        all_sections[name] += 1
        wb.close()
        project_count += 1
    except Exception as e:
        print(f'Error with {d}: {e}')

print(f'Checked {project_count} projects')
print(f'\nAll 表-08 section names (across {project_count} projects):')
for name, count in all_sections.most_common():
    print(f'  {name}: {count} occurrences')