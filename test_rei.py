import requests
import re

url = "https://api.firecrawl.dev/v2/scrape"

data = {
    "url": "https://www.rei.com/b/arcteryx/c/all",
    "formats": ["markdown"]
}

print("=" * 50)
print("REI 价格解析测试")
print("=" * 50)

r = requests.post(url, json=data, timeout=90)

print("Firecrawl 状态:", r.status_code)

if r.status_code != 200:
    print("❌ 抓取失败")
    print(r.text[:1000])
    raise SystemExit

result = r.json()
markdown = result.get("data", {}).get("markdown", "")

print("网页内容长度:", len(markdown))

# 提取 REI 商品链接
links = re.findall(
    r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
    markdown
)

links = list(dict.fromkeys(links))

print("发现商品链接:", len(links))
print()

# 输出前 10 个商品附近的内容
for i, link in enumerate(links[:10], 1):
    print("-" * 50)
    print(f"商品 {i}")
    print("链接:", link)

    pos = markdown.find(link)

    if pos >= 0:
        nearby = markdown[pos:pos + 1200]

        # 清理多余空白
        nearby = re.sub(r'\n+', '\n', nearby)

        print("商品页面内容:")
        print(nearby[:1000])

print("=" * 50)
print("✅ REI 商品数据解析测试完成")
print("=" * 50)
