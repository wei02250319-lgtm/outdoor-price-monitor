import os
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# =========================
# 配置
# =========================

CRAWLBASE_TOKEN = os.getenv("CRAWLBASE_JS_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DATA_FILE = "data/prices.json"

# 本阶段只测试 REI 始祖鸟
REI_URL = "https://www.rei.com/b/arcteryx/c/all"

# 第一次只抓 5 个商品，节省 Crawlbase 配额
MAX_PRODUCTS = 5


# =========================
# Telegram
# =========================

def send_telegram(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Telegram 配置不完整")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True
            },
            timeout=20
        )

        print("Telegram:", response.status_code)

        if response.status_code == 200:
            return True

        print(response.text[:500])
        return False

    except Exception as e:
        print("Telegram 发送失败:", type(e).__name__, e)
        return False


# =========================
# Crawlbase 获取网页
# =========================

def fetch_page(url):
    if not CRAWLBASE_TOKEN:
        print("❌ 没有读取到 CRAWLBASE_JS_TOKEN")
        return None

    api_url = "https://api.crawlbase.com/"

    params = {
        "token": CRAWLBASE_TOKEN,
        "url": url,
        "javascript": "true",
        "page_wait": "3000"
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            timeout=90
        )

        print("Crawlbase:", response.status_code)
        print("页面长度:", len(response.text))

        if response.status_code != 200:
            print(response.text[:500])
            return None

        return response.text

    except Exception as e:
        print("❌ Crawlbase 获取失败:", type(e).__name__, e)
        return None


# =========================
# 价格转换
# =========================

def price_to_number(value):
    if not value:
        return None

    value = str(value)

    # 删除货币符号和文字
    value = re.sub(r"[^\d.,]", "", value)

    if not value:
        return None

    # 处理 1,299.00
    if "," in value and "." in value:
        value = value.replace(",", "")

    # 处理 1,299
    elif "," in value:
        parts = value.split(",")

        if len(parts[-1]) == 2:
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")

    try:
        return float(value)
    except:
        return None


# =========================
# 计算折扣
# =========================

def calculate_discount(original_price, sale_price):

    if not original_price or not sale_price:
        return None

    if original_price <= sale_price:
        return None

    discount = (
        (original_price - sale_price)
        / original_price
        * 100
    )

    return round(discount, 1)


# =========================
# JSON-LD 商品解析
# =========================

def extract_jsonld_products(soup):

    products = []

    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    for script in scripts:

        try:
            data = json.loads(script.string or script.get_text())
        except:
            continue

        items = []

        if isinstance(data, list):
            items = data

        elif isinstance(data, dict):

            if "@graph" in data:
                items = data["@graph"]

            else:
                items = [data]

        for item in items:

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")

            if isinstance(item_type, list):
                is_product = "Product" in item_type
            else:
                is_product = item_type == "Product"

            if not is_product:
                continue

            name = item.get("name")

            if not name:
                continue

            offers = item.get("offers")

            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            if not isinstance(offers, dict):
                offers = {}

            price = offers.get("price")

            currency = offers.get("priceCurrency")

            url = item.get("url")

            if not url:
                url = offers.get("url")

            image = item.get("image")

            if isinstance(image, list):
                image = image[0] if image else None

            product = {
                "name": str(name).strip(),
                "price": price_to_number(price),
                "currency": currency or "USD",
                "url": url,
                "image": image
            }

            products.append(product)

    return products


# =========================
# 从页面链接补充商品
