import requests

url = "https://api.firecrawl.dev/v2/scrape"

data = {
    "url": "https://www.rei.com/b/arcteryx/c/all",
    "formats": ["markdown"]
}

print("开始测试 Firecrawl → REI")

try:
    r = requests.post(
        url,
        json=data,
        timeout=90
    )

    print("HTTP状态:", r.status_code)
    print("返回长度:", len(r.text))
    print("返回内容前500字:")
    print(r.text[:500])

    if r.status_code == 200:
        print("✅ Firecrawl 抓取成功")
    else:
        print("❌ Firecrawl 测试失败")

except Exception as e:
    print("❌ 程序错误:", type(e).__name__, str(e))
