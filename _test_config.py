import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests, json

configs = [
    dict(project_type='\u4f4f\u5b85', structure_type='\u6846\u67b6\u7ed3\u6784', total_area=5000, floors=5, location='\u56db\u5ddd', build_year=2023, decoration_level='\u4e00\u822c\u88c5\u4fee'),
    dict(project_type='\u5546\u4e1a\u7efc\u5408\u4f53', structure_type='\u94a2\u7ed3\u6784', total_area=200000, floors=99, location='\u5317\u4eac', build_year=2024, decoration_level='\u7cbe\u88c5\u4fee'),
    dict(project_type='\u529e\u516c\u697c', structure_type='\u526a\u529b\u5899\u7ed3\u6784', total_area=50000, floors=30, location='\u4e0a\u6d77', build_year=2020, decoration_level='\u8c6a\u534e\u88c5\u4fee'),
]

for i, c in enumerate(configs):
    r = requests.post('http://localhost:8000/api/predict', json=dict(**c, project_name=f'Test{i+1}')).json()
    print(f'=== Config {i+1}: {c["project_type"]} {c["floors"]}F {c["total_area"]}m2 ===')
    print(f'  fused_unit_price: {r.get("fused_unit_price")}')
    print(f'  fused_total_cost: {r.get("fused_total_cost")}')
    print(f'  average_accuracy: {r.get("average_accuracy")}')
    print(f'  scale_factor: {r.get("scale_factor")}')
    print(f'  trade_composition: {json.dumps(r.get("trade_composition", {}), ensure_ascii=False)}')
    print(f'  division_composition: {json.dumps(r.get("division_composition", {}), ensure_ascii=False)}')
    print(f'  indicators: {json.dumps(r.get("indicators", {}), ensure_ascii=False)}')
    mc = r.get("material_consumption", {})
    print(f'  material_consumption: {json.dumps(mc, ensure_ascii=False)}')
    print()

print('=== Models ===')
r2 = requests.get('http://localhost:8000/api/models').json()
for layer, models in r2.items():
    for m in models:
        print(f'  {m["id"]}: accuracy={m.get("accuracy")}, trained={m.get("is_trained")}, samples={m.get("train_samples")}')
