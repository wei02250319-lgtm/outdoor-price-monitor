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

MAX_PRODUCTS = 1

# 只提醒这三个尺码
FOCUS_SIZES = {"M", "L", "XL"}


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

        if re.match(
            pattern,
            lower
        ):

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

        return (
            0,
            order[lower]
        )

    try:

        return (
            1,
            float(value)
        )

    except Exception:

        return (
            2,
            lower
        )


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

    combined_text = " ".join(
        script_texts
    )

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

        pattern = (
            rf"(?<![A-Za-z])"
            rf"{re.escape(size)}"
            rf"(?![A-Za-z])"
        )

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

    script_texts = []

    for script in soup.find_all("script"):

        text = script.get_text(
            " ",
            strip=True
        )

        if text:

            script_texts.append(text)

    combined_text = " ".join(
        script_texts
    )

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


def compare_lists(
    old_list,
    new_list
):

    old_set = set(
        old_list or []
    )

    new_set = set(
        new_list or []
    )

    added = sorted(
        new_set - old_set
    )

    removed = sorted(
        old_set - new_set
    )

    return added, removed


def compare_focus_sizes(
    old_list,
    new_list
):

    old_set = (
        set(old_list or [])
        & FOCUS_SIZES
    )

    new_set = (
        set(new_list or [])
        & FOCUS_SIZES
    )

    added = sorted(
        new_set - old_set,
        key=size_sort_key
    )

    removed = sorted(
        old_set - new_set,
        key=size_sort_key
    )

    return added, removed


def get_discount_label(discount):

    if discount is None:

        return ""

    if discount >= 50:

        return "🔥 超级优惠"

    if discount >= 30:

        return "🔥 重要优惠"

    if discount >= 20:

        return "🟢 达到20%提醒线"

    return ""


def stock_text(value):

    mapping = {

        "in_stock": "有货",

        "out_of_stock": "售罄",

        "unknown": "未知"

    }

    return mapping.get(
        value,
        value
    )


def build_product_message(
    product,
    events
):

    message = []

    message.append(
        "🏔️ REI 商品综合提醒"
    )

    message.append("")

    message.append(
        f"商品：{product['name']}"
    )

    if product.get("price") is not None:

        message.append(
            f"当前价格：${product['price']:.2f}"
        )

    if product.get("price_cny") is not None:

        message.append(
            f"人民币：¥{product['price_cny']:.2f}"
        )

    if product.get("original_price") is not None:

        message.append(
            f"原价：${product['original_price']:.2f}"
        )

    if product.get("discount") is not None:

        label = get_discount_label(
            product["discount"]
        )

        discount_line = (
            f"折扣：{product['discount']}%"
        )

        if label:

            discount_line += (
                f" {label}"
            )

        message.append(
            discount_line
        )

    message.append("")

    message.append(
        "📌 本次变化："
    )

    for event in events:

        message.append(event)

    message.append("")

    current_focus_sizes = (
        set(product.get("sizes", []))
        & FOCUS_SIZES
    )

    if current_focus_sizes:

        size_text = ", ".join(
            sorted(
                current_focus_sizes,
                key=size_sort_key
            )
        )

    else:

        size_text = "暂无"

    message.append(
        f"📏 当前关注尺码：{size_text}"
    )

    message.append(
        f"📦 当前库存："
        f"{stock_text(product.get('stock_status', 'unknown'))}"
    )

    message.append("")

    if product.get("colors"):

        message.append(
            "🎨 当前颜色："
            + ", ".join(
                product["colors"]
            )
        )

        message.append("")

    message.append(
        f"🔗 {product['url']}"
    )

    return "\n".join(message)


