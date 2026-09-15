import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup


# ============================================================
# 基本配置
# ============================================================

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

DATA_FILE = "data/prices.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USD_RMB = 7.20

MAX_PRODUCTS = 12

# 重点尺码
FOCUS_SIZES = ["M", "L", "XL"]


# ============================================================
# REI 品牌页
# ============================================================

REI_PAGES = [
    "https://www.rei.com/b/arcteryx/c/all",
    "https://www.rei.com/b/patagonia/c/all",
    "https://www.rei.com/b/the-north-face/c/all",
]


# ============================================================
# 重点商品
# ============================================================

WATCHLIST = [
    "Beta AR",
    "Beta Jacket",
    "Beta LT",

    "Gamma MX",
    "Gamma Jacket",
    "Gamma Pant",
    "Gamma Pants",

    "Atom Insulated Jacket",
    "Atom Insulated Hoody",
    "Atom Jacket",

    "R2 TechFace Jacket",
    "R2 TechFace Hoody",

    "C1",
    "Capilene Cool Daily Graphic Hoody",
]


# ============================================================
# Firecrawl
# ============================================================

def firecrawl(url, use_raw_html=True):
    """
    优先请求 markdown + rawHtml。

    markdown:
        用于找商品、名称、价格等。

    rawHtml:
        用于寻找真正的颜色 / 尺码 / 价格 / 库存变体数据。
    """

    try:
        formats = ["markdown"]

        if use_raw_html:
            formats.append("rawHtml")

        payload = {
            "url": url,
            "formats": formats,
        }

        r = requests.post(
            FIRECRAWL_URL,
            json=payload,
            timeout=120,
            headers={
                "Content-Type": "application/json",
                "Authorization": (
                    f"Bearer {os.getenv('FIRECRAWL_API_KEY')}"
                ),
            },
        )

        print("Firecrawl:", r.status_code, url)

        if r.status_code != 200:
            print(r.text[:500])
            return {
                "markdown": "",
                "raw_html": "",
            }

        data = r.json()

        result = data.get("data", data)

        markdown = (
            result.get("markdown")
            or ""
        )

        raw_html = (
            result.get("rawHtml")
            or result.get("raw_html")
            or ""
        )

        return {
            "markdown": markdown,
            "raw_html": raw_html,
        }

    except Exception as e:
        print("Firecrawl error:", e)

        return {
            "markdown": "",
            "raw_html": "",
        }


# ============================================================
# Telegram
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("缺少 TELEGRAM_BOT_TOKEN")
        return False

    if not TELEGRAM_CHAT_ID:
        print("缺少 TELEGRAM_CHAT_ID")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        r = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        print(
            "Telegram:",
            r.status_code
        )

        if r.status_code != 200:
            print(r.text[:500])

        return r.status_code == 200

    except Exception as e:

        print(
            "Telegram error:",
            e
        )

        return False


# ============================================================
# 历史数据
# ============================================================

def load_history():

    if not os.path.exists(DATA_FILE):
        return {}

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            "读取历史失败:",
            e
        )

        return {}


def save_history(data):

    directory = os.path.dirname(DATA_FILE)

    if directory:
        os.makedirs(
            directory,
            exist_ok=True
        )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# 商品链接
# ============================================================

def get_product_links(markdown):

    if not markdown:
        return []

    patterns = [
        r"https?://www\.rei\.com/product/\d+/[^\s\)\]\"<>]+",
        r"https?://www\.rei\.com/product/\d+",
    ]

    result = []

    for pattern in patterns:

        links = re.findall(
            pattern,
            markdown,
            re.I,
        )

        for url in links:

            url = html.unescape(url)

            url = url.rstrip(
                ".,;\"')]>"
            )

            if url not in result:
                result.append(url)

    return result


# ============================================================
# 商品名称
# ============================================================

