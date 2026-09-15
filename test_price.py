import requests
import re

print("=" * 60)
print("REI 商品价格解析测试")
print("=" * 60)

url = "https://api.firecrawl.dev/v2/scrape"

data = {
    "url": "https://www.rei.com/b/arcteryx/c/all",
    "formats": ["markdown"]
}

r = requests.post(url, json=data, timeout=90)

print("Firecrawl 状态:", r.status_code)

if r.status_code != 200:
    print("❌ 抓取失败")
    print(r.text[:1000])
    raise SystemExit

result = r.json()
markdown = result.get("data", {}).get("markdown", "")

print("网页内容长度:", len(markdown))

# 找商品链接
links = re.findall(
    r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
    markdown
)

links = list(dict.fromkeys(links))

print("发现商品链接:", len(links))
print()

# 测试前10个商品
for i, link in enumerate(links[:10], 1):

    print("-" * 60)
    print("商品", i)
    print("链接:", link)

    pos = markdown.find(link)

    if pos == -1:
        continue

    text = markdown[pos:pos + 2000]

    # 找美元价格
    prices = re.findall(
        r'\$\s?\d+(?:\.\d{2})?',
        text
    )

    # 去重
    prices = list(dict.fromkeys(prices))

    print("发现价格:", prices[:10])

    # 显示商品附近文字
    clean = re.sub(r'\n+', '\n', text)

    print("商品信息:")
    print(clean[:1000])

print()
print("=" * 60)
print("✅ REI 价格解析测试完成")
print("=" * 60)