def main():

    print("================================")

    print(
        "Outdoor Price Monitor"
    )

    print(
        "价格 + 折扣 + 尺码 + 库存 + 颜色"
    )

    print(
        "一个商品汇总成一条 Telegram 消息"
    )

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

    html = fetch_page(
        REI_URL
    )

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

    products = products[
        :MAX_PRODUCTS
    ]

    data = load_data()

    # ==================================
    # 关键：
    # 每个商品独立收集所有变化
    # ==================================

    product_events = {}

    for product in products:

        key = (
            product.get("url")
            or product.get("name")
        )

        price = product.get(
            "price"
        )

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

        # ===============================
        # 抓取详情页
        # ===============================

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

            product["sizes"] = (
                inventory["sizes"]
            )

            product["stock_status"] = (
                inventory["stock_status"]
            )

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

            # 抓取失败时保留旧数据
            # 避免误判成无货/无颜色

            old_product = data[
                "products"
            ].get(
                key,
                {}
            )

            product["sizes"] = (
                old_product.get(
                    "sizes",
                    []
                )
            )

            product["stock_status"] = (
                old_product.get(
                    "stock_status",
                    "unknown"
                )
            )

            product["colors"] = (
                old_product.get(
                    "colors",
                    []
                )
            )

            print(
                "详情页抓取失败，"
                "保留上次尺码/库存/颜色"
            )

        old_product = data[
            "products"
        ].get(key)

        # ===============================
        # 第一次发现商品
        # ===============================

        if not old_product:

            print(
                "首次发现商品，不发送提醒:",
                product["name"]
            )

            data["products"][key] = (
                product
            )

            continue

        events = []

        # ===============================
        # 价格变化
        # ===============================

        old_price = old_product.get(
            "price"
        )

        if (
            old_price is not None
            and price < old_price
        ):

            drop_pct = round(
                (
                    old_price - price
                )
                / old_price
                * 100,
                1
            )

            if drop_pct >= 20:

                events.append(
                    f"📉 降价："
                    f"${old_price:.2f} → "
                    f"${price:.2f}，"
                    f"下降 {drop_pct}%"
                )

        # ===============================
        # 折扣变化
        # ===============================

        old_discount = (
            old_product.get(
                "discount"
            )
        )

        new_discount = (
            product.get(
                "discount"
            )
        )

        if new_discount is not None:

            if old_discount is None:

                if new_discount >= 20:

                    events.append(
                        f"🏷️ 进入促销："
                        f"当前折扣 {new_discount}%"
                    )

            elif new_discount > old_discount:

                events.append(
                    f"🏷️ 折扣增加："
                    f"{old_discount}% → "
                    f"{new_discount}%"
                )

        # ===============================
        # M / L / XL 尺码变化
        # ===============================

        added_sizes, removed_sizes = (
            compare_focus_sizes(
                old_product.get(
                    "sizes",
                    []
                ),
                product.get(
                    "sizes",
                    []
                )
            )
        )

        if added_sizes:

            events.append(
                "📏 新增关注尺码 🟢："
                + ", ".join(
                    added_sizes
                )
            )

        if removed_sizes:

            events.append(
                "📏 消失关注尺码 🔴："
                + ", ".join(
                    removed_sizes
                )
            )

        # ===============================
        # 库存变化
        # ===============================

        old_stock = old_product.get(
            "stock_status",
            "unknown"
        )

        new_stock = product.get(
            "stock_status",
            "unknown"
        )

        if (
            old_stock != new_stock
            and new_stock != "unknown"
        ):

            events.append(
                "📦 库存状态："
                f"{stock_text(old_stock)} → "
                f"{stock_text(new_stock)}"
            )

        # ===============================
        # 颜色变化
        # ===============================

        old_colors = old_product.get(
            "colors",
            []
        )

        new_colors = product.get(
            "colors",
            []
        )

        added_colors, removed_colors = (
            compare_lists(
                old_colors,
                new_colors
            )
        )

        if added_colors:

            events.append(
                "🎨 新增颜色 🟢："
                + ", ".join(
                    added_colors
                )
            )

        if removed_colors:

            events.append(
                "🎨 消失颜色 🔴："
                + ", ".join(
                    removed_colors
                )
            )

        # ===============================
        # 如果这个商品有任何变化
        # 就暂存起来
        # 最后统一发送
        # ===============================

        if events:

            product_events[key] = {

                "product": product,

                "events": events

            }

            print(
                "发现商品变化，准备汇总推送:",
                product["name"]
            )

        # 保存最新数据

        data["products"][key] = (
            product
        )

    # ===============================
    # 保存数据
    # ===============================

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

    print(
        "需要推送的商品:",
        len(product_events)
    )

    # ===============================
    # Telegram 汇总推送
    #
    # 一个商品 = 一条消息
    # ===============================

    for item in product_events.values():

        product = item["product"]

        events = item["events"]

        message = build_product_message(
            product,
            events
        )

        if send_telegram(message):

            print(
                "已发送商品汇总提醒:",
                product["name"]
            )

    if not product_events:

        print(
            "没有需要推送的变化"
        )

    print(
        "运行完成"
    )


if __name__ == "__main__":

    main()
