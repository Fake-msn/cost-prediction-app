import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests, json

# Test: same config twice to verify determinism
c = dict(project_type='\u4f4f\u5b85', structure_type='\u6846\u67b6\u7ed3\u6784', total_area=10000, floors=10, location='\u6210\u90fd', build_year=2023, decoration_level='\u666e\u901a\u88c5\u4fee', project_name='dup_test')
r1 = requests.post('http://localhost:8000/api/predict', json=c).json()
r2 = requests.post('http://localhost:8000/api/predict', json=c).json()
print('Same config twice:')
print(f'  Run1: unit={r1["fused_unit_price"]}, total={r1["fused_total_cost"]}')
print(f'  Run2: unit={r2["fused_unit_price"]}, total={r2["fused_total_cost"]}')
print(f'  trade same? {r1["trade_composition"] == r2["trade_composition"]}')
print(f'  division same? {r1["division_composition"] == r2["division_composition"]}')
print(f'  indicators same? {r1["indicators"] == r2["indicators"]}')
print(f'  material same? {r1["material_consumption"] == r2["material_consumption"]}')
print()

# Test: only change decoration
c2 = dict(c, decoration_level='\u8c6a\u534e\u88c5\u4fee', project_name='deco_test')
r3 = requests.post('http://localhost:8000/api/predict', json=c2).json()
print('Change decoration only:')
print(f'  unit={r3["fused_unit_price"]} (was {r1["fused_unit_price"]})')
print(f'  trade: {json.dumps(r3["trade_composition"], ensure_ascii=False)}')
print(f'  division: {json.dumps(r3["division_composition"], ensure_ascii=False)}')
print(f'  indicators: {json.dumps(r3["indicators"], ensure_ascii=False)}')
print(f'  material: {json.dumps(r3["material_consumption"], ensure_ascii=False)}')
print()

# Test: only change location
c3 = dict(c, location='\u5317\u4eac', project_name='loc_test')
r4 = requests.post('http://localhost:8000/api/predict', json=c3).json()
print('Change location only:')
print(f'  unit={r4["fused_unit_price"]} (was {r1["fused_unit_price"]})')
print(f'  trade: {json.dumps(r4["trade_composition"], ensure_ascii=False)}')
print(f'  division: {json.dumps(r4["division_composition"], ensure_ascii=False)}')
print()

# Test: only change structure_type
c4 = dict(c, structure_type='\u94a2\u7ed3\u6784', project_name='struct_test')
r5 = requests.post('http://localhost:8000/api/predict', json=c4).json()
print('Change structure_type only:')
print(f'  unit={r5["fused_unit_price"]} (was {r1["fused_unit_price"]})')
print(f'  trade: {json.dumps(r5["trade_composition"], ensure_ascii=False)}')
print(f'  division: {json.dumps(r5["division_composition"], ensure_ascii=False)}')