def get_product_name(markdown, raw_html, url):

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    if raw_html:

        try:

            soup = BeautifulSoup(
                raw_html,
                "html.parser",
            )

            scripts = soup.find_all(
                "script",
                type="application/ld+json",
            )

            for script in scripts:

                text = script.string

                if not text:
                    continue

                try:

                    data = json.loads(text)

                except Exception:
                    continue

                objects = []

                if isinstance(data, dict):
                    objects.append(data)

                    if "@graph" in data:
                        graph = data["@graph"]

                        if isinstance(graph, list):
                            objects.extend(graph)

                elif isinstance(data, list):
                    objects.extend(data)

                for obj in objects:

                    if not isinstance(obj, dict):
                        continue

                    name = obj.get("name")

                    if (
                        name
                        and isinstance(name, str)
                        and len(name) < 200
                    ):
                        return name.strip()

        except Exception:
            pass

    # --------------------------------------------------------
    # Markdown 标题
    # --------------------------------------------------------

    if markdown:

        lines = markdown.splitlines()

        for line in lines:

            text = line.strip()

            if not text:
                continue

            text = re.sub(
                r"^#+\s*",
                "",
                text,
            )

            if len(text) > 150:
                continue

            lower = text.lower()

            if (
                "arc'teryx" in lower
                or "patagonia" in lower
                or "the north face" in lower
            ):
                return text

    # --------------------------------------------------------
    # URL 兜底
    # --------------------------------------------------------

    slug = url.rstrip("/").split("/")[-1]

    slug = re.sub(
        r"^\d+/",
        "",
        slug,
    )

    return slug.replace(
        "-",
        " ",
    ).title()


# ============================================================
# 价格
# ============================================================

def normalize_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):

        price = float(value)

    else:

        text = str(value)

        text = text.replace(
            ",",
            "",
        )

        match = re.search(
            r"([0-9]+(?:\.[0-9]{1,2})?)",
            text,
        )

        if not match:
            return None

        try:
            price = float(
                match.group(1)
            )

        except Exception:
            return None

    if price < 10:
        return None

    if price > 3000:
        return None

    return round(price, 2)


def extract_prices(text):

    if not text:
        return []

    result = []

    for m in re.finditer(
        r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
    ):

        price = normalize_price(
            m.group(1)
        )

        if price is not None:
            result.append(price)

    return sorted(
        set(result)
    )


# ============================================================
# 百分比
# ============================================================

def calculate_discount(
    original,
    sale,
):

    if not original:
        return 0

    if sale >= original:
        return 0

    return round(
        (original - sale)
        / original
        * 100
    )


# ============================================================
# 颜色标准化
# ============================================================

def normalize_color(value):

    if value is None:
        return ""

    text = str(value)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = text.strip()

    return text


# ============================================================
# 尺码标准化
# ============================================================

def normalize_size(value):

    if value is None:
        return ""

    text = str(value).strip()

    replacements = {
        "Medium": "M",
        "Large": "L",
        "Extra Large": "XL",
        "Extra-Large": "XL",
        "Small": "S",
        "Extra Small": "XS",
        "XX-Large": "XXL",
        "XX Large": "XXL",
    }

    return replacements.get(
        text,
        text,
    )


# ============================================================
# 库存判断
# ============================================================

def is_available(value):

    if value is None:
        return None

    text = str(value).lower()

    unavailable_words = [
        "outofstock",
        "out_of_stock",
        "out-of-stock",
        "soldout",
        "sold_out",
        "sold-out",
        "unavailable",
        "not available",
        "false",
    ]

    available_words = [
        "instock",
        "in_stock",
        "in-stock",
        "available",
        "true",
    ]

    for word in unavailable_words:

        if word in text:
            return False

    for word in available_words:

        if word in text:
            return True

    return None


# ============================================================
# 递归寻找 JSON
# ============================================================

def walk_json(obj):

    yield obj

    if isinstance(obj, dict):

        for value in obj.values():

            yield from walk_json(
                value
            )

    elif isinstance(obj, list):

        for item in obj:

            yield from walk_json(
                item
            )


# ============================================================
# 从 HTML 中提取 JSON
# ============================================================

def extract_embedded_json(raw_html):

    result = []

    if not raw_html:
        return result

    soup = BeautifulSoup(
        raw_html,
        "html.parser",
    )

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):

        text = script.string

        if not text:
            continue

        try:

            obj = json.loads(text)

            result.append(obj)

        except Exception:
            pass

    # --------------------------------------------------------
    # Next.js
    # --------------------------------------------------------

    for script in soup.find_all(
        "script"
    ):

        script_id = script.get(
            "id",
            "",
        )

        if script_id == "__NEXT_DATA__":

            text = script.string

            if text:

                try:

                    result.append(
                        json.loads(text)
                    )

                except Exception:
                    pass

    # --------------------------------------------------------
    # 常见 JSON 数据脚本
    # --------------------------------------------------------

    for script in soup.find_all(
        "script"
    ):

        text = script.string

        if not text:
            continue

        lower = text.lower()

        keywords = [
            "variants",
            "sku",
            "availability",
            "price",
            "color",
            "size",
        ]

        if not any(
            k in lower
            for k in keywords
        ):
            continue

        # 尝试直接解析
        try:

            obj = json.loads(text)

            result.append(
                obj
            )

        except Exception:
            pass

    return result


