import os
import json
import time
import requests
from pathlib import Path
from collections import defaultdict


# =========================================================
# 基本配置
# =========================================================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = Path("data/prices.json")

# 每轮抓取数量
BATCH_SIZE = 3

# Firecrawl 请求间隔
REQUEST_INTERVAL = 9

# 最低推送折扣
MIN_DISCOUNT = 20.0


# =========================================================
# 监控商品
# =========================================================

PRODUCTS = [
    {
        "name": "Arc'teryx Gamma MX Hoody - Men's",
        "url": "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens",
    },
    {
        "name": "Arc'teryx Gamma Jacket - Men's",
        "url": "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens",
    },
    {
        "name": "Arc'teryx Gamma Pants - Men's",
        "url": "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens",
    },
    {
        "name": "Patagonia R2 TechFace Jacket - Men's",
        "url": "https://www.rei.com/product/222148/patagonia-r2-techface-jacket-mens",
    },
    {
        "name": "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "url": "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
    },
    {
        "name": "Arc'teryx Atom Insulated Jacket - Men's",
        "url": "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
    },
    {
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
    },
]


# =========================================================
# 历史记录
# =========================================================

def load_history():
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        return {
            "position": 0,
            "products": {}
        }

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("历史文件格式错误")

        data.setdefault("position", 0)
        data.setdefault("products", {})

        return data

    except Exception as e:
        print(f"历史文件读取失败: {e}")

        return {
            "position": 0,
            "products": {}
        }


def save_history(history):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = HISTORY_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp_file.replace(HISTORY_FILE)


# =========================================================
# Firecrawl
# =========================================================

def firecrawl_product(url):
    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")
        return None

    endpoint = "https://api.firecrawl.dev/v2/scrape"

    payload = {
        "url": url,
        "formats": ["product"],
        "waitFor": 3000,
    }

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=90,
        )

        print(f"Firecrawl: {response.status_code}")

        if response.status_code != 200:
            print(
                "Firecrawl 错误:",
                response.text[:500]
            )
            return None

        data = response.json()

        # Firecrawl v2
        result = data.get("data", data)

        product = result.get("product")

        if not product:
            print("Firecrawl 没有返回 product")
            print(
                "warning: No product found on this page; "
                "it does not appear to be a product page."
            )
            return None

        return product

    except Exception as e:
        print(f"Firecrawl 请求异常: {e}")
        return None


# =========================================================
# 数据读取
# =========================================================

