import os
import json
import re
import requests
from bs4 import BeautifulSoup

CRAWLBASE_JS_TOKEN = os.getenv("CRAWLBASE_JS_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DATA_FILE = "data/prices.json"
REI_URL = "https://www.rei.com/b/arcteryx/c/all"
MAX_PRODUCTS = 5


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram 配置缺失")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.post(url, data=data, timeout=30)
        print("Telegram:", r.status_code)
        return r.ok
    except Exception as e:
        print("Telegram 发送失败:", e)
        return False


def fetch_page(url):
    if not CRAWLBASE_JS_TOKEN:
        print("CRAWLBASE_JS_TOKEN 未配置")
        return None

    api = "https://api.crawlbase.com/"
    params = {
        "token": CRAWLBASE_JS_TOKEN,
        "url": url,
        "javascript": "true",
        "page_wait": 3000
    }

    print("正在抓取:", url)

    try:
        r = requests.get(api, params=params, timeout=90)
        print("Crawlbase:", r.status_code)

        if r.ok:
            return r.text

        print(r.text[:500])

    except Exception as e:
        print("抓取失败:", e)

    return None
    def price_to_number(value):
    if value is None:
        return None
    text = str(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


def extract_jsonld_products(soup):
    products = []

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text())
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]

        for item in items:
            if not isinstance(item, dict):
                continue

            if item.get("@type") != "Product":
                continue

            name = item.get("name")
            url = item.get("url")
            offers = item.get("offers")

            price = None
            currency = None

            if isinstance(offers, dict):
                price = price_to_number(offers.get("price"))
                currency = offers.get("priceCurrency")

            elif isinstance(offers, list) and offers:
                first = offers[0]
                if isinstance(first, dict):
                    price = price_to_number(first.get("price"))
                    currency = first.get("priceCurrency")

            if name:
                products.append({
                    "name": name,
                    "url": url,
                    "price": price,
                    "currency": currency
                })

    return products


def extract_product_links(soup):
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if "/product/" not in href:
            continue

        if href.startswith("/"):
            href = "https://www.rei.com" + href

        if href not in links:
            links.append(href)

    return links
    def deduplicate_products(products):
    result = []
    seen = set()

    for product in products:
        key = product.get("url") or product.get("name")

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(product)

    return result


def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    print("================================")
    print("Outdoor Price Monitor")
    print("开始运行")
    print("================================")

    if not CRAWLBASE_JS_TOKEN:
        print("错误：没有 CRAWLBASE_JS_TOKEN")
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("错误：Telegram Secrets 不完整")
        return

    html = fetch_page(REI_URL)

    if not html:
        print("没有取得网页内容")
        return

    print("网页抓取成功，长度:", len(html))

    soup = BeautifulSoup(html, "lxml")

    products = extract_jsonld_products(soup)
    links = extract_product_links(soup)

    print("JSON-LD 商品:", len(products))
    print("商品链接:", len(links))

    products = deduplicate_products(products)
    products = products[:MAX_PRODUCTS]
        data = load_data()

    for product in products:
        key = product.get("url") or product.get("name")
        data["products"][key] = product

    from datetime import datetime, timezone

    data["last_update"] = datetime.now(timezone.utc).isoformat()

    save_data(data)

    print("已保存价格数据:", len(products))

    message = (
        "🟢 户外价格监控运行成功\n\n"
        "REI 始祖鸟页面\n"
        f"本次发现商品：{len(products)} 个\n"
        "监控程序已正常运行。"
    )

    send_telegram(message)

    print("运行完成")


if __name__ == "__main__":
    main()