# ============================================================
# 判断一个字典是不是变体
# ============================================================

def looks_like_variant(obj):

    if not isinstance(obj, dict):
        return False

    keys = {
        str(k).lower()
        for k in obj.keys()
    }

    signals = [
        "sku",
        "price",
        "saleprice",
        "sale_price",
        "color",
        "size",
        "availability",
        "inventory",
    ]

    score = 0

    for signal in signals:

        if signal in keys:
            score += 1

    return score >= 2


# ============================================================
# 获取字段
# ============================================================

def get_first_value(
    obj,
    names,
):

    if not isinstance(obj, dict):
        return None

    lower_map = {
        str(k).lower(): k
        for k in obj.keys()
    }

    for name in names:

        key = lower_map.get(
            name.lower()
        )

        if key is not None:

            value = obj.get(key)

            if value is not None:
                return value

    return None


# ============================================================
# 从一个 JSON 对象提取变体
# ============================================================

def parse_variant_object(obj):

    if not isinstance(obj, dict):
        return None

    if not looks_like_variant(obj):
        return None

    # --------------------------------------------------------
    # 价格
    # --------------------------------------------------------

    sale_price = get_first_value(
        obj,
        [
            "salePrice",
            "sale_price",
            "sale",
            "currentPrice",
            "current_price",
            "sellingPrice",
            "selling_price",
        ],
    )

    price = get_first_value(
        obj,
        [
            "price",
            "unitPrice",
            "unit_price",
        ],
    )

    original_price = get_first_value(
        obj,
        [
            "originalPrice",
            "original_price",
            "listPrice",
            "list_price",
            "regularPrice",
            "regular_price",
            "compareAtPrice",
            "compare_at_price",
        ],
    )

    sale_price = normalize_price(
        sale_price
    )

    price = normalize_price(
        price
    )

    original_price = normalize_price(
        original_price
    )

    # --------------------------------------------------------
    # 如果同时有 salePrice + price
    # --------------------------------------------------------

    if sale_price is not None:

        current_price = sale_price

    elif price is not None:

        current_price = price

    else:

        current_price = None

    if current_price is None:
        return None

    # --------------------------------------------------------
    # 原价
    # --------------------------------------------------------

    if (
        original_price is None
        and price is not None
        and sale_price is not None
        and price > sale_price
    ):
        original_price = price

    # --------------------------------------------------------
    # JSON-LD Offer 特殊结构
    # --------------------------------------------------------

    offers = obj.get(
        "offers"
    )

    if isinstance(
        offers,
        dict
    ):

        offer_price = normalize_price(
            offers.get("price")
        )

        if (
            current_price is None
            and offer_price is not None
        ):
            current_price = offer_price

    # --------------------------------------------------------
    # 颜色
    # --------------------------------------------------------

    color = get_first_value(
        obj,
        [
            "color",
            "colour",
            "colorName",
            "color_name",
        ],
    )

    # --------------------------------------------------------
    # 尺码
    # --------------------------------------------------------

    size = get_first_value(
        obj,
        [
            "size",
            "sizeName",
            "size_name",
        ],
    )

    # --------------------------------------------------------
    # SKU
    # --------------------------------------------------------

    sku = get_first_value(
        obj,
        [
            "sku",
            "id",
            "variantId",
            "variant_id",
        ],
    )

    # --------------------------------------------------------
    # 库存
    # --------------------------------------------------------

    availability = get_first_value(
        obj,
        [
            "availability",
            "stock",
            "inventory",
            "inStock",
            "in_stock",
        ],
    )

    available = is_available(
        availability
    )

    return {
        "sku": str(sku)
        if sku is not None
        else "",
        "price": current_price,
        "original": (
            original_price
            or current_price
        ),
        "color": normalize_color(
            color
        ),
        "size": normalize_size(
            size
        ),
        "available": available,
    }


# ============================================================
# 从 HTML / JSON 中提取真实变体
# ============================================================

