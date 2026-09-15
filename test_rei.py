import requests
import re

url = "https://api.firecrawl.dev/v2/scrape"

data = {
    "url": "https://www.rei.com/b/arcteryx/c/all",
    "formats": ["markdown"]
}

print("=" * 50)
print("REI 商品解析测试")
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

# 查找 REI 商品链接
links = re.findall(
    r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
    markdown
)

# 去重
links = list(dict.fromkeys(links))

print("发现商品链接:", len(links))
print()

for i, link in enumerate(links[:20], 1):
    print(f"{i}. {link}")

print()
print("=" * 50)

if links:
    print("✅ REI 商品链接解析成功")
else:
    print("❌ 没找到商品链接")

print("=" * 50)
