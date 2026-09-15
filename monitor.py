import os
import json
import time
import requests
from pathlib import Path
from collections import defaultdict

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = Path("data/prices.json")
USD_TO_CNY = 7.15

# 每30分钟运行一次，每次检查3个商品
DETAILS_PER_RUN = 3

WATCHLIST = [
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
        "name": "Patagonia R2 TechFace Hoody - Men's",
        "url": "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
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


def load_history():
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not HISTORY_FILE.exists():
        return {
            "rotation": 0,
            "variants": {}
        }

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

        if "variants" not in data:
            data["variants"] = {}

        if "rotation" not in data:
            data["rotation"] = 0

        return data

    except Exception:
        return {
            "rotation": 0,
            "variants": {}
        }


def save_history(data):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def firecrawl_product(url):
    endpoint = "https://api.firecrawl.dev/v2/scrape"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
    }

    payload = {
        "url": url,
        "formats": ["product"],
        "waitFor": 3000,
    }

    response = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=120,
    )

    print(f"Firecrawl: {response.status_code}")

    if response.status_code != 200:
        print(response.text[:1000])
        return None

    try:
        result = response.json()
    except Exception:
        print("Firecrawl 返回不是 JSON")
        return None

    if not result.get("success"):
        print("Firecrawl success=false")
        return None

    data = result.get("data", {})
    product = data.get("product")

    if not product:
        print("Firecrawl 没有返回 product")
        warning = data.get("warning")
        if warning:
            print("warning:", warning)
        return None

    return product


def money(value):
    try:
        return float(value)
    except Exception:
        return None


def get_price(obj):
    if not isinstance(obj, dict):
        return None

    value = obj.get("amount")

    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def get_currency(obj):
    if not isinstance(obj, dict):
        return "USD"

    return obj.get("currency") or "USD"


def format_money(value, currency="USD"):
    if value is None:
        return "-"

    if currency == "USD":
        return f"${value:.2f}"

    return f"{currency} {value:.2f}"


def cny(value, currency="USD"):
    if value is None:
        return None

    if currency == "USD":
        return value * USD_TO_CNY

    return None


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def get_color(variant):
    values = variant.get("values") or {}

    if not isinstance(values, dict):
        return "未知颜色"

    for key in ["color", "Color", "colour", "Colour"]:
        if key in values and values[key]:
            return clean_text(values[key])

    # REI 某些页面可能把颜色放在variant标题
    title = clean_text(variant.get("title"))

    if "—" in title:
        parts = title.split("—")
        if len(parts) >= 2:
            return parts[-1].strip()

    if "-" in title:
        parts = title.split("-")
        if len(parts) >= 2:
            return parts[-1].strip()

    return "未知颜色"


def get_size(variant):
    values = variant.get("values") or {}

    if not isinstance(values, dict):
        return "均码"

    for key in ["size", "Size", "尺码"]:
        if key in values and values[key]:
            return clean_text(values[key])

    return "均码"


def is_in_stock(variant):
    availability = variant.get("availability") or {}

    if isinstance(availability, dict):
        if availability.get("inStock") is True:
            return True

        if availability.get("inStock") is False:
            return False

        text = clean_text(availability.get("text")).lower()

        if any(x in text for x in [
            "out of stock",
            "sold out",
            "unavailable",
            "not available"
        ]):
            return False

        if any(x in text for x in [
            "in stock",
            "available"
        ]):
            return True

    return None


def make_variant_key(product_url, variant):
    sku = clean_text(variant.get("sku"))

    if sku:
        return f"{product_url}|sku:{sku}"

    variant_id = clean_text(variant.get("id"))

    if variant_id:
        return f"{product_url}|id:{variant_id}"

    color = get_color(variant)
    size = get_size(variant)

    return f"{product_url}|{color}|{size}"


def calculate_discount(original, current):
    if not original or not current:
        return None

    if original <= current:
        return 0

    return round((original - current) / original * 100)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram 环境变量没有配置")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print("Telegram:", response.status_code)

    except Exception as e:
        print("Telegram 发送失败:", e)


