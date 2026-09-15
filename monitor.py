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


def is_valid_size(value):
    if not value:
        return False

    value = str(value).strip()

    if len(value) > 30:
        return False

    invalid_words = [
        "color",
        "colour",
        "black",
        "blue",
        "red",
        "green",
        "white",
        "gray",
        "grey",
        "jacket",
        "hoody",
        "hoodie",
        "men",
        "women"
    ]

    lower = value.lower()

    if lower in invalid_words:
        return False

    size_patterns = [
        r"^(xxs|xs|s|m|l|xl|xxl|xxxl)$",
        r"^(2xs|3xs|2xl|3xl|4xl)$",
        r"^\d{1,2}$",
        r"^\d{1,2}\s*-\s*\d{1,2}$"
    ]

    for pattern in size_patterns:
        if re.match(pattern, lower):
            return True

    return False


def size_sort_key(value):
    order = {
        "xxxs": 0,
        "xxs": 1,
        "2xs": 1,
        "xs": 2,
        "s": 3,
        "m": 4,
        "l": 5,
        "xl": 6,
        "xxl": 7,
        "2xl": 7,
        "xxxl": 8,
        "3xl": 8,
        "4xl": 9
    }

    lower = str(value).lower()

    if lower in order:
        return (0, order[lower])

    try:
        return (1, float(value))
    except Exception:
        return (2, lower)


def extract_inventory(soup):
    sizes = set()

    script_texts = []

    for script in soup.find_all("script"):
        text = script.get_text(
            " ",
            strip=True
        )

        if text:
            script_texts.append(text)

    combined_text = " ".join(script_texts)

    size_patterns = [
        r'"size"\s*:\s*"([^"]+)"',
        r'"displaySize"\s*:\s*"([^"]+)"',
        r'"sizeName"\s*:\s*"([^"]+)"'
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
        "XXXS",
        "XXS",
        "2XS",
        "XS",
        "S",
        "M",
        "L",
        "XL",
        "XXL",
        "2XL",
        "XXXL",
        "3XL",
        "4XL"
    ]

    for size in common_sizes:

        pattern = rf"(?<![A-Za-z]){re.escape(size)}(?![A-Za-z])"

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

    lower_text = combined_text.lower()

    if (
        "out of stock" in lower_text
        or "sold out" in lower_text
        or "unavailable" in lower_text
    ):
        stock_status = "out_of_stock"

    elif (
        "in stock" in lower_text
        or "available" in lower_text
        or sizes
    ):
        stock_status = "in_stock"

    else:
        stock_status = "unknown"

    return {
        "sizes": sizes,
        "stock_status": stock_status
    }


def clean_color(value):
    if value is None:
        return None

    value = str(value).strip()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    if not value:
        return None

    if len(value) > 80:
        return None

    invalid = [
        "size",
        "sizes",
        "price",
        "quantity",
        "availability",
        "in stock",
        "out of stock",
        "undefined",
        "null"
    ]

    if value.lower() in invalid:
        return None

    return value


