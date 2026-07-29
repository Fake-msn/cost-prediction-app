#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量运行 extract_boq.py 处理模板目录中所有项目（健壮版）"""
import os
import re
import subprocess
import sys
import hashlib
import duckdb

source = r'd:\工程造价预测AI项目模板'
extractor = r'backend\scripts\extract_boq.py'
db_path = 'data/cost_prediction.duckdb'

# 获取已在数据库中的项目ID集合
conn = duckdb.connect(db_path)
existing_ids = set(r[0] for r in conn.execute('SELECT project_id FROM boq_items').fetchall())
existing_proj_count = conn.execute('SELECT COUNT(*) FROM project_meta').fetchone()[0]
existing_boq_count = conn.execute('SELECT COUNT(*) FROM boq_items').fetchone()[0]
conn.close()
print(f'DB current: {existing_proj_count} projects, {existing_boq_count} BOQ items, {len(existing_ids)} projects with BOQ')

folders = sorted([f for f in os.listdir(source) if os.path.isdir(os.path.join(source, f))])
print(f'Found {len(folders)} project folders in template\n')

success = 0
fail = 0
skip = 0
already_done = 0

for i, folder in enumerate(folders):
    folder_path = os.path.join(source, folder)
    xlsx_files = [f for f in os.listdir(folder_path) if f.endswith('.xlsx') and '项目信息' not in f]
    
    if not xlsx_files:
        print(f'[{i+1}/{len(folders)}] SKIP {folder[:50]}: no main xlsx')
        skip += 1
        continue
    
    # 计算该项目对应的project_id（与extract_boq.py逻辑一致）
    folder_name = os.path.basename(folder_path)
    proj_name = re.sub(r'^\d+\.?\s*', '', folder_name)
    project_id = hashlib.md5(proj_name.encode()).hexdigest()[:12]
    
    if project_id in existing_ids:
        print(f'[{i+1}/{len(folders)}] ALREADY DONE: {folder[:50]}')
        already_done += 1
        continue
    
    xlsx_path = os.path.join(folder_path, xlsx_files[0])
    print(f'[{i+1}/{len(folders)}] Processing: {folder[:50]}...')
    sys.stdout.flush()
    
    try:
        result = subprocess.run(
            [sys.executable, extractor, '--input', xlsx_path, '--db-path', db_path],
            capture_output=True, text=True, timeout=300,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        if result.returncode == 0:
            success += 1
            for line in result.stdout.split('\n'):
                if '清单' in line or '表-08' in line or '提取' in line:
                    print(f'  {line.strip()}')
        else:
            fail += 1
            stderr_short = result.stderr[:300] if result.stderr else '(no stderr)'
            print(f'  ERROR (rc={result.returncode}): {stderr_short}')
    except subprocess.TimeoutExpired:
        fail += 1
        print(f'  TIMEOUT (>300s)')
    except MemoryError:
        fail += 1
        print(f'  MEMORY ERROR')
    except Exception as e:
        fail += 1
        print(f'  EXCEPTION: {e}')
    
    sys.stdout.flush()

print(f'\n=== Summary ===')
print(f'Total folders: {len(folders)}')
print(f'Already done:  {already_done}')
print(f'New success:   {success}')
print(f'Failed/skip:   {fail} / {skip}')

# Final DB stats
conn = duckdb.connect(db_path)
final_proj = conn.execute('SELECT COUNT(*) FROM project_meta').fetchone()[0]
final_boq = conn.execute('SELECT COUNT(*) FROM boq_items').fetchone()[0]
conn.close()
print(f'\n=== Final DB: {final_proj} projects, {final_boq} BOQ items ===')