def build_alert(product_name, product_url, tiers):
    """
    tiers:
    {
        original,
        current,
        discount,
        currency,
        colors: {
            color: {
                sizes: [],
                stock: []
            }
        }
    }
    """

    lines = []

    for tier in sorted(
        tiers,
        key=lambda x: x["discount"],
        reverse=True
    ):

        discount = tier["discount"]
        original = tier["original"]
        current = tier["current"]
        currency = tier["currency"]

        if discount >= 50:
            emoji = "🔥"
        elif discount >= 30:
            emoji = "⚡"
        else:
            emoji = "🏷️"

        lines.append(
            f"{emoji} {discount}% OFF｜{product_name}"
        )

        original_text = format_money(
            original,
            currency
        )

        current_text = format_money(
            current,
            currency
        )

        original_cny = cny(original, currency)
        current_cny = cny(current, currency)

        if original_cny is not None:
            lines.append(
                f"🏷️ 原价 {original_text} "
                f"(≈¥{original_cny:.0f})"
            )

        if current_cny is not None:
            lines.append(
                f"💰 现价 {current_text} "
                f"(≈¥{current_cny:.0f})"
            )
        else:
            lines.append(
                f"💰 现价 {current_text}"
            )

        colors = tier["colors"]

        if colors:

            color_names = list(colors.keys())

            lines.append("")
            lines.append(
                "颜色    " +
                "    ".join(color_names)
            )

            size_parts = []

            for color in color_names:
                sizes = colors[color]["sizes"]

                if sizes:
                    size_parts.append(
                        "/".join(sizes)
                    )
                else:
                    size_parts.append("-")

            lines.append(
                "尺码    " +
                "    ".join(size_parts)
            )

            stock_parts = []

            for color in color_names:

                stocks = colors[color]["stock"]

                if any(stocks):
                    stock_parts.append("有货")
                elif stocks:
                    stock_parts.append("无货")
                else:
                    stock_parts.append("-")

            lines.append(
                "库存    " +
                "    ".join(stock_parts)
            )

        lines.append("")
        lines.append(product_url)
        lines.append("")
        lines.append("━━━━━━━━━━━━")
        lines.append("")

    return "\n".join(lines).strip()


def process_product(item, history):
    product_name = item["name"]
    product_url = item["url"]

    print()
    print(f"[商品] {product_name}")

    product = firecrawl_product(product_url)

    if not product:
        print("没有获取到商品数据")
        return

    actual_name = clean_text(
        product.get("title")
    ) or product_name

    print("商品名称:", actual_name)

    variants = product.get("variants") or []

    if not variants:
        print("没有发现商品变体")
        return

    print("发现变体:", len(variants))

    alert_variants = []

    for variant in variants:

        current = get_price(
            variant.get("price")
        )

        sale = variant.get("sale") or {}

        original = get_price(
            sale.get("originalPrice")
        )

        currency = (
            get_currency(variant.get("price"))
        )

        # 没有明确原价，绝不自己猜
        if current is None or original is None:
            continue

        # 没有真正降价
        if original <= current:
            continue

        discount = calculate_discount(
            original,
            current
        )

        if discount is None or discount < 20:
            continue

        color = get_color(variant)
        size = get_size(variant)
        stock = is_in_stock(variant)

        key = make_variant_key(
            product_url,
            variant
        )

        previous = history["variants"].get(key)

        previous_price = None

        if isinstance(previous, dict):
            previous_price = money(
                previous.get("price")
            )

        # 第一次看到，只记录，不推送
        should_alert = False

        if previous_price is not None:
            # 只有真正降价才推
            if current < previous_price:
                should_alert = True

        if should_alert:
            alert_variants.append({
                "key": key,
                "original": original,
                "current": current,
                "discount": discount,
                "currency": currency,
                "color": color,
                "size": size,
                "stock": stock,
            })

        # 始终更新当前价格
        history["variants"][key] = {
            "product": actual_name,
            "url": product_url,
            "price": current,
            "original_price": original,
            "currency": currency,
            "color": color,
            "size": size,
            "stock": stock,
        }

    if not alert_variants:
        print("没有价格下降")
        return

    # 按折扣价格层级重新组合
    tier_map = {}

    for item in alert_variants:

        tier_key = (
            item["original"],
            item["current"],
            item["currency"]
        )

        if tier_key not in tier_map:
            tier_map[tier_key] = {
                "original": item["original"],
                "current": item["current"],
                "discount": item["discount"],
                "currency": item["currency"],
                "colors": {}
            }

        color = item["color"]

        if color not in tier_map[tier_key]["colors"]:
            tier_map[tier_key]["colors"][color] = {
                "sizes": [],
                "stock": []
            }

        if item["size"] not in tier_map[tier_key]["colors"][color]["sizes"]:
            tier_map[tier_key]["colors"][color]["sizes"].append(
                item["size"]
            )

        tier_map[tier_key]["colors"][color]["stock"].append(
            item["stock"]
        )

    tiers = list(tier_map.values())

    message = build_alert(
        actual_name,
        product_url,
        tiers
    )

    print()
    print("发现降价，发送 Telegram:")
    print(message)

    send_telegram(message)


def main():

    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")
        return

    history = load_history()

    total = len(WATCHLIST)

    start = int(history.get("rotation", 0))

    end = min(
        start + DETAILS_PER_RUN,
        total
    )

    selected = WATCHLIST[start:end]

    # 到末尾后下一轮从0开始
    next_rotation = end

    if next_rotation >= total:
        next_rotation = 0

    print(
        f"轮询位置: {start} -> {next_rotation}"
    )

    print(
        f"本轮抓取详情: {len(selected)}"
    )

    for index, item in enumerate(selected, 1):

        print()
        print(
            f"[{index}/{len(selected)}] "
            f"{item['name']}"
        )

        try:
            process_product(
                item,
                history
            )

        except Exception as e:
            print(
                "处理商品出现异常:",
                repr(e)
            )

        # 避免 Firecrawl 请求过快
        if index < len(selected):
            time.sleep(9)

    history["rotation"] = next_rotation

    save_history(history)

    print()
    print("本轮完成")


if __name__ == "__main__":
    main()
