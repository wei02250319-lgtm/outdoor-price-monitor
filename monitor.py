import requests
from bs4 import BeautifulSoup

URL = "https://www.rei.com/b/arcteryx/c/all"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

print("================================")
print("REI 快速连接测试")
print("================================")

try:
    print("正在连接 REI...")

    r = requests.get(
        URL,
        headers=HEADERS,
        timeout=15
    )

    print("HTTP状态码：", r.status_code)
    print("页面大小：", len(r.text), "字符")

    if r.status_code != 200:
        print("REI访问失败，请检查状态码。")
    else:
        soup = BeautifulSoup(r.text, "lxml")

        title = soup.title.string if soup.title else "无标题"

        print("网页标题：", title)

        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if "/product/" in href:
                if href not in links:
                    links.append(href)

        print("发现商品链接：", len(links))

        print("")
        print("测试完成。")

except Exception as e:
    print("测试发生错误：")
    print(type(e).__name__, e)

print("================================")