def extract_colors(soup):
    colors = set()

    # 读取页面中的 JSON / script
    script_texts = []

    for script in soup.find_all("script"):
        text = script.get_text(
            " ",
            strip=True
        )

        if text:
            script_texts.append(text)

    combined_text = " ".join(script_texts)

    # 常见颜色字段
    color_patterns = [
        r'"color"\s*:\s*"([^"]+)"',
        r'"colorName"\s*:\s*"([^"]+)"',
        r'"displayColor"\s*:\s*"([^"]+)"',
        r'"colour"\s*:\s*"([^"]+)"',
        r'"colourName"\s*:\s*"([^"]+)"'
    ]

    for pattern in color_patterns:

        matches = re.findall(
            pattern,
            combined_text,
            flags=re.IGNORECASE
        )

        for value in matches:

            color = clean_color(value)

            if color:
                colors.add(color)

    # 从页面文字中寻找 Color / Colour 后面的内容
    visible_text = soup.get_text(
        " ",
        strip=True
    )

    visible_patterns = [
        r"Color\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 /&'\-]{1,60})",
        r"Colour\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 /&'\-]{1,60})"
    ]

    for pattern in visible_patterns:

        matches = re.findall(
            pattern,
            visible_text,
            flags=re.IGNORECASE
        )

        for value in matches:

            color = clean_color(value)

            if color:
                colors.add(color)

    return sorted(
        colors,
        key=lambda x: x.lower()
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

            data = json.load(f)

        if "products" not in data:
            data["products"] = {}

        return data

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


def compare_lists(old_list, new_list):

    old_set = set(old_list or [])
    new_set = set(new_list or [])

    added = sorted(
        new_set - old_set
    )

    removed = sorted(
        old_set - new_set
    )

    return added, removed


def main():

    print("================================")
    print("Outdoor Price Monitor")
    print("价格 + 尺码 + 库存 + 颜色")
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
        "商品解析:",
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
    color_changes = []

    for product in products:

        key = (
            product.get("url")
            or product.get("name")
        )

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

        # 抓取商品详情页
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

            colors = extract_colors(
                detail_soup
            )

            product["sizes"] = inventory[
                "sizes"
            ]

            product["stock_status"] = inventory[
                "stock_status"
            ]

            product["colors"] = colors

            print(
                "商品:",
                product["name"]
            )

            print(
                "尺码:",
                product["sizes"]
            )

            print(
                "库存:",
                product["stock_status"]
            )

            print(
                "颜色:",
                product["colors"]
            )

        else:

            product["sizes"] = []
            product["stock_status"] = "unknown"
            product["colors"] = []

        old_product = data[
            "products"
        ].get(key)

        # 第一次发现商品
        if not old_product:

            print(
                "首次发现商品，不发送变化提醒:",
                product["name"]
            )

            data["products"][key] = product

            continue

        # =========================
        # 价格变化
        # =========================

        old_price = old_product.get(
            "price"
        )

        if (
            old_price is not None
            and price <= old_price * 0.8
        ):

            price_drop_products.append({
                "name": product["name"],
                "old_price": old_price,
                "new_price": price,
                "price_cny": product[
                    "price_cny"
                ],
                "discount": product.get(
                    "discount"
                ),
                "url": product["url"]
            })

            print(
                "发现降价:",
                product["name"],
                old_price,
                "->",
                price
            )

        # =========================
        # 尺码变化
        # =========================

        old_sizes = old_product.get(
            "sizes",
            []
        )

        new_sizes = product.get(
            "sizes",
            []
        )

        added_sizes, removed_sizes = compare_lists(
            old_sizes,
            new_sizes
        )

        if (
            added_sizes
            or removed_sizes
        ):

            inventory_changes.append({
                "name": product["name"],
                "url": product["url"],
                "added_sizes": added_sizes,
                "removed_sizes": removed_sizes,
                "old_stock": old_product.get(
                    "stock_status",
                    "unknown"
                ),
                "new_stock": product.get(
                    "stock_status",
                    "unknown"
                )
            })

        # =========================
        # 库存变化
        # =========================

        old_stock = old_product.get(
            "stock_status",
            "unknown"
        )

        new_stock = product.get(
            "stock_status",
            "unknown"
        )

        if old_stock != new_stock:

            already_exists = False

            for item in inventory_changes:

                if item["name"] == product["name"]:
                    already_exists = True
                    break

            if not already_exists:

                inventory_changes.append({
                    "name": product["name"],
                    "url": product["url"],
                    "added_sizes": [],
                    "removed_sizes": [],
                    "old_stock": old_stock,
                    "new_stock": new_stock
                })

        # =========================
        # 颜色变化
        # =========================

        old_colors = old_product.get(
            "colors",
            []
        )

        new_colors = product.get(
            "colors",
            []
        )

        added_colors, removed_colors = compare_lists(
            old_colors,
            new_colors
        )

        if (
            added_colors
            or removed_colors
        ):

            color_changes.append({
                "name": product["name"],
                "url": product["url"],
                "added_colors": added_colors,
                "removed_colors": removed_colors
            })

            print(
                "发现颜色变化:",
                product["name"]
            )

        # 保存最新数据
        data["products"][key] = product

    data["last_update"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    save_data(data)

    print(
        "已保存价格数据:",
        len(products)
    )

    # =========================
    # Telegram：价格提醒
    # =========================

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
                    f"折扣：{item['discount']}%\n"
                )

            message += (
                f"链接：{item['url']}\n\n"
            )

        send_telegram(message)

        print(
            "已发送降价提醒:",
            len(price_drop_products)
        )

    # =========================
    # Telegram：库存/尺码提醒
    # =========================

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
                    "新增尺码 🟢："
                    + ", ".join(
                        item["added_sizes"]
                    )
                    + "\n"
                )

            if item["removed_sizes"]:

                message += (
                    "消失尺码 🔴："
                    + ", ".join(
                        item["removed_sizes"]
                    )
                    + "\n"
                )

            if (
                item["old_stock"]
                != item["new_stock"]
            ):

                message += (
                    f"库存："
                    f"{item['old_stock']} → "
                    f"{item['new_stock']}\n"
                )

            message += (
                f"链接：{item['url']}\n\n"
            )

        send_telegram(message)

        print(
            "已发送库存/尺码提醒:",
            len(inventory_changes)
        )

    # =========================
    # Telegram：颜色提醒
    # =========================

    if color_changes:

        message = (
            "🎨 REI 始祖鸟颜色变化提醒\n\n"
        )

        for item in color_changes:

            message += (
                f"商品：{item['name']}\n"
            )

            if item["added_colors"]:

                message += (
                    "新增颜色 🟢："
                    + ", ".join(
                        item["added_colors"]
                    )
                    + "\n"
                )

            if item["removed_colors"]:

                message += (
                    "消失颜色 🔴："
                    + ", ".join(
                        item["removed_colors"]
                    )
                    + "\n"
                )

            message += (
                f"链接：{item['url']}\n\n"
            )

        send_telegram(message)

        print(
            "已发送颜色变化提醒:",
            len(color_changes)
        )

    if not price_drop_products:
        print(
            "没有达到20%降价条件，不发送价格提醒"
        )

    if not inventory_changes:
        print(
            "没有发现尺码/库存变化"
        )

    if not color_changes:
        print(
            "没有发现颜色变化"
        )

    print("运行完成")


if __name__ == "__main__":
    main()
