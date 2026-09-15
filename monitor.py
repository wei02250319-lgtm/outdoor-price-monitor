import os
import re
import json
import time
import html
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# =========================
# 基础配置
# =========================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

HISTORY_FILE = "data/prices.json"

# 美元 -> 人民币
USD_CNY = 7.15

# =========================
# 最终监控清单
# 共 8 个
# C1 已删除
# =========================

WATCHLIST = [
    (
        "Arc'teryx Gamma MX Hoody - Men's",
        "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens",
    ),
    (
        "Arc'teryx Gamma Jacket - Men's",
        "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens",
    ),
    (
        "Arc'teryx Gamma Pants - Men's",
        "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens",
    ),
    (
        "Patagonia R2 TechFace Jacket - Men's",
        "https://www.rei.com/product/222148/patagonia-r2-techface-jacket-mens",
    ),
    (
        "Patagonia R2 TechFace Hoody - Men's",
        "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
    ),
    (
        "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
    ),
    (
        "Arc'teryx Atom Insulated Jacket - Men's",
        "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
    ),
    (
        "Arc'teryx Atom Insulated Hoody - Men's",
        "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
    ),
]

# =========================
# REI 列表页
# =========================

LISTING_PAGES = [
    (
        "Arc'teryx",
        "https://www.rei.com/b/arcteryx/c/all",
    ),
    (
        "Patagonia",
        "https://www.rei.com/b/patagonia/c/all",
    ),
    (
        "The North Face",
        "https://www.rei.com/b/the-north-face/c/all",
    ),
]

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 Chrome/128 Safari/537.36"
        )
    }
)


# =========================
# 工具函数
# =========================

def money(value):
    try:
        return float(
            str(value)
            .replace("$", "")
            .replace(",", "")
            .strip()
        )
    except Exception:
        return None


def discount_percent(original, current):
    if (
        original is not None
        and current is not None
        and original > 0
        and current < original
    ):
        return round((1 - current / original) * 100)

    return 0


def normalize_url(url):
    if not url:
        return ""

    url = html.unescape(url)

    if url.startswith("/"):
        url = urljoin("https://www.rei.com", url)

    return url.split("?")[0].rstrip("/")


# =========================
# Firecrawl
# =========================

def firecrawl_scrape(url):
    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")
        return None

    payload = {
        "url": url,
        "formats": [
            "markdown",
            "rawHtml",
        ],
        "onlyMainContent": False,
        "waitFor": 2000,
    }

    try:
        response = session.post(
            FIRECRAWL_URL,
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )

        print("Firecrawl:", response.status_code, url)

        if response.status_code != 200:
            print(response.text[:500])
            return None

        result = response.json()

        return result.get("data", result)

    except Exception as e:
        print("Firecrawl异常:", e)
        return None


# =========================
# 列表页测试
# =========================

def discover_links():
    total = 0

    for brand, url in LISTING_PAGES:

        print()
        print("抓取列表:", brand)

        data = firecrawl_scrape(url)

        if not data:
            continue

        markdown = data.get("markdown", "") or ""
        raw_html = data.get("rawHtml", "") or ""

        found = set()

        for text in (markdown, raw_html):

            urls = re.findall(
                r'https?://www\.rei\.com/product/[^\s)"<>]+',
                text,
            )

            for item in urls:
                found.add(normalize_url(item))

            hrefs = re.findall(
                r'href=["\']([^"\']*?/product/[^"\']+)["\']',
                text,
                re.I,
            )

            for item in hrefs:
                found.add(normalize_url(item))

        count = min(len(found), 25)

        print("发现商品:", count)

        total += count

    return total


# =========================
# JSON 递归解析
# =========================

def parse_json_objects(obj, output):

    if isinstance(obj, dict):

        if any(
            key in obj
            for key in (
                "price",
                "salePrice",
                "currentPrice",
                "availability",
            )
        ):
            output.append(obj)

        for value in obj.values():
            parse_json_objects(value, output)

    elif isinstance(obj, list):

        for value in obj:
            parse_json_objects(value, output)


# =========================
# 提取网页 JSON
# =========================

