import os
import json
import re
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# =========================
# 基础配置
# =========================

DATA_FILE = "data/prices.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 人民币参考汇率
# 后续可以改成自动获取实时汇率
RATES_TO_CNY = {
    "USD": 7.15,
    "CAD": 5.20,
    "DKK": 1.05,
    "JPY": 0.048,
    "CNY": 1.0
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 16) "
        "AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}

TIMEOUT = 25


# =========================
# 文件操作
# =========================

def load_data():
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

        data = {
            "products": {},
            "exchange_rates": RATES_TO_CNY,
            "last_update": None
        }

        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "products": {},
            "exchange_rates": RATES_TO_CNY,
            "last_update": None
        }


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================
# 工具
# =========================

def now():
    return datetime.now(timezone.utc).isoformat()


def product_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def currency_from_url(url):
    host = urlparse(url).netloc.lower()

    if ".ca" in host:
        return "CAD"

    if ".dk" in host:
        return "DKK"

    if ".jp" in host:
        return "JPY"

    return "USD"


def to_cny(price, currency):
    rate = RATES_TO_CNY.get(currency)

    if not rate:
        return None

    return round(price * rate, 2)


def money(value, currency):
    if value is None:
        return "-"

    symbols = {
        "USD": "$",
        "CAD": "C$",
        "DKK": "kr",
        "JPY": "¥",
        "CNY": "¥"
    }

    return f"{symbols.get(currency, '')}{value:,.2f}"


# =========================
# JSON-LD 商品信息
# =========================

def find_product_jsonld(soup):
    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    for script in scripts:
        try:
            obj = json.loads(script.string or script.get_text())

            objects = obj if isinstance(obj, list) else [obj]

            for item in objects:
                if not isinstance(item, dict):
                    continue

                if item.get("@type") == "Product":
                    return item

                if isinstance(item.get("@graph"), list):
                    for graph_item in item["@graph"]:
                        if (
                            isinstance(graph_item, dict)
                            and graph_item.get("@type") == "Product"
                        ):
                            return graph_item

        except Exception:
            continue

    return None


# =========================
# 价格解析
# =========================

def parse_number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value)

    value = value.replace(",", "")

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        value
    )

    if not match:
        return None

    return float(match.group())


def get_price(product):
    offers = product.get("offers")

    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    if not isinstance(offers, dict):
        offers = {}

    price = parse_number(offers.get("price"))

    low_price = parse_number(
        offers.get("lowPrice")
    )

    if price is None:
        price = low_price

    currency = offers.get("priceCurrency")

    return price, currency


# =========================
# 页面抓取
# =========================