def extract_real_variants(raw_html):

    json_objects = extract_embedded_json(
        raw_html
    )

    candidates = []

    for root in json_objects:

        for obj in walk_json(root):

            variant = parse_variant_object(
                obj
            )

            if variant:

                candidates.append(
                    variant
                )

    # 去重
    unique = {}

    for variant in candidates:

        key = (
            variant.get("sku"),
            variant.get("color"),
            variant.get("size"),
            variant.get("price"),
            variant.get("original"),
        )

        unique[key] = variant

    variants = list(
        unique.values()
    )

    # 至少要有颜色/尺码/sku之一
    variants = [
        v
        for v in variants
        if (
            v.get("color")
            or v.get("size")
            or v.get("sku")
        )
    ]

    return variants


# ============================================================
# Markdown 价格兜底
# ============================================================

def fallback_price_variants(markdown):

    prices = extract_prices(
        markdown
    )

    if not prices:
        return []

    original = max(prices)

    result = []

    for price in prices:

        discount = calculate_discount(
            original,
            price,
        )

        result.append({
            "sku": "",
            "price": price,
            "original": original,
            "color": "",
            "size": "",
            "available": None,
            "discount": discount,
            "fallback": True,
        })

    return result


# ============================================================
# 将真实变体整理成价格档
# ============================================================

def group_variants(real_variants):

    if not real_variants:
        return []

    # --------------------------------------------------------
    # 计算合理原价
    # --------------------------------------------------------

    all_prices = [
        v["price"]
        for v in real_variants
        if v.get("price") is not None
    ]

    if not all_prices:
        return []

    highest_price = max(
        all_prices
    )

    groups = {}

    for v in real_variants:

        price = v.get(
            "price"
        )

        if price is None:
            continue

        original = v.get(
            "original"
        )

        if (
            original is None
            or original < price
        ):
            original = highest_price

        discount = calculate_discount(
            original,
            price,
        )

        key = (
            round(price, 2),
            round(original, 2),
        )

        if key not in groups:

            groups[key] = {
                "price": round(
                    price,
                    2
                ),
                "original": round(
                    original,
                    2
                ),
                "discount": discount,
                "currency": "USD",
                "rmb": round(
                    price * USD_RMB,
                    2
                ),
                "colors": {},
            }

        color = (
            v.get("color")
            or "未标明颜色"
        )

        size = v.get(
            "size"
        )

        if color not in groups[key]["colors"]:
            groups[key]["colors"][color] = []

        if size:

            if size not in groups[key]["colors"][color]:

                groups[key]["colors"][color].append(
                    size
                )

    return list(
        groups.values()
    )


# ============================================================
# 兜底价格档
# ============================================================

def group_fallback_variants(
    variants
):

    groups = []

    for v in variants:

        groups.append({
            "price": v["price"],
            "original": v["original"],
            "discount": v["discount"],
            "currency": "USD",
            "rmb": round(
                v["price"] * USD_RMB,
                2
            ),
            "colors": {},
            "fallback": True,
        })

    return groups


# ============================================================
# 只保留优惠档
# ============================================================

def get_sale_variants(
    variants
):

    result = []

    for variant in variants:

        discount = variant.get(
            "discount",
            0
        )

        if discount > 0:
            result.append(
                variant
            )

    result.sort(
        key=lambda x: (
            -x.get(
                "discount",
                0
            ),
            x.get(
                "price",
                0
            ),
        )
    )

    return result


# ============================================================
# 判断价格是否真正下降
# ============================================================

def get_lowest_sale_price(
    product
):

    sale = product.get(
        "sale_variants",
        []
    )

    prices = []

    for variant in sale:

        price = variant.get(
            "price"
        )

        if price is not None:
            prices.append(
                float(price)
            )

    if not prices:
        return None

    return min(prices)


def should_notify_price_drop(
    old_product,
    new_product
):

    # 第一次发现商品：
    # 只建立基线，不推送
    if not old_product:
        return False

    old_price = get_lowest_sale_price(
        old_product
    )

    new_price = get_lowest_sale_price(
        new_product
    )

    # 之前没有优惠，现在出现优惠
    # 不是“降价”，这里不推
    if old_price is None:
        return False

    # 现在优惠消失
    # 不推
    if new_price is None:
        return False

    # 只有真正降价才推
    return new_price < old_price


