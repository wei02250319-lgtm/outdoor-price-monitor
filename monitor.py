import requests

URL = "https://www.rei.com/b/arcteryx/c/all"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

print("================================")
print("REI 连接测试")
print("================================")

try:
    print("正在连接 REI...")

    r = requests.get(
        URL,
        headers=HEADERS,
        timeout=10
    )

    print("HTTP状态码：", r.status_code)
    print("页面大小：", len(r.text), "字符")

    if r.status_code == 200:
        print("✅ REI 连接成功")
    else:
        print("⚠️ REI 返回异常状态")

except Exception as e:
    print("❌ REI 连接失败")
    print(type(e).__name__, e)

print("================================")
print("测试结束")
