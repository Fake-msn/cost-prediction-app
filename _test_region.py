import requests, json

r = requests.post('http://localhost:8000/api/chat', json={'message': '成都高新区呢', 'session_id': 't1'})
d = r.json()
reply = d.get('reply', '')
print(f"Backend: {d.get('backend')}")
print(f"Has generic menu: {'1.造价预测' in reply}")
print(f"Has 高新区: {'高新区' in reply}")
print(f"Reply:\n{reply[:600]}")