# ============================================================
# HTML 转义
# ============================================================

def tg_escape(text):

    if text is None:
        return ""

    text = str(text)

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============================================================
# 颜色排序
# ============================================================

def sort_sizes(sizes):

    order = {
        "XXS": 0,
        "XS": 1,
        "S": 2,
        "M": 3,
        "L": 4,
        "XL": 5,
        "XXL": 6,
        "XXXL": 7,
    }

    return sorted(
        sizes,
        key=lambda x: order.get(
            x,
            99
        )
    )


# ============================================================
# Telegram 消息
# ============================================================

def build_message(product):

    name = product.get(
        "name",
        "未知商品"
    )

    url = product.get(
        "url",
        ""
    )

    sale_variants = product.get(
        "sale_variants",
        []
    )

    if not sale_variants:
        return None

    lines = []

    lines.append(
        "🔥 <b>REI 降价提醒</b>"
    )

    lines.append("")

    lines.append(
        f"<b>{tg_escape(name)}</b>"
    )

    lines.append(
        "━━━━━━━━━━━━"
    )

    for index, variant in enumerate(
        sale_variants
    ):

        price = variant.get(
            "price",
            0
        )

        original = variant.get(
            "original",
            0
        )

        discount = variant.get(
            "discount",
            0
        )

        rmb = variant.get(
            "rmb",
            0
        )

        if index > 0:
            lines.append(
                ""
            )

        # ----------------------------------------------------
        # 价格放最顶部
        # ----------------------------------------------------

        lines.append(
            f"🔥 <b>{discount}% OFF</b>"
        )

        lines.append(
            f"🏷️ 原价 ${original:.2f}"
            f"｜💰 现价 ${price:.2f}"
            f"｜¥{rmb:,.0f}"
        )

        # ----------------------------------------------------
        # 颜色
        # ----------------------------------------------------

        colors = variant.get(
            "colors",
            {}
        )

        if colors:

            color_names = list(
                colors.keys()
            )

            # 横向显示
            lines.append(
                "🎨 "
                + "    ".join(
                    tg_escape(c)
                    for c in color_names
                )
            )

            # 尺码
            size_parts = []

            for color in color_names:

                sizes = colors.get(
                    color,
                    []
                )

                sizes = sort_sizes(
                    sizes
                )

                focus = [
                    s
                    for s in sizes
                    if s in FOCUS_SIZES
                ]

                if focus:

                    size_text = " ".join(
                        focus
                    )

                elif sizes:

                    size_text = " ".join(
                        sizes
                    )

                else:

                    size_text = "-"

                size_parts.append(
                    size_text
                )

            lines.append(
                "📏 "
                + "    ".join(
                    size_parts
                )
            )

            # 库存
            #
            # 这里不因为库存变化推送。
            # 只负责展示当前抓到的状态。
            stock_parts = []

            for color in color_names:

                sizes = colors.get(
                    color,
                    []
                )

                if sizes:
                    stock_parts.append(
                        "有货"
                    )
                else:
                    stock_parts.append(
                        "未知"
                    )

            lines.append(
                "📦 "
                + "    ".join(
                    stock_parts
                )
            )

        else:

            # 如果 Firecrawl 页面没有拿到
            # 真实颜色/尺码矩阵，
            # 明确告诉用户，不假装精确。
            lines.append(
                "🎨 颜色：页面未提供变体数据"
            )

            lines.append(
                "📏 尺码：页面未提供变体数据"
            )

            lines.append(
                "📦 库存：页面未提供变体数据"
            )

        lines.append(
            "━━━━━━━━━━━━"
        )

    # --------------------------------------------------------
    # 最后只放商品链接
    # --------------------------------------------------------

    if url:
        lines.append(
            tg_escape(url)
        )

    return "\n".join(lines)


# ============================================================
# 选择重点商品
# ============================================================

def select_products(
    all_links
):

    selected = []

    for url in all_links:

        lower = url.lower()

        for keyword in WATCHLIST:

            if keyword.lower() in lower:

                if url not in selected:
                    selected.append(
                        url
                    )

                break

    return selected[:MAX_PRODUCTS]


# ============================================================
# 主程序
# ============================================================

