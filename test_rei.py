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

try:
    r = requests.post(url, json=data, timeout=90)

    print("Firecrawl 状态:", r.status_code)

    if r.status_code != 200:
        print("❌ Firecrawl 抓取失败")
        print(r.text[:1000])
        raise SystemExit

    result = r.json()
    markdown = result.get("data", {}).get("markdown", "")

    print("网页内容长度:", len(markdown))

    # 找 REI 商品链接
    links = re.findall(
        r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
        markdown
    )

    links = list(dict.fromkeys(links))

    print("发现商品链接:", len(links))
    print()

    if not links:
        print("❌ 没找到商品链接")
        raise SystemExit

    # 显示前10个商品及附近价格信息
    for i, link in enumerate(links[:10], 1):

        print("-" * 60)
        print("商品", i)
        print("链接:", link)

        pos = markdown.find(link)

        if pos >= 0:
            nearby = markdown[pos:pos + 1500]

            # 简单清理文字
            nearby = re.sub(r'\n+', '\n', nearby)

            print("商品信息:")
            print(nearby[:1200])

    print()
    print("=" * 60)
    print("✅ REI 商品价格解析测试完成")
    print("=" * 60)

except Exception as e:
    print("❌ 程序发生错误:")
    print(str(e))
