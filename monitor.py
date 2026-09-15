import os
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

URLS = {
    "Arc'teryx": "https://www.rei.com/b/arcteryx/c/all",
    "Patagonia": "https://www.rei.com/b/patagonia/c/all",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram配置缺失")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=15
        )
        print("Telegram:", r.status_code)
    except Exception as e:
        print("Telegram错误:", e)

def check_brand(brand, url):
    print("")
    print("正在检查:", brand)

    try:
        r = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        print("HTTP:", r.status_code)

        if r.status_code != 200:
            return

        soup = BeautifulSoup(r.text, "lxml")

        products = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if "/product/" not in href:
                continue

            name = a.get_text(" ", strip=True)

            if name and href not in [x[0] for x in products]:
                products.append((href, name))

            if len(products) >= 10:
                break

        print("发现商品:", len(products))

        if products:
            message = (
                f"🛍️ REI监控测试\n\n"
                f"品牌：{brand}\n"
                f"发现商品：{len(products)} 个\n\n"
                f"监控连接正常。"
            )

            send_telegram(message)

    except Exception as e:
        print("检查错误:", type(e).__name__, e)

def main():
    print("================================")
    print("REI 户外商品监控")
    print("================================")

    for brand, url in URLS.items():
        check_brand(brand, url)

    print("")
    print("本次检查完成")

if __name__ == "__main__":
    main()
