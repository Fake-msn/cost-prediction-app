import requests, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Test 1: Knowledge query (桥梁工程 - not in typical types)
print("=== Test 1: Knowledge query (桥梁工程) ===")
r = requests.post('http://localhost:8000/api/chat', json={
    'message': '桥梁工程的造价一般是多少？请基于你的专业知识回答',
    'session_id': 'test_harden_1'
})
d = r.json()
reply = d.get("reply", "")
print(f"Backend: {d.get('backend')}")
print(f"Reply length: {len(reply)} chars")
print(f"Reply preview: {reply[:300]}")
print(f"PASS: {len(reply) > 50}")
print()

# Test 2: Knowledge query (住宅 - should have data or typical range)
print("=== Test 2: Knowledge query (住宅) ===")
r = requests.post('http://localhost:8000/api/chat', json={
    'message': '住宅建筑的造价一般是多少？',
    'session_id': 'test_harden_2'
})
d = r.json()
reply = d.get("reply", "")
print(f"Backend: {d.get('backend')}")
print(f"Reply length: {len(reply)} chars")
print(f"Reply preview: {reply[:300]}")
print(f"PASS: {len(reply) > 50}")
print()

# Test 3: Greeting (should not fallback to empty)
print("=== Test 3: Greeting ===")
r = requests.post('http://localhost:8000/api/chat', json={
    'message': '你好',
    'session_id': 'test_harden_3'
})
d = r.json()
reply = d.get("reply", "")
print(f"Backend: {d.get('backend')}")
print(f"Reply length: {len(reply)} chars")
print(f"PASS: {len(reply) > 20}")
print()

# Test 4: Infrastructure query (基础设施 - previously could be empty)
print("=== Test 4: Knowledge query (基础设施) ===")
r = requests.post('http://localhost:8000/api/chat', json={
    'message': '基础设施项目的造价水平如何？',
    'session_id': 'test_harden_4'
})
d = r.json()
reply = d.get("reply", "")
print(f"Backend: {d.get('backend')}")
print(f"Reply length: {len(reply)} chars")
print(f"Reply preview: {reply[:300]}")
print(f"PASS: {len(reply) > 50}")
print()

# Test 5: General knowledge query (no specific type)
print("=== Test 5: General knowledge query (no specific type) ===")
r = requests.post('http://localhost:8000/api/chat', json={
    'message': '各类建筑的造价一般是多少？',
    'session_id': 'test_harden_5'
})
d = r.json()
reply = d.get("reply", "")
print(f"Backend: {d.get('backend')}")
print(f"Reply length: {len(reply)} chars")
print(f"Reply preview: {reply[:300]}")
print(f"PASS: {len(reply) > 50}")
print()

# Summary
print("=== ALL TESTS COMPLETE ===")
