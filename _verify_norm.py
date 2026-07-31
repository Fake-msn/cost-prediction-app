import requests, json

payload = {
    'building_type': '住宅', 'structure_type': '框架结构',
    'total_area': 50000, 'floors': 18, 'region': '四川',
    'year': 2023, 'decoration': '一般装修'
}
r = requests.post('http://localhost:8000/api/predict', json=payload)
d = r.json()
print(json.dumps(d, indent=2, ensure_ascii=False, default=str)[:3000])