def extract_json_candidates(raw_html):

    candidates = []

    soup = BeautifulSoup(
        raw_html or "",
        "html.parser",
    )

    # JSON-LD
    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):

        try:

            content = script.string or script.get_text()

            if not content:
                continue

            obj = json.loads(content)

            parse_json_objects(
                obj,
                candidates,
            )

        except Exception:
            pass

    # 页面内部 JSON
    for script in soup.find_all("script"):

        text = script.string or script.get_text()

        if not text:
            continue

        if len(text) > 2_000_000:
            continue

        if not any(
            word in text
            for word in (
                "salePrice",
                "currentPrice",
                "variants",
                "availability",
                "sku",
            )
        ):
            continue

        stripped = text.strip()

        if not (
            stripped.startswith("{")
            or stripped.startswith("[")
        ):
            continue

        try:

            obj = json.loads(stripped)

            parse_json_objects(
                obj,
                candidates,
            )

        except Exception:
            pass

    return candidates


# =========================
# 变体解析
# =========================

def parse_variant_records(
    raw_html,
    markdown,
    fallback_name,
):

    records = []

    candidates = extract_json_candidates(
        raw_html
    )

    for obj in candidates:

        price = None
        original = None

        for key in (
            "salePrice",
            "currentPrice",
            "price",
        ):

            if key in obj:

                price = money(
                    obj.get(key)
                )

                if price is not None:
                    break

        for key in (
            "originalPrice",
            "regularPrice",
            "listPrice",
            "compareAtPrice",
        ):

            if key in obj:

                original = money(
                    obj.get(key)
                )

                if original is not None:
                    break

        if price is None:
            continue

        if original is None:
            original = price

        color = ""
        size = ""

        # 颜色
        for key in (
            "color",
            "colorName",
            "colour",
        ):

            if obj.get(key):

                color = str(
                    obj.get(key)
                ).strip()

                break

        # 尺码
        for key in (
            "size",
            "sizeName",
        ):

            if obj.get(key):

                size = str(
                    obj.get(key)
                ).strip()

                break

        # options
        for key in (
            "options",
            "optionValues",
            "selectedOptions",
            "attributes",
        ):

            value = obj.get(key)

            if isinstance(value, dict):

                for option_key, option_value in value.items():

                    option_key_lower = (
                        str(option_key).lower()
                    )

                    if (
                        not color
                        and "color" in option_key_lower
                    ):
                        color = str(
                            option_value
                        ).strip()

                    if (
                        not size
                        and "size" in option_key_lower
                    ):
                        size = str(
                            option_value
                        ).strip()

            elif isinstance(value, list):

                for item in value:

                    if not isinstance(item, dict):
                        continue

                    option_name = str(
                        item.get("name")
                        or item.get("key")
                        or ""
                    )

                    option_value = str(
                        item.get("value")
                        or item.get("label")
                        or ""
                    )

                    name_lower = option_name.lower()

                    if (
                        not color
                        and "color" in name_lower
                    ):
                        color = option_value.strip()

                    if (
                        not size
                        and "size" in name_lower
                    ):
                        size = option_value.strip()

        # 库存
        available = obj.get("available")

        if available is None:

            availability = str(
                obj.get(
                    "availability",
                    "",
                )
            ).lower()

            available = not any(
                word in availability
                for word in (
                    "outofstock",
                    "out of stock",
                    "unavailable",
                )
            )

        records.append(
            {
                "price": price,
                "original": original,
                "color": color or "默认颜色",
                "size": size or "—",
                "stock": (
                    "有货"
                    if available
                    else "无货"
                ),
            }
        )

    # 去重
    unique = {}

    for item in records:

        key = (
            item["price"],
            item["original"],
            item["color"],
            item["size"],
            item["stock"],
        )

        unique[key] = item

    return list(unique.values())


# =========================
# Markdown 价格备用解析
# =========================

def parse_markdown_price(markdown):

    prices = []

    pattern = (
        r'\$(\d+(?:\.\d{1,2})?)'
        r'\s+Compared to\s+'
        r'\$(\d+(?:\.\d{1,2})?)'
    )

    for match in re.finditer(
        pattern,
        markdown or "",
        re.I,
    ):

        prices.append(
            (
                float(match.group(1)),
                float(match.group(2)),
            )
        )

    return prices