def get_amount(value):
    """
    兼容：

    199.99
    {"amount": 199.99}
    {"value": 199.99}
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, dict):
        for key in ("amount", "value", "price"):
            if key in value:
                try:
                    return float(value[key])
                except Exception:
                    pass

    return None


def get_price(variant):
    return get_amount(
        variant.get("price")
    )


def get_original_price(variant):
    sale = variant.get("sale")

    if not isinstance(sale, dict):
        return None

    return get_amount(
        sale.get("originalPrice")
    )


def get_currency(variant):
    price = variant.get("price")

    if isinstance(price, dict):
        currency = price.get("currency")

        if currency:
            return str(currency)

    return "USD"


def get_values(variant):
    values = variant.get("values")

    if isinstance(values, dict):
        return values

    return {}


def get_color(variant):
    values = get_values(variant)

    for key in (
        "color",
        "Color",
        "colour",
        "Colour",
    ):
        value = values.get(key)

        if value:
            return str(value)

    return "未知颜色"


def get_size(variant):
    values = get_values(variant)

    for key in (
        "size",
        "Size",
        "尺码",
    ):
        value = values.get(key)

        if value:
            return str(value)

    return "未知尺码"


def is_in_stock(variant):
    availability = variant.get("availability")

    if isinstance(availability, dict):
        if "inStock" in availability:
            return bool(
                availability["inStock"]
            )

    if isinstance(availability, bool):
        return availability

    if isinstance(availability, str):
        text = availability.lower()

        if "out" in text:
            return False

        if "in stock" in text:
            return True

        if "instock" in text:
            return True

    # 如果 Firecrawl 没给库存状态，
    # 但商品有价格，默认暂时视为有货
    return True


# =========================================================
# 变体唯一 ID
# =========================================================

def make_variant_key(variant):
    """
    优先使用 Firecrawl 给出的 SKU / ID。

    如果没有，则：

    颜色 + 尺码 + 当前价格

    组合成稳定的变体键。
    """

    for key in (
        "sku",
        "id",
        "variantId",
        "variant_id",
    ):
        value = variant.get(key)

        if value:
            return f"id:{value}"

    color = get_color(variant)
    size = get_size(variant)

    return f"{color}|{size}"


# =========================================================
# 折扣
# =========================================================

def calculate_discount(original, current):
    if original is None:
        return None

    if current is None:
        return None

    if original <= 0:
        return None

    if current >= original:
        return 0.0

    return round(
        (original - current) / original * 100,
        1
    )


# =========================================================
# 价格显示
# =========================================================

def money(value):
    if value is None:
        return "-"

    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))}"

    return f"{value:.2f}"


def currency_symbol(currency):
    symbols = {
        "USD": "$",
        "CAD": "C$",
        "DKK": "kr",
        "JPY": "¥",
        "EUR": "€",
        "GBP": "£",
    }

    return symbols.get(
        currency,
        currency + " "
    )


# =========================================================
# 构建 Telegram 推送
# =========================================================

def build_alert(
    product_name,
    product_url,
    alert_variants
):
    """
    alert_variants:

    [
        {
            original,
            current,
            currency,
            color,
            size,
            in_stock
        }
    ]

    按：

    原价 + 当前价 + 货币

    分成不同价格档。

    同一个价格档里面，
    不同颜色横向排列。
    """

    groups = defaultdict(list)

    for item in alert_variants:
        key = (
            item["original"],
            item["current"],
            item["currency"],
        )

        groups[key].append(item)

    blocks = []

    # 折扣最高的价格档放前面
    sorted_groups = sorted(
        groups.items(),
        key=lambda x: (
            calculate_discount(
                x[0][0],
                x[0][1]
            ) or 0
        ),
        reverse=True
    )

    for (
        original,
        current,
        currency
    ), items in sorted_groups:

        discount = calculate_discount(
            original,
            current
        )

        symbol = currency_symbol(currency)

        # ---------------------------------------------
        # 按颜色整理
        # ---------------------------------------------

        color_data = defaultdict(set)

        for item in items:
            color = item["color"]
            size = item["size"]

            if size and size != "未知尺码":
                color_data[color].add(size)

        colors = list(color_data.keys())

        if not colors:
            colors = ["未知颜色"]

        # ---------------------------------------------
        # 标题
        # ---------------------------------------------

        if discount is not None:
            if discount >= 50:
                emoji = "🔥"
            elif discount >= 30:
                emoji = "🔥"
            else:
                emoji = "🏷️"

            title = (
                f"{emoji} {discount:.0f}% OFF｜"
                f"{product_name}"
            )
        else:
            title = product_name

        lines = [
            title,
            (
                f"🏷️ 原价 {symbol}{money(original)}"
                f"｜💰 现价 {symbol}{money(current)}"
            ),
            "",
        ]

        # ---------------------------------------------
        # 颜色横向排列
        # ---------------------------------------------

        lines.append(
            "颜色       " +
            "       ".join(colors)
        )

        # ---------------------------------------------
        # 尺码
        # ---------------------------------------------

        size_parts = []

        for color in colors:
            sizes = sorted(
                color_data.get(color, set())
            )

            if sizes:
                size_text = " ".join(sizes)
            else:
                size_text = "-"

            size_parts.append(size_text)

        lines.append(
            "尺码       " +
            "       ".join(size_parts)
        )

        # ---------------------------------------------
        # 库存
        # ---------------------------------------------

        stock_parts = []

        for color in colors:
            color_items = [
                x
                for x in items
                if x["color"] == color
            ]

            if any(
                x["in_stock"]
                for x in color_items
            ):
                stock_text = "有货"
            else:
                stock_text = "无货"

            stock_parts.append(stock_text)

        lines.append(
            "库存       " +
            "       ".join(stock_parts)
        )

        lines.append("")
        lines.append("━━━━━━━━━━━━")
        lines.append("")
        lines.append(product_url)

        blocks.append(
            "\n".join(lines)
        )

    return "\n".join(blocks)


# =========================================================
# Telegram
# =========================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("没有 TELEGRAM_BOT_TOKEN")
        return False

    if not TELEGRAM_CHAT_ID:
        print("没有 TELEGRAM_CHAT_ID")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        if response.status_code == 200:
            print("Telegram 推送成功")
            return True

        print(
            "Telegram 推送失败:",
            response.status_code,
            response.text[:500]
        )

        return False

    except Exception as e:
        print(f"Telegram 异常: {e}")
        return False


# =========================================================
# 单个商品处理
# =========================================================

def process_product(product, history):
    name = product["name"]
    url = product["url"]

    print()
    print(f"[商品] {name}")

    data = firecrawl_product(url)

    if not data:
        print("没有获取到商品数据")
        return

    product_name = data.get(
        "title"
    ) or data.get(
        "name"
    ) or name

    print(
        f"商品名称: {product_name}"
    )

    variants = data.get("variants")

    if not isinstance(variants, list):
        print("没有找到 variants")
        return

    print(
        f"发现变体: {len(variants)}"
    )

    # ---------------------------------------------
    # 商品历史
    # ---------------------------------------------

    products_history = history["products"]

    if name not in products_history:
        products_history[name] = {
            "url": url,
            "variants": {}
        }

    product_history = products_history[name]

    if "variants" not in product_history:
        product_history["variants"] = {}

    old_variants = product_history["variants"]

    alert_variants = []

    valid_price_count = 0
    discounted_count = 0

    # ---------------------------------------------
    # 遍历所有变体
    # ---------------------------------------------

    for variant in variants:

        current = get_price(variant)

        if current is None:
            continue

        valid_price_count += 1

        original = get_original_price(
            variant
        )

        currency = get_currency(
            variant
        )

        color = get_color(
            variant
        )

        size = get_size(
            variant
        )

        in_stock = is_in_stock(
            variant
        )

        variant_key = make_variant_key(
            variant
        )

        # 当前折扣
        discount = calculate_discount(
            original,
            current
        )

        if (
            discount is not None
            and discount >= MIN_DISCOUNT
        ):
            discounted_count += 1

        # -----------------------------------------
        # 上一次记录
        # -----------------------------------------

        previous = old_variants.get(
            variant_key
        )

        previous_price = None

        if isinstance(previous, dict):
            previous_price = get_amount(
                previous.get("price")
            )

        # -----------------------------------------
        # 核心规则
        #
        # 当前实际售价 < 上一次实际售价
        #
        # 并且当前折扣 >= 20%
        # -----------------------------------------

        price_dropped = (
            previous_price is not None
            and current < previous_price
        )

        discount_ok = (
            discount is not None
            and discount >= MIN_DISCOUNT
        )

        should_alert = (
            price_dropped
            and discount_ok
        )

        if should_alert:
            print(
                f"发现降价: "
                f"{previous_price} -> {current}"
            )

            alert_variants.append(
                {
                    "original": original,
                    "current": current,
                    "currency": currency,
                    "color": color,
                    "size": size,
                    "in_stock": in_stock,
                }
            )

        # -----------------------------------------
        # 无论是否打折，
        # 都保存当前实际价格
        # -----------------------------------------

        old_variants[variant_key] = {
            "price": current,
            "original_price": original,
            "currency": currency,
            "color": color,
            "size": size,
            "in_stock": in_stock,
            "updated_at": int(time.time()),
        }

    # ---------------------------------------------
    # 日志
    # ---------------------------------------------

    print(
        f"有效价格变体: {valid_price_count}"
    )

    print(
        f"当前折扣变体: {discounted_count}"
    )

    # ---------------------------------------------
    # 推送
    # ---------------------------------------------

    if not alert_variants:
        print("没有价格下降")
        return

    message = build_alert(
        product_name,
        url,
        alert_variants
    )

    send_telegram(message)


# =========================================================
# 主程序
# =========================================================

def main():

    if not FIRECRAWL_API_KEY:
        print("错误：FIRECRAWL_API_KEY 未设置")
        return

    if not TELEGRAM_BOT_TOKEN:
        print("错误：TELEGRAM_BOT_TOKEN 未设置")
        return

    if not TELEGRAM_CHAT_ID:
        print("错误：TELEGRAM_CHAT_ID 未设置")
        return

    history = load_history()

    total = len(PRODUCTS)

    position = int(
        history.get("position", 0)
    )

    # 防止越界
    if position >= total:
        position = 0

    end = min(
        position + BATCH_SIZE,
        total
    )

    current_products = PRODUCTS[
        position:end
    ]

    # 如果到了最后，从头开始
    next_position = end

    if next_position >= total:
        next_position = 0

    print(
        f"轮询位置: "
        f"{position} -> {next_position}"
    )

    print(
        f"本轮抓取详情: "
        f"{len(current_products)}"
    )

    # ---------------------------------------------
    # 抓取
    # ---------------------------------------------

    for index, product in enumerate(
        current_products,
        start=1
    ):

        print()
        print(
            f"[{index}/{len(current_products)}] "
            f"{product['name']}"
        )

        try:
            process_product(
                product,
                history
            )

        except Exception as e:
            # 一个商品出错，
            # 不影响其他商品
            print(
                f"商品处理异常: {e}"
            )

        # 避免 Firecrawl 请求过快
        if index < len(current_products):
            time.sleep(
                REQUEST_INTERVAL
            )

    # ---------------------------------------------
    # 保存轮询位置
    # ---------------------------------------------

    history["position"] = next_position

    save_history(history)

    print()
    print("本轮完成")


if __name__ == "__main__":
    main()