def fetch_product(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    product = find_product_jsonld(soup)

    if not product:
        return {
            "success": False,
            "error": "页面没有找到标准 Product JSON-LD"
        }

    name = product.get("name") or "未知商品"

    price, currency = get_price(product)

    if currency is None:
        currency = currency_from_url(url)

    if price is None:
        return {
            "success": False,
            "error": "没有找到价格"
        }

    # 原价
    old_price = None

    offers = product.get("offers")

    if isinstance(offers, dict):
        old_price = parse_number(
            offers.get("priceSpecification", {}).get(
                "price"
            )
        )

    # 从页面文字中寻找折扣
    text = soup.get_text(" ", strip=True)

    discount = None

    discount_match = re.search(
        r"(\d{1,2})\s*%\s*(?:OFF|off|discount|折扣)",
        text
    )

    if discount_match:
        discount = float(
            discount_match.group(1)
        )

    # 尝试根据原价/现价计算折扣
    if old_price and price and old_price > price:
        discount = round(
            (old_price - price)
            / old_price
            * 100,
            1
        )

    # 颜色
    colors = []

    color_patterns = [
        r"Color[:：]\s*([^|,;\n]+)",
        r"Colour[:：]\s*([^|,;\n]+)"
    ]

    for pattern in color_patterns:
        matches = re.findall(
            pattern,
            text,
            re.I
        )

        for item in matches:
            item = item.strip()

            if item and item not in colors:
                colors.append(item)

    # 尺码
    sizes = []

    for size in [
        "XXS", "XS", "S", "M", "L", "XL", "XXL",
        "2XS", "2XL",
        "28", "30", "32", "34", "36", "38",
        "40", "42", "44"
    ]:
        if re.search(
            rf"\b{re.escape(size)}\b",
            text,
            re.I
        ):
            sizes.append(size)

    return {
        "success": True,
        "name": name.strip(),
        "url": url,
        "currency": currency,
        "price": price,
        "price_cny": to_cny(
            price,
            currency
        ),
        "old_price": old_price,
        "discount": discount,
        "colors": colors,
        "sizes": sizes,
        "checked_at": now()
    }


# =========================
# 是否需要通知
# =========================

def should_notify(old, new):
    if not old:
        # 第一次发现商品：
        # 只有有折扣才通知
        return (
            new.get("discount") is not None
            and new.get("discount", 0) > 0
        )

    # 价格发生变化
    if old.get("price") != new.get("price"):
        return True

    # 折扣变化
    if old.get("discount") != new.get("discount"):
        return True

    # 颜色变化
    if old.get("colors") != new.get("colors"):
        return True

    # 尺码变化
    if old.get("sizes") != new.get("sizes"):
        return True

    return False


# =========================
# Telegram
# =========================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN:
        print("没有设置 TELEGRAM_BOT_TOKEN")
        return False

    if not TELEGRAM_CHAT_ID:
        print("没有设置 TELEGRAM_CHAT_ID")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        return True

    except Exception as e:
        print("Telegram 推送失败:", e)
        return False


# =========================
# 消息
# =========================

def build_message(item, old):
    discount = item.get("discount")

    if discount is not None:
        if discount >= 50:
            title = "🔥🔥 超级优惠"
        elif discount >= 30:
            title = "🔥 30%+大折扣"
        else:
            title = "💰 商品价格变化"
    else:
        title = "💰 商品价格变化"

    currency = item["currency"]

    message = [
        title,
        "",
        f"商品：{item['name']}",
        f"本地价格：{money(item['price'], currency)}",
        f"人民币：¥{item['price_cny']:,.2f}",
    ]

    if discount is not None:
        message.append(
            f"折扣：{discount}%"
        )

    if old:
        old_price = old.get("price")

        if old_price != item["price"]:
            old_cny = old.get("price_cny")

            message.extend([
                "",
                "📉 价格变化：",
                f"{money(old_price, currency)}"
                f" → "
                f"{money(item['price'], currency)}"
            ])

            if old_cny is not None:
                message.append(
                    f"人民币：¥{old_cny:,.2f}"
                    f" → "
                    f"¥{item['price_cny']:,.2f}"
                )

    if item.get("colors"):
        message.extend([
            "",
            "🎨 颜色：",
            "、".join(item["colors"][:20])
        ])

    if item.get("sizes"):
        message.extend([
            "",
            "📏 页面检测到的尺码：",
            "、".join(item["sizes"])
        ])

    message.extend([
        "",
        "🔗 商品链接：",
        item["url"]
    ])

    return "\n".join(message)


# =========================
# 主程序
# =========================

def main():
    data = load_data()

    # =========================================
    # 商品链接
    # 后续我们会把这里改成自动发现
    # =========================================

    urls = [
        # 在这里加入需要监控的商品链接
        #
        # "https://www.rei.com/...",
        # "https://arcteryx.com/...",
        # "https://www.patagonia.com/...",
    ]

    if not urls:
        print(
            "当前还没有商品链接。"
            "下一步我们会建立 products.json "
            "自动管理监控商品。"
        )
        return

    for url in urls:
        print("检查:", url)

        result = fetch_product(url)

        if not result["success"]:
            print(
                "检查失败:",
                result.get("error")
            )
            continue

        pid = product_id(url)

        old = data["products"].get(pid)

        if should_notify(old, result):
            message = build_message(
                result,
                old
            )

            print(message)

            telegram_send(message)

        # 永远保存最新状态
        data["products"][pid] = result

    data["exchange_rates"] = RATES_TO_CNY
    data["last_update"] = now()

    save_data(data)

    print("监控完成:", now())


if __name__ == "__main__":
    main()