# =========================
# 商品解析
# =========================

def parse_product(
    data,
    expected_name,
    url,
):

    if not data:
        return None

    markdown = data.get(
        "markdown",
        "",
    ) or ""

    raw_html = data.get(
        "rawHtml",
        "",
    ) or ""

    name = expected_name

    title_match = re.search(
        r'(?im)^\s*#\s+(.+?)\s*$',
        markdown,
    )

    if title_match:

        candidate = re.sub(
            r"\s+",
            " ",
            title_match.group(1),
        ).strip()

        if len(candidate) < 180:
            name = candidate

    variants = parse_variant_records(
        raw_html,
        markdown,
        name,
    )

    # 解析失败时使用 Markdown 价格
    if not variants:

        prices = parse_markdown_price(
            markdown
        )

        for current, original in prices:

            variants.append(
                {
                    "price": current,
                    "original": (
                        original
                        or current
                    ),
                    "color": "默认颜色",
                    "size": "—",
                    "stock": "有货",
                }
            )

    if not variants:

        return {
            "name": name,
            "url": url,
            "tiers": [],
            "lowest_sale": None,
        }

    # 只保留真正降价的 SKU
    sale_variants = [
        item
        for item in variants
        if (
            item["original"] is not None
            and item["price"] < item["original"]
        )
    ]

    # 价格层级
    tiers = {}

    for item in sale_variants:

        key = (
            round(item["price"], 2),
            round(item["original"], 2),
        )

        tiers.setdefault(
            key,
            [],
        ).append(item)

    tier_list = []

    for (
        price,
        original,
    ), items in sorted(
        tiers.items(),
        key=lambda x: x[0][0],
    ):

        discount = discount_percent(
            original,
            price,
        )

        tier_list.append(
            {
                "price": price,
                "original": original,
                "discount": discount,
                "variants": items,
            }
        )

    lowest_sale = min(
        (
            item["price"]
            for item in sale_variants
        ),
        default=None,
    )

    return {
        "name": name,
        "url": url,
        "tiers": tier_list,
        "lowest_sale": lowest_sale,
    }


# =========================
# 历史价格
# =========================

def load_history():

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            return json.load(file)

    except Exception:

        return {}


def save_history(history):

    os.makedirs(
        os.path.dirname(HISTORY_FILE),
        exist_ok=True,
    )

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            history,
            file,
            ensure_ascii=False,
            indent=2,
        )


# =========================
# Telegram
# =========================

def send_telegram(text):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print("未配置 Telegram")

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": False,
            },
            timeout=30,
        )

        print(
            "Telegram:",
            response.status_code,
        )

        return response.ok

    except Exception as e:

        print(
            "Telegram异常:",
            e,
        )

        return False


# =========================
# Telegram 格式
# =========================

def format_tier(
    tier,
    product_name,
):

    discount = tier["discount"]

    if discount >= 50:
        icon = "🔥"
    elif discount >= 30:
        icon = "⚡"
    else:
        icon = "🏷️"

    price = tier["price"]
    original = tier["original"]

    lines = []

    lines.append(
        f"{icon} {discount}% OFF｜{product_name}"
    )

    lines.append(
        f"🏷️ 原价 ${original:.2f}"
        f"（¥{original * USD_CNY:.0f}）"
        f"｜💰 现价 ${price:.2f}"
        f"（¥{price * USD_CNY:.0f}）"
    )

    by_color = {}

    for variant in tier["variants"]:

        color = variant["color"]

        by_color.setdefault(
            color,
            [],
        ).append(variant)

    colors = list(
        by_color.keys()
    )

    if colors:

        lines.append("")

        lines.append(
            "颜色\t"
            + "\t".join(colors)
        )

        size_cells = []
        stock_cells = []

        for color in colors:

            items = by_color[color]

            sizes = []
            stocks = []

            for item in items:

                if item["size"] not in sizes:
                    sizes.append(
                        item["size"]
                    )

                if item["stock"] not in stocks:
                    stocks.append(
                        item["stock"]
                    )

            size_cells.append(
                " ".join(sizes)
            )

            stock_cells.append(
                "/".join(stocks)
            )

        lines.append(
            "尺码\t"
            + "\t".join(size_cells)
        )

        lines.append(
            "库存\t"
            + "\t".join(stock_cells)
        )

    lines.append("")

    lines.append(
        "━━━━━━━━━━━━"
    )

    return "\n".join(lines)


