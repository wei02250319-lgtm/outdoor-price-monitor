import os
import json
import re
import time
import hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# 基础配置
# ============================================================

DATA_FILE = "data/prices.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 第一版使用固定参考汇率
# 后续可以升级成实时汇率
USD_TO_CNY = 7.15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# REI 两个重点品牌
BRANDS = {
    "Arc'teryx": "https://www.rei.com/b/arcteryx/c/all",
    "Patagonia": "https://www.rei.com/b/patagonia/c/all",
}

# 每个品牌最多扫描页数
# 第一版先控制访问量，后续可以继续扩大
MAX_PAGES = 20

REQUEST_TIMEOUT = 30

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# 文件
# ============================================================

def load_data():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(DATA_FILE):
        return {
            "products": {},
            "exchange_rates": {
                "USD": USD_TO_CNY,
                "CNY": 1.0
            },
            "last_update": None
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "products" not in data:
            data["products"] = {}

        return data

    except Exception:
        return {
            "products": {},
            "exchange_rates": {
                "USD": USD_TO_CNY,
                "CNY": 1.0
            },
            "last_update": None
        }


def save_data(data):
    os.makedirs("data", exist_ok=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 网络
# ============================================================

def get_page(url):
    for attempt in range(3):
        try:
            response = session.get(
                url,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                return response.text

            print(
                f"[WARN] HTTP {response.status_code}: {url}"
            )

        except Exception as e:
            print(
                f"[WARN] request failed "
                f"{attempt + 1}/3: {url} -> {e}"
            )

        time.sleep(2)

    return ""


# ============================================================
# JSON-LD
# ============================================================

def extract_jsonld_products(soup):
    products = []

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):
        try:
            raw = script.string

            if not raw:
                continue

            data = json.loads(raw)

        except Exception:
            continue

        if isinstance(data, dict):
            if data.get("@type") == "Product":
                products.append(data)

            if isinstance(data.get("@graph"), list):
                for item in data["@graph"]:
                    if (
                        isinstance(item, dict)
                        and item.get("@type") == "Product"
                    ):
                        products.append(item)

        elif isinstance(data, list):
            for item in data:
                if (
                    isinstance(item, dict)
                    and item.get("@type") == "Product"
                ):
                    products.append(item)

    return products


# ============================================================
# 价格
# ============================================================

def number_from_text(text):
    if not text:
        return None

    text = str(text).replace(",", "")

    match = re.search(
        r"(\d+(?:\.\d{1,2})?)",
        text
    )

    if not match:
        return None

    try:
        return float(match.group(1))
    except Exception:
        return None


def get_price(product):
    offers = product.get("offers")

    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    if not isinstance(offers, dict):
        offers = {}

    price = (
        offers.get("price")
        or product.get("price")
    )

    price_value = number_from_text(price)

    return price_value


def detect_original_price(text):
    if not text:
        return None

    # 常见形式：
    # $199.83 - $300.00
    # $199.83 $300.00
    # Save 25% compared to $260.00
    patterns = [
        r"Save\s+\d+%\s+compared\s+to\s+\$?([\d,]+(?:\.\d{1,2})?)",
        r"\$([\d,]+\.\d{2})\s*-\s*\$([\d,]+\.\d{2})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            continue

        if len(match.groups()) == 1:
            return number_from_text(match.group(1))

        values = []

        for value in match.groups():
            number = number_from_text(value)

            if number is not None:
                values.append(number)

        if len(values) >= 2:
            return max(values)

    return None


def detect_discount(text, current_price, original_price):
    if not text:
        text = ""

    match = re.search(
        r"(\d+)%\s*(?:off|save)",
        text,
        re.IGNORECASE
    )

    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass

    if (
        current_price is not None
        and original_price is not None
        and original_price > current_price
    ):
        discount = (
            1 - current_price / original_price
        ) * 100

        return round(discount)

    return 0


# ============================================================
# 商品信息
# ============================================================

def clean_text(text):
    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def get_product_id(url, name):
    raw = f"{url}|{name}"

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


def parse_jsonld_product(product, brand):
    name = clean_text(
        product.get("name", "")
    )

    url = ""

    offers = product.get("offers")

    if isinstance(offers, list):
        offers = offers[0] if offers else {}

    if isinstance(offers, dict):
        url = offers.get("url", "")

    if not url:
        url = product.get("url", "")

    if url:
        url = urljoin(
            "https://www.rei.com",
            url
        )

    price = get_price(product)

    if not name or price is None:
        return None

    currency = "USD"

    description = clean_text(
        product.get("description", "")
    )

    original_price = detect_original_price(
        description
    )

    discount = detect_discount(
        description,
        price,
        original_price
    )

    product_id = get_product_id(
        url,
        name
    )

    return {
        "id": product_id,
        "brand": brand,
        "name": name,
        "url": url,
        "currency": currency,
        "price": round(price, 2),
        "original_price": (
            round(original_price, 2)
            if original_price
            else None
        ),
        "discount": discount,
        "sizes": [],
        "colors": [],
        "stock": "unknown"
    }


# ============================================================
# 页面商品链接备用解析
# ============================================================

def extract_product_links(soup):
    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")

        if "/product/" not in href:
            continue

        url = urljoin(
            "https://www.rei.com",
            href
        )

        if url not in links:
            links.append(url)

    return links


# ============================================================
# 解析品牌页面
# ============================================================

def parse_brand_page(html, brand):
    if not html:
        return []

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    products = []

    # 第一优先：JSON-LD
    jsonld_products = extract_jsonld_products(
        soup
    )

    for item in jsonld_products:
        parsed = parse_jsonld_product(
            item,
            brand
        )

        if parsed:
            products.append(parsed)

    # 去重
    unique = {}

    for product in products:
        unique[product["id"]] = product

    return list(unique.values())


# ============================================================
# 发现商品
# ============================================================

def discover_brand_products(brand, base_url):
    all_products = {}

    print(
        f"\n========== {brand} =========="
    )

    for page in range(1, MAX_PAGES + 1):

        if page == 1:
            url = base_url
        else:
            url = f"{base_url}?page={page}"

        print(
            f"[SCAN] {brand} page {page}"
        )

        html = get_page(url)

        if not html:
            print(
                f"[WARN] empty page: {url}"
            )
            continue

        products = parse_brand_page(
            html,
            brand
        )

        print(
            f"[FOUND] {len(products)} products"
        )

        before = len(all_products)

        for product in products:
            all_products[
                product["id"]
            ] = product

        after = len(all_products)

        # 如果连续页面没有新增商品，
        # 后面的页面大概率已经没有内容
        if page > 2 and after == before:
            print(
                "[INFO] no new products, stop paging"
            )
            break

        time.sleep(1)

    return list(all_products.values())


# ============================================================
# 人民币
# ============================================================

def to_cny(price, currency):
    if price is None:
        return None

    if currency == "USD":
        return round(
            price * USD_TO_CNY,
            2
        )

    if currency == "CNY":
        return round(price, 2)

    return None


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print(
            "[WARN] TELEGRAM_BOT_TOKEN missing"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "[WARN] TELEGRAM_CHAT_ID missing"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
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

        if response.status_code == 200:
            print("[TELEGRAM] sent")
            return True

        print(
            "[TELEGRAM] failed:",
            response.text[:500]
        )

    except Exception as e:
        print(
            "[TELEGRAM] error:",
            e
        )

    return False


# ============================================================
# 是否需要提醒
# ============================================================

def should_notify(old, new):
    # 第一次发现商品：
    # 只有已经打折才提醒
    if old is None:
        return new.get("discount", 0) > 0

    # 价格变化
    if old.get("price") != new.get("price"):
        return True

    # 折扣变化
    if old.get("discount") != new.get("discount"):
        return True

    # 原价变化
    if old.get("original_price") != new.get(
        "original_price"
    ):
        return True

    # 尺码变化
    if old.get("sizes") != new.get("sizes"):
        return True

    # 颜色变化
    if old.get("colors") != new.get("colors"):
        return True

    # 库存变化
    if old.get("stock") != new.get("stock"):
        return True

    return False


# ============================================================
# Telegram 消息
# ============================================================

def make_message(product, old=None):
    brand = product["brand"]
    name = product["name"]

    price = product["price"]
    price_cny = to_cny(
        price,
        product["currency"]
    )

    original = product.get(
        "original_price"
    )

    discount = product.get(
        "discount",
        0
    )

    if discount >= 50:
        level = "🔥🔥 超级优惠"
    elif discount >= 30:
        level = "🔥 重点优惠"
    elif discount > 0:
        level = "🏷️ 有折扣"
    else:
        level = "📌 价格变化"

    lines = [
        f"{level}",
        "",
        f"品牌：{brand}",
        f"商品：{name}",
        "",
        f"REI价格：${price:.2f}",
    ]

    if price_cny is not None:
        lines.append(
            f"人民币约：¥{price_cny:.0f}"
        )

    if original:
        lines.append(
            f"原价：${original:.2f}"
        )

    if discount:
        lines.append(
            f"折扣：{discount}% OFF"
        )

    if old:
        old_price = old.get("price")

        if old_price is not None:
            change = price - old_price

            if change < 0:
                lines.append(
                    f"⬇️ 比上次低：${abs(change):.2f}"
                )

            elif change > 0:
                lines.append(
                    f"⬆️ 比上次高：${change:.2f}"
                )

    if product.get("url"):
        lines.extend([
            "",
            product["url"]
        ])

    return "\n".join(lines)


# ============================================================
# 主程序
# ============================================================

def main():
    print(
        "\n======================================"
    )
    print(
        " REI Outdoor Price Monitor"
    )
    print(
        " Arc'teryx + Patagonia"
    )
    print(
        "======================================"
    )

    data = load_data()

    old_products = data.get(
        "products",
        {}
    )

    new_products = {}

    total_found = 0
    notifications = 0

    for brand, url in BRANDS.items():

        products = discover_brand_products(
            brand,
            url
        )

        total_found += len(products)

        for product in products:

            product_id = product["id"]

            old = old_products.get(
                product_id
            )

            new_products[product_id] = product

            if should_notify(
                old,
                product
            ):
                message = make_message(
                    product,
                    old
                )

                print(
                    "\n[NOTIFY]"
                )
                print(message)

                if send_telegram(message):
                    notifications += 1

                # 避免短时间大量发送
                time.sleep(0.5)

    data["products"] = new_products

    data["exchange_rates"] = {
        "USD_CNY": USD_TO_CNY
    }

    data["last_update"] = datetime.now(
        timezone.utc
    ).isoformat()

    save_data(data)

    print(
        "\n======================================"
    )
    print(
        f"商品数量：{total_found}"
    )
    print(
        f"本次推送：{notifications}"
    )
    print(
        "历史价格：已保存"
    )
    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
