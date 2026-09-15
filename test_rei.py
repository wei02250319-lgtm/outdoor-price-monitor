import requests

url = "https://api.scrapingant.com/v2/general"

params = {
    "url": "https://www.rei.com/b/arcteryx/c/all",
    "x-api-key": "YOUR_API_KEY"
}

print("开始测试 REI...")
r = requests.get(url, params=params, timeout=60)

print("状态码:", r.status_code)
print("网页长度:", len(r.text))

if r.status_code == 200 and len(r.text) > 10000:
    print("✅ 测试成功：已经能够通过中转访问 REI")
else:
    print("❌ 测试失败")
    print(r.text[:500])