# =========================
# 主程序
# =========================

def main():

    print(
        """
======================================
REI Outdoor Price Monitor
8个重点商品｜轮询｜只推送降价
======================================
"""
    )

    discover_links()

    history = load_history()

    print()
    print(
        "重点商品:",
        len(WATCHLIST),
    )

    for index, (_, url) in enumerate(
        WATCHLIST,
        1,
    ):

        print(
            f"  {index}. {url}"
        )

    # 每次只抓 3 个
    batch_size = 3

    state = history.get(
        "_state",
        {},
    )

    position = int(
        state.get(
            "position",
            0,
        )
    ) % len(WATCHLIST)

    indexes = [
        (
            position + i
        ) % len(WATCHLIST)
        for i in range(batch_size)
    ]

    print()
    print(
        f"轮询位置: {position} -> {indexes[-1]}"
    )

    print(
        "本轮抓取详情:",
        len(indexes),
    )

    alerts = []

    for number, index in enumerate(
        indexes,
        1,
    ):

        expected_name, url = WATCHLIST[index]

        print()
        print(
            f"[{number}/{len(indexes)}]"
        )

        print(url)

        data = firecrawl_scrape(url)

        product = parse_product(
            data,
            expected_name,
            url,
        )

        if not product:

            print("抓取失败")

        else:

            print(
                "商品名称:",
                product["name"],
            )

            print(
                "发现折扣价格层级:",
                len(product["tiers"]),
            )

            for tier in product["tiers"]:

                print(
                    f'  原价 ${tier["original"]:.2f}'
                    f' -> 现价 ${tier["price"]:.2f}'
                    f' ({tier["discount"]}%)'
                )

            old_data = history.get(
                url,
                {},
            )

            old_lowest = old_data.get(
                "lowest_sale"
            )

            current_lowest = product[
                "lowest_sale"
            ]

            # 第一次看到商品
            if old_lowest is None:

                if current_lowest is not None:

                    print(
                        "首次记录价格，"
                        "建立基线，不推送"
                    )

            # 只有降价才推送
            elif (
                current_lowest is not None
                and current_lowest < old_lowest
            ):

                print(
                    f"发现降价："
                    f"${old_lowest:.2f}"
                    f" -> "
                    f"${current_lowest:.2f}"
                )

                qualifying = []

                for tier in product["tiers"]:

                    # 20%以上才推送
                    if tier["discount"] >= 20:

                        qualifying.append(
                            tier
                        )

                if qualifying:

                    alerts.append(
                        (
                            product,
                            qualifying,
                        )
                    )

            elif current_lowest is not None:

                print(
                    f"价格没有下降："
                    f"${current_lowest:.2f}"
                    f" -> "
                    f"${current_lowest:.2f}"
                )

            else:

                print(
                    "没有发现折扣商品"
                )

            history[url] = {
                "name": product["name"],
                "lowest_sale": current_lowest,
                "updated_at": int(
                    time.time()
                ),
            }

        # Firecrawl 限速保护
        if number < len(indexes):

            print(
                "等待 9 秒..."
            )

            time.sleep(9)

    # 下一轮从下一个位置开始
    state["position"] = (
        position + batch_size
    ) % len(WATCHLIST)

    history["_state"] = state

    save_history(history)

    # =========================
    # Telegram 推送
    # =========================

    if alerts:

        for product, tiers in alerts:

            message_parts = []

            for tier in tiers:

                message_parts.append(
                    format_tier(
                        tier,
                        product["name"],
                    )
                )

            # 只保留直接商品链接
            message_parts.append(
                product["url"]
            )

            message = "\n".join(
                message_parts
            )

            send_telegram(message)

            print(
                "已发送 Telegram 降价提醒"
            )

    else:

        print(
            "\n本轮没有需要推送的降价。"
        )

    print()
    print(
        "本轮价格历史已保存。"
    )

    print(
        "======================================"
    )

    print(
        "运行完成"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
