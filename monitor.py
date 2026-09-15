import requests
from bs4 import BeautifulSoup

URL = "https://www.rei.com/b/arcteryx/c/all"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

print("=" * 40)
print("REI 直连测试")
print("=" * 40)
print("正在访问:", URL)

try:
    r = requests.get(URL, headers=headers, timeout=30)

    print("HTTP状态:", r.status_code)
    print("网页长度:", len(r.text))

    if r.status_code == 200 and len(r.text) > 10000:
        print("✅ REI网页抓取成功")

        soup = BeautifulSoup(r.text, "lxml")

        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]

            if "/product/" in href:
                if href.startswith("/"):
                    href = "https://www.rei.com" + href

                if href not in links:
                    links.append(href)

        print("发现商品链接:", len(links))

        for link in links[:10]:
            print("商品:", link)

        print("=" * 40)
        print("✅ 第一次直连测试成功")
        print("=" * 40)

    else:
        print("❌ REI返回异常")
        print(r.text[:500])

except Exception as e:
    print("❌ 抓取失败:")
    print(type(e).__name__, str(e))