def main():

    print("")
    print(
        "======================================"
    )
    print(
        "REI Outdoor Price Monitor"
    )
    print(
        "======================================"
    )

    history = load_history()

    all_links = []

    # ========================================================
    # 1. 抓品牌列表
    # ========================================================

    for page_url in REI_PAGES:

        print("")
        print(
            "抓取列表:",
            page_url
        )

        result = firecrawl(
            page_url,
            use_raw_html=False
        )

        markdown = result.get(
            "markdown",
            ""
        )

        if not markdown:
            print(
                "列表抓取失败"
            )
            continue

        links = get_product_links(
            markdown
        )

        print(
            "发现商品:",
            len(links)
        )

        for link in links:

            if link not in all_links:

                all_links.append(
                    link
                )

    print("")
    print(
        "总商品链接:",
        len(all_links)
    )

    # ========================================================
    # 2. 选择重点商品
    # ========================================================

    selected = select_products(
        all_links
    )

    print(
        "重点商品:",
        len(selected)
    )

    for url in selected:
        print(
            "  -",
            url
        )

    # ========================================================
    # 3. 抓详情页
    # ========================================================

    for url in selected:

        print("")
        print(
            "======================================"
        )

        print(
            "详情:",
            url
        )

        result = firecrawl(
            url,
            use_raw_html=True
        )

        markdown = result.get(
            "markdown",
            ""
        )

        raw_html = result.get(
            "raw_html",
            ""
        )

        if not markdown and not raw_html:

            print(
                "详情抓取失败"
            )

            continue

        # ----------------------------------------------------
        # 商品名称
        # ----------------------------------------------------

        name = get_product_name(
            markdown,
            raw_html,
            url
        )

        print(
            "商品:",
            name
        )

        # ----------------------------------------------------
        # 优先寻找真实变体
        # ----------------------------------------------------

        real_variants = extract_real_variants(
            raw_html
        )

        print(
            "真实变体:",
            len(real_variants)
        )

        if real_variants:

            price_groups = group_variants(
                real_variants
            )

        else:

            print(
                "没有找到完整变体矩阵，"
                "使用价格兜底模式"
            )

            fallback = fallback_price_variants(
                markdown
            )

            price_groups = group_fallback_variants(
                fallback
            )

        # ----------------------------------------------------
        # 优惠
        # ----------------------------------------------------

        sale_variants = get_sale_variants(
            price_groups
        )

        print(
            "优惠档:",
            len(sale_variants)
        )

        for v in sale_variants:

            print(
                "  价格:",
                v.get("price"),
                "原价:",
                v.get("original"),
                "折扣:",
                v.get("discount")
            )

        # ----------------------------------------------------
        # 当前商品
        # ----------------------------------------------------

        product = {
            "name": name,
            "url": url,
            "variants": price_groups,
            "sale_variants": sale_variants,
            "lowest_sale_price": (
                get_lowest_sale_price({
                    "sale_variants":
                    sale_variants
                })
            ),
            "updated_at": int(
                time.time()
            ),
        }

        # ----------------------------------------------------
        # 历史价格
        # ----------------------------------------------------

        old_product = history.get(
            url
        )

        old_lowest = None

        if old_product:

            old_lowest = get_lowest_sale_price(
                old_product
            )

        new_lowest = get_lowest_sale_price(
            product
        )

        print(
            "历史最低优惠价:",
            old_lowest
        )

        print(
            "当前最低优惠价:",
            new_lowest
        )

        # ----------------------------------------------------
        # 只判断“降价”
        # ----------------------------------------------------

        notify = should_notify_price_drop(
            old_product,
            product
        )

        if notify:

            print(
                "🔥 检测到真正降价，发送 Telegram"
            )

            message = build_message(
                product
            )

            if message:

                send_telegram(
                    message
                )

        else:

            if old_product is None:

                print(
                    "首次发现：建立价格基线，不推送"
                )

            elif (
                old_lowest is not None
                and new_lowest is not None
                and new_lowest > old_lowest
            ):

                print(
                    "价格上涨：不推送"
                )

            elif (
                old_lowest is not None
                and new_lowest is None
            ):

                print(
                    "优惠消失：不推送"
                )

            else:

                print(
                    "没有降价：不推送"
                )

        # ----------------------------------------------------
        # 保存最新数据
        # ----------------------------------------------------

        history[url] = product

        # 避免连续请求过快
        time.sleep(1)

    # ========================================================
    # 4. 保存历史
    # ========================================================

    save_history(
        history
    )

    print("")
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
