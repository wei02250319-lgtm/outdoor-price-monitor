import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone


CRAWLBASE_JS_TOKEN = os.getenv("CRAWLBASE_JS_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DATA_FILE = "data/prices.json"

USD_TO_CNY = 7.10

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
        r = requests.post(
            url,
            data=data,
            timeout=30
        )

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
        r = requests.get(
            api,
            params=params,
            timeout=90
        )

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

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


def extract_jsonld_products(soup):
    products = []

    for a in soup.find_all("a", href=True):

        href = a.get("href", "")

        if "/product/" not in href:
            continue

        name = a.get_text(
            " ",
            strip=True
        )

        if not name:
            continue

        if href.startswith("/"):
            full_url = "https://www.rei.com" + href
        else:
            full_url = href

        parent_text = ""

        if a.parent:
            parent_text = a.parent.get_text(
                " ",
                strip=True
            )

        text = parent_text[:2000]

        prices = re.findall(
            r"\$\s?(\d+(?:\.\d{1,2})?)",
            text
        )

        price = None
        original_price = None

        if prices:

            numbers = [
                float(x)
                for x in prices
            ]

            price = numbers[0]

            if len(numbers) > 1:
                original_price = max(numbers)

        discount = None

        if (
            price is not None
            and original_price is not None
            and original_price > price
        ):
            discount = round(
                (original_price - price)
                / original_price
                * 100
            )

        products.append({
            "name": name,
            "url": full_url,
            "price": price,
            "original_price": original_price,
            "discount": discount,
            "currency": "USD"
        })

    return products


def extract_product_links(soup):
    links = []

    for a in soup.find_all(
        "a",
        href=True
    ):

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

        key = (
            product.get("url")
            or product.get("name")
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)

        result.append(product)

    return result


def extract_inventory(soup):
    """
    尝试从 REI 商品详情页提取尺码/库存信息。

    返回：
    {
        "sizes": [...],
        "stock_status": "in_stock" / "out_of_stock" / "unknown"
    }
    """

    sizes = set()

    # 先检查页面中的 JSON / script 内容
    script_texts = []

    for script in soup.find_all("script"):
        text = script.get_text(" ", strip=True)

        if text:
            script_texts.append(text)

    combined_text = " ".join(script_texts)

    # 常见尺码关键词
    size_patterns = [
        r'"size"\s*:\s*"([^"]+)"',
        r'"displaySize"\s*:\s*"([^"]+)"',
        r'"sizeName"\s*:\s*"([^"]+)"',
        r'"label"\s*:\s*"([^"]+)"'
    ]

    for pattern in size_patterns:

        matches = re.findall(
            pattern,
            combined_text,
            flags=re.IGNORECASE
        )

        for value in matches:

            value = value.strip()

            if is_valid_size(value):
                sizes.add(value)

    # 再从页面可见文字中寻找常见尺码
    visible_text = soup.get_text(
        " ",
        strip=True
    )

    common_sizes = [
        "XXS",
        "XS",
        "S",
        "M",
        "L",
        "XL",
        "XXL",
        "XXXL",
        "2XS",
        "2XL",
        "3XL",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
        "42",
        "43",
        "44",
        "45",
        "46",
        "48",
        "50",
        "52",
        "54"
    ]

    for size in common_sizes:

        pattern = rf"\b{re.escape(size)}\b"

        if re.search(
            pattern,
            visible_text,
            flags=re.IGNORECASE
        ):
            sizes.add(size)

    sizes = sorted(
        sizes,
        key=size_sort_key
    )

    lower_text = visible_text.lower()

    if (
        "out of stock" in lower_text
        or "sold out" in lower_text
        or "unavailable" in lower_text
    ):
        stock_status = "out_of_stock"

    elif (
        "add to cart" in lower_text
        or "add to bag" in lower_text
        or "in stock" in lower_text
    ):
        stock_status = "in_stock"

    else:
        stock_status = "unknown"

    return {
        "sizes": sizes,
        "stock_status": stock_status
    }


def is_valid_size(value):

    if not value:
        return False

    value = value.strip().upper()

    if len(value) > 12:
        return False

    allowed = {
        "XXS",
        "XS",
        "S",
        "M",
        "L",
        "XL",
        "XXL",
        "XXXL",
        "2XS",
        "2XL",
        "3XL"
    }

    if value in allowed:
        return True

    if re.fullmatch(
        r"\d{2}",
        value
    ):
        number = int(value)

        if 28 <= number <= 60:
            return True

    return False


def size_sort_key(value):

    order = {
        "XXS": 0,
        "2XS": 1,
        "XS": 2,
        "S": 3,
        "M": 4,
        "L": 5,
        "XL": 6,
        "2XL": 7,
        "XXL": 8,
        "3XL": 9,
        "XXXL": 10
    }

    value_upper = value.upper()

    if value_upper in order:
        return (
            0,
            order[value_upper]
        )

    try:
        return (
            1,
            int(value)
        )
    except Exception:
        return (
            2,
            value
        )


def load_data():

    if not os.path.exists(DATA_FILE):

        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }


def save_data(data):

    os.makedirs(
        os.path.dirname(DATA_FILE),
        exist_ok=True
    )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def main():

    print("================================")
    print("Outdoor Price Monitor")
    print("开始运行")
    print("================================")

    if not CRAWLBASE_JS_TOKEN:

        print(
            "错误：没有 CRAWLBASE_JS_TOKEN"
        )

        return

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "错误：Telegram Secrets 不完整"
        )

        return

    html = fetch_page(REI_URL)

    if not html:

        print(
            "没有取得网页内容"
        )

        return

    print(
        "网页抓取成功，长度:",
        len(html)
    )

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    products = extract_jsonld_products(
        soup
    )

    links = extract_product_links(
        soup
    )

    print(
        "JSON-LD 商品:",
        len(products)
    )

    print(
        "商品链接:",
        len(links)
    )

    products = deduplicate_products(
        products
    )

    products = products[:MAX_PRODUCTS]

    data = load_data()

    price_drop_products = []
    inventory_changes = []

    for product in products:

        price = product.get("price")

        if price is None:

            print(
                "跳过没有价格的商品:",
                product.get("name")
            )

            continue

        product["price_cny"] = round(
            price * USD_TO_CNY,
            2
        )

        key = (
            product.get("url")
            or product.get("name")
        )

        old_product = data["products"].get(
            key
        )

        # -----------------------------
        # 抓取商品详情页库存/尺码
        # -----------------------------

        detail_html = fetch_page(
            product["url"]
        )

        if detail_html:

            detail_soup = BeautifulSoup(
                detail_html,
                "lxml"
            )

            inventory = extract_inventory(
                detail_soup
            )

            product["sizes"] = inventory[
                "sizes"
            ]

            product["stock_status"] = inventory[
                "stock_status"
            ]

            print(
                "尺码:",
                product["sizes"]
            )

            print(
                "库存状态:",
                product["stock_status"]
            )

        else:

            product["sizes"] = []

            product["stock_status"] = (
                "unknown"
            )

            print(
                "商品详情页抓取失败，"
                "库存状态未知"
            )

        # -----------------------------
        # 价格变化
        # -----------------------------

        if old_product:

            old_price = old_product.get(
                "price"
            )

            # 价格下降 20% 或以上
            if (
                old_price is not None
                and price <= old_price * 0.8
            ):

                price_drop_products.append({

                    "name": product.get(
                        "name"
                    ),

                    "old_price": old_price,

                    "new_price": price,

                    "price_cny": product[
                        "price_cny"
                    ],

                    "discount": product.get(
                        "discount"
                    ),

                    "url": product.get(
                        "url"
                    )
                })

                print(
                    "发现降价:",
                    product.get("name"),
                    old_price,
                    "->",
                    price
                )

        else:

            print(
                "首次发现商品，不推送:",
                product.get("name")
            )

        # -----------------------------
        # 尺码变化
        # -----------------------------

        if old_product:

            old_sizes = set(
                old_product.get(
                    "sizes",
                    []
                )
            )

            new_sizes = set(
                product.get(
                    "sizes",
                    []
                )
            )

            added_sizes = sorted(
                new_sizes - old_sizes,
                key=size_sort_key
            )

            removed_sizes = sorted(
                old_sizes - new_sizes,
                key=size_sort_key
            )

            old_stock = old_product.get(
                "stock_status",
                "unknown"
            )

            new_stock = product.get(
                "stock_status",
                "unknown"
            )

            if (
                added_sizes
                or removed_sizes
                or (
                    old_stock != new_stock
                    and new_stock != "unknown"
                )
            ):

                inventory_changes.append({

                    "name": product.get(
                        "name"
                    ),

                    "url": product.get(
                        "url"
                    ),

                    "added_sizes": added_sizes,

                    "removed_sizes": removed_sizes,

                    "old_stock": old_stock,

                    "new_stock": new_stock
                })

                print(
                    "发现库存/尺码变化:",
                    product.get("name")
                )

        data["products"][key] = product

    # -----------------------------
    # 更新时间
    # -----------------------------

    data["last_update"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    save_data(data)

    print(
        "已保存价格和库存数据:",
        len(products)
    )

    # -----------------------------
    # Telegram：价格提醒
    # -----------------------------

    if price_drop_products:

        message = (
            "🔥 REI 始祖鸟降价提醒\n\n"
        )

        for item in price_drop_products:

            message += (
                f"商品：{item['name']}\n"
                f"原价格：${item['old_price']:.2f}\n"
                f"新价格：${item['new_price']:.2f}\n"
                f"人民币：¥{item['price_cny']:.2f}\n"
            )

            if item["discount"] is not None:

                message += (
                    f"折扣："
                    f"{item['discount']}%\n"
                )

            message += (
                f"链接：{item['url']}\n\n"
            )

        send_telegram(message)

        print(
            "已发送降价提醒:",
            len(price_drop_products)
        )

    # -----------------------------
    # Telegram：库存/尺码提醒
    # -----------------------------

    if inventory_changes:

        message = (
            "📦 REI 始祖鸟库存/尺码变化\n\n"
        )

        for item in inventory_changes:

            message += (
                f"商品：{item['name']}\n"
            )

            if item["added_sizes"]:

                message += (
                    "🟢 新增尺码："
                    + ", ".join(
                        item["added_sizes"]
                    )
                    + "\n"
                )

            if item["removed_sizes"]:

                message += (
                    "🔴 消失尺码："
                    + ", ".join(
                        item["removed_sizes"]
                    )
                    + "\n"
                )

            if (
                item["old_stock"]
                != item["new_stock"]
            ):

                if (
                    item["new_stock"]
                    == "in_stock"
                ):

                    message += (
                        "🟢 状态：补货/有货\n"
                    )

                elif (
                    item["new_stock"]
                    == "out_of_stock"
                ):

                    message += (
                        "🔴 状态：售罄/缺货\n"
                    )

            message += (
                f"链接：{item['url']}\n\n"
            )

        send_telegram(message)

        print(
            "已发送库存变化提醒:",
            len(inventory_changes)
        )

    if (
        not price_drop_products
        and not inventory_changes
    ):

        print(
            "没有价格或库存变化，"
            "不发送 Telegram"
        )

    print("运行完成")


if __name__ == "__main__":
    main()
