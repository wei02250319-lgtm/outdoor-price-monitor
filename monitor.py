import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# 基础配置
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

# 每次 Firecrawl 请求之间等待
FIRECRAWL_DELAY = 9

# Firecrawl 超时
FIRECRAWL_TIMEOUT = 90

# 每次运行自动发现商品数量上限
DISCOVERY_LIMIT = 6

# 每次运行固定商品轮换数量
FIXED_ROTATION = 4

# 降价推送最低折扣
MIN_DISCOUNT = 20

# 重要优惠
IMPORTANT_DISCOUNT = 30

# 超级优惠
SUPER_DISCOUNT = 50

# 历史文件
DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "prices.json"

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 14) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/130.0 Mobile Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
)


# ============================================================
# 固定监控商品
# ============================================================

FIXED_PRODUCTS = [
    {
        "name": "Arc'teryx Gamma MX Hoody - Men's",
        "url": "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx Gamma Jacket - Men's",
        "url": "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx Gamma Pants - Men's",
        "url": "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Patagonia R2 TechFace Jacket - Men's",
        "url": "https://www.rei.com/product/222148/patagonia-r2-techface-jacket-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "url": "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx Atom Insulated Jacket - Men's",
        "url": "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
        "site": "REI",
        "currency": "USD",
    },
]


# ============================================================
# 自动发现页面
# ============================================================

DISCOVERY_SOURCES = [
    {
        "name": "REI",
        "url": "https://www.rei.com/c/mens-clothing/f/scd-deals",
        "site": "REI",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx US Outlet",
        "url": "https://outlet.arcteryx.com/us/en/shop/mens",
        "site": "Arc'teryx US",
        "currency": "USD",
    },
    {
        "name": "Arc'teryx Canada Outlet",
        "url": "https://outlet.arcteryx.com/ca/en/shop/mens",
        "site": "Arc'teryx Canada",
        "currency": "CAD",
    },
    {
        "name": "Patagonia US",
        "url": "https://www.patagonia.com/shop/web-specials/mens",
        "site": "Patagonia US",
        "currency": "USD",
    },
    {
        "name": "Patagonia Canada",
        "url": "https://www.patagonia.ca/shop/web-specials/mens",
        "site": "Patagonia Canada",
        "currency": "CAD",
    },
    {
        "name": "The North Face US",
        "url": "https://www.thenorthface.com/en-us/c/sale/mens-sale-317774",
        "site": "The North Face US",
        "currency": "USD",
    },
    {
        "name": "The North Face Canada",
        "url": "https://www.thenorthface.com/en-ca/c/sale-829803",
        "site": "The North Face Canada",
        "currency": "CAD",
    },
]


# ============================================================
# 排除商品
# ============================================================

EXCLUDED_URLS = {
    "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
}

EXCLUDED_NAMES = {
    "patagonia r2 techface hoody - men's",
    "patagonia r2 techface hoody men's",
}


# ============================================================
# 工具函数
# ============================================================

def ensure_data_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps(
                {
                    "products": {},
                    "meta": {
                        "version": 2
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def load_history():
    ensure_data_file()

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            data = {}

        if "products" not in data:
            data["products"] = {}

        return data

    except Exception as exc:
        print("读取历史价格失败：", exc)

        return {
            "products": {},
            "meta": {
                "version": 2
            },
        }


def save_history(data):
    ensure_data_file()

    temp_file = DATA_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp_file.replace(DATA_FILE)


def clean_text(value):
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def to_float(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, dict):
        for key in (
            "amount",
            "value",
            "price",
            "current",
            "salePrice",
            "currentPrice",
        ):
            if key in value:
                result = to_float(value[key])

                if result is not None:
                    return result

        return None

    text = str(value)

    text = text.replace(",", "")

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text,
    )

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


def amount(value):
    if value is None:
        return None

    if isinstance(value, dict):

        for key in (
            "amount",
            "value",
            "price",
            "currentPrice",
            "salePrice",
        ):
            if key in value:

                result = amount(value[key])

                if result is not None:
                    return result

        return None

    return to_float(value)


def nested(obj, *keys):

    current = obj

    for key in keys:

        if not isinstance(current, dict):
            return None

        current = current.get(key)

    return current


def first_value(obj, keys):

    if not isinstance(obj, dict):
        return None

    for key in keys:

        value = obj.get(key)

        if value is not None:
            return value

    return None


# ============================================================
# Firecrawl
# ============================================================

def firecrawl(url, formats):

    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")
        return {}

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": url,
        "formats": formats,
        "waitFor": 3000,
    }

    try:

        response = SESSION.post(
            FIRECRAWL_URL,
            headers=headers,
            json=payload,
            timeout=FIRECRAWL_TIMEOUT,
        )

        print(
            f"Firecrawl HTTP {response.status_code}: {url}"
        )

        if response.status_code != 200:

            print(
                "Firecrawl 返回：",
                response.text[:1000],
            )

            return {}

        body = response.json()

        return body.get("data", {}) or {}

    except Exception as exc:

        print(
            "Firecrawl 请求异常：",
            repr(exc),
        )

        return {}


def product_scrape(url):

    data = firecrawl(
        url,
        ["product"],
    )

    product = data.get("product") or {}

    if not isinstance(product, dict):
        return {}

    return product


# ============================================================
# 商品名称
# ============================================================

def get_product_title(product, fallback=""):

    if not isinstance(product, dict):
        return fallback

    title = first_value(
        product,
        [
            "title",
            "name",
            "productName",
            "product_title",
        ],
    )

    if title:
        return clean_text(title)

    return clean_text(fallback)


# ============================================================
# 价格
# ============================================================

def get_price(variant):

    if not isinstance(variant, dict):
        return None

    candidates = [
        variant.get("price"),
        variant.get("currentPrice"),
        variant.get("salePrice"),
        variant.get("discountedPrice"),
        variant.get("finalPrice"),
        nested(variant, "sale", "price"),
        nested(variant, "pricing", "price"),
        nested(variant, "pricing", "currentPrice"),
        nested(variant, "prices", "sale"),
        nested(variant, "prices", "current"),
    ]

    for candidate in candidates:

        value = amount(candidate)

        if value is not None:
            return value

    return None


def get_original(variant):

    if not isinstance(variant, dict):
        return None

    candidates = [
        variant.get("originalPrice"),
        variant.get("listPrice"),
        variant.get("compareAtPrice"),
        variant.get("regularPrice"),
        variant.get("wasPrice"),
        variant.get("fullPrice"),
        nested(variant, "sale", "originalPrice"),
        nested(variant, "pricing", "originalPrice"),
        nested(variant, "pricing", "listPrice"),
        nested(variant, "prices", "original"),
        nested(variant, "prices", "regular"),
    ]

    for candidate in candidates:

        value = amount(candidate)

        if value is not None:
            return value

    return None


# ============================================================
# 货币
# ============================================================

def get_currency(variant, product, default_currency):

    for obj in (variant, product):

        if not isinstance(obj, dict):
            continue

        value = first_value(
            obj,
            [
                "currency",
                "currencyCode",
            ],
        )

        if value:
            return str(value).upper()

    return default_currency


# ============================================================
# 颜色 / 尺码
# ============================================================

def get_values(variant):

    if not isinstance(variant, dict):
        return "", ""

    color = first_value(
        variant,
        [
            "color",
            "colour",
            "colorName",
            "colourName",
        ],
    )

    size = first_value(
        variant,
        [
            "size",
            "sizeName",
        ],
    )

    if isinstance(color, dict):
        color = first_value(
            color,
            [
                "name",
                "value",
                "label",
            ],
        )

    if isinstance(size, dict):
        size = first_value(
            size,
            [
                "name",
                "value",
                "label",
            ],
        )

    return (
        clean_text(color),
        clean_text(size),
    )


# ============================================================
# 库存
# ============================================================

def in_stock(variant):

    if not isinstance(variant, dict):
        return True

    values = [
        variant.get("inStock"),
        variant.get("available"),
        variant.get("availableForSale"),
        variant.get("isAvailable"),
        variant.get("availability"),
        variant.get("stock"),
        variant.get("inventory"),
    ]

    for value in values:

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value > 0

        if isinstance(value, dict):

            for key in (
                "available",
                "quantity",
                "inStock",
            ):

                if key in value:

                    inner = value[key]

                    if isinstance(inner, bool):
                        return inner

                    if isinstance(inner, (int, float)):
                        return inner > 0

        if isinstance(value, str):

            text = value.lower()

            if any(
                word in text
                for word in [
                    "out of stock",
                    "unavailable",
                    "sold out",
                ]
            ):
                return False

            if any(
                word in text
                for word in [
                    "in stock",
                    "available",
                ]
            ):
                return True

    return True


# ============================================================
# Variant Key
# ============================================================

def variant_key(variant):

    if not isinstance(variant, dict):
        return ""

    value = first_value(
        variant,
        [
            "id",
            "sku",
            "variantId",
            "productId",
        ],
    )

    if value:
        return str(value)

    color, size = get_values(variant)

    return f"{color}|{size}"


# ============================================================
# 提取 Variant
# ============================================================

def get_product_variants(product, default_currency):

    if not isinstance(product, dict):
        return []

    variants = product.get("variants")

    if not isinstance(variants, list):
        variants = []

    # 有些 Firecrawl 数据直接把商品本身当成一个 variant
    if not variants:
        variants = [product]

    results = []

    for variant in variants:

        if not isinstance(variant, dict):
            continue

        current = get_price(variant)

        if current is None:
            continue

        original = get_original(variant)

        color, size = get_values(variant)

        currency = get_currency(
            variant,
            product,
            default_currency,
        )

        results.append(
            {
                "key": variant_key(variant),
                "price": current,
                "original": original,
                "currency": currency,
                "color": color or "默认颜色",
                "size": size or "默认尺码",
                "stock": in_stock(variant),
            }
        )

    return results


# ============================================================
# 折扣计算
# ============================================================

def discount_percent(price, original):

    if price is None or original is None:
        return 0

    if original <= 0:
        return 0

    if price >= original:
        return 0

    discount = (
        (original - price)
        / original
        * 100
    )

    return round(discount)


# ============================================================
# URL 判断
# ============================================================

def is_product_url(url):

    if not url:
        return False

    parsed = urlparse(url)

    host = parsed.netloc.lower()

    path = parsed.path.lower().rstrip("/")

    # REI
    if "rei.com" in host:

        return "/product/" in path

    # Arc'teryx Outlet
    if "outlet.arcteryx.com" in host:

        if "/shop/mens/" not in path:
            return False

        slug = path.rsplit("/", 1)[-1]

        if not slug:
            return False

        category_words = {
            "jackets",
            "tops",
            "shirts",
            "pants",
            "shorts",
            "fleece",
            "insulation",
            "shells",
            "layers",
            "vests",
            "hoodies",
            "sweaters",
            "base-layers",
            "accessories",
            "packs",
            "footwear",
            "climbing",
            "ski",
            "snow",
        }

        if slug in category_words:
            return False

        return True

    # Patagonia
    if (
        "patagonia.com" in host
        or "patagonia.ca" in host
    ):

        return "/product/" in path

    # The North Face
    if "thenorthface.com" in host:

        if "/c/" in path:
            return False

        if re.search(
            r"/(?:p|product)/",
            path,
            re.I,
        ):
            return True

        return bool(
            re.search(
                r"[a-z0-9-]+-\d{5,}$",
                path,
                re.I,
            )
        )

    return False


# ============================================================
# 链接发现
# ============================================================

def discover_links(source):

    source_name = source["name"]
    source_url = source["url"]

    print(
        f"发现扫描：{source_name}"
    )

    data = firecrawl(
        source_url,
        ["markdown"],
    )

    markdown = data.get("markdown") or ""

    links = set()

    # Markdown URL
    markdown_urls = re.findall(
        r"https?://[^\s\]\)>\"]+",
        markdown,
    )

    for url in markdown_urls:
        url = url.rstrip(".,;")

        if is_product_url(url):
            links.add(url)

    # HTML href
    html = data.get("html") or ""

    if html:

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        for a in soup.find_all(
            "a",
            href=True,
        ):

            href = a.get("href")

            if not href:
                continue

            full_url = urljoin(
                source_url,
                href,
            )

            full_url = full_url.split("#")[0]

            if is_product_url(full_url):
                links.add(full_url)

    print(
        f"发现 {len(links)} 个商品链接：{source_name}"
    )

    return list(links)


# ============================================================
# 自动发现商品
# ============================================================

def discovery_products(history):

    known_urls = set()

    for product in FIXED_PRODUCTS:
        known_urls.add(product["url"])

    for url in EXCLUDED_URLS:
        known_urls.add(url)

    history_products = history.get(
        "products",
        {},
    )

    if isinstance(history_products, dict):

        for value in history_products.values():

            if isinstance(value, dict):

                url = value.get("url")

                if url:
                    known_urls.add(url)

    candidates = []

    for source in DISCOVERY_SOURCES:

        try:

            links = discover_links(
                source
            )

            for url in links:

                if url in known_urls:
                    continue

                if url in EXCLUDED_URLS:
                    continue

                candidates.append(
                    {
                        "name": "",
                        "url": url,
                        "site": source["site"],
                        "currency": source["currency"],
                        "discovered": True,
                    }
                )

        except Exception as exc:

            print(
                f"发现 {source['name']} 失败：",
                repr(exc),
            )

    # 去重
    unique = {}

    for item in candidates:

        unique[item["url"]] = item

    candidates = list(unique.values())

    # 控制数量
    candidates = candidates[
        :DISCOVERY_LIMIT
    ]

    print(
        "本次新增发现商品：",
        len(candidates),
    )

    return candidates


# ============================================================
# 商品历史 ID
# ============================================================

def product_history_key(url):

    return url


# ============================================================
# 商品名称过滤
# ============================================================

def is_mens_product(title):

    text = title.lower()

    if "men's" in text:
        return True

    if "mens" in text:
        return True

    if "men’s" in text:
        return True

    return False


def is_excluded_product(title, url):

    if url in EXCLUDED_URLS:
        return True

    text = clean_text(
        title
    ).lower()

    if text in EXCLUDED_NAMES:
        return True

    if "r2 techface hoody" in text:
        return True

    return False


# ============================================================
# 当前商品数据
# ============================================================

def build_current_product(
    item,
    product,
):

    title = get_product_title(
        product,
        item.get("name", ""),
    )

    variants = get_product_variants(
        product,
        item.get("currency", "USD"),
    )

    if not variants:
        return None

    # 商品中所有有效价格
    prices = [
        v["price"]
        for v in variants
        if v.get("price") is not None
    ]

    if not prices:
        return None

    current_min = min(prices)

    originals = [
        v["original"]
        for v in variants
        if v.get("original") is not None
    ]

    original_max = (
        max(originals)
        if originals
        else None
    )

    # 如果 Firecrawl 没返回原价，
    # 尝试从商品整体读取
    if original_max is None:

        original_max = get_original(
            product
        )

    return {
        "name": title,
        "url": item["url"],
        "site": item.get(
            "site",
            "",
        ),
        "currency": item.get(
            "currency",
            "USD",
        ),
        "variants": variants,
        "current_min": current_min,
        "original_max": original_max,
    }


# ============================================================
# 价格层级
# ============================================================

def build_price_groups(variants):

    groups = {}

    for variant in variants:

        price = variant.get("price")

        if price is None:
            continue

        key = (
            variant.get("currency"),
            round(float(price), 2),
        )

        if key not in groups:

            groups[key] = {
                "currency": variant.get(
                    "currency",
                    "USD",
                ),
                "price": float(price),
                "variants": [],
            }

        groups[key]["variants"].append(
            variant
        )

    return list(
        groups.values()
    )


# ============================================================
# 格式化价格
# ============================================================

def money(value):

    if value is None:
        return "-"

    return f"{value:.2f}"


# ============================================================
# 生成 Telegram 商品信息
# ============================================================

def build_product_message(
    product,
    previous_price=None,
):

    variants = product["variants"]

    groups = build_price_groups(
        variants
    )

    if not groups:
        return ""

    messages = []

    for group in groups:

        price = group["price"]

        group_variants = group[
            "variants"
        ]

        originals = [
            v["original"]
            for v in group_variants
            if v.get("original") is not None
        ]

        original = (
            max(originals)
            if originals
            else product.get(
                "original_max"
            )
        )

        discount = discount_percent(
            price,
            original,
        )

        if discount < MIN_DISCOUNT:
            continue

        if discount >= SUPER_DISCOUNT:
            icon = "🚨"
            level = "超级优惠"
        elif discount >= IMPORTANT_DISCOUNT:
            icon = "🔥"
            level = "重要优惠"
        else:
            icon = "🏷️"
            level = "优惠"

        lines = []

        lines.append(
            f"{icon} {discount}% OFF｜"
            f"{product['name']}"
        )

        if level != "优惠":
            lines.append(
                f"⭐ {level}"
            )

        if original is not None:

            lines.append(
                f"🏷️ 原价 "
                f"{group['currency']} "
                f"{money(original)}｜"
                f"💰 现价 "
                f"{group['currency']} "
                f"{money(price)}"
            )

        else:

            lines.append(
                f"💰 现价 "
                f"{group['currency']} "
                f"{money(price)}"
            )

        # ----------------------------------------------------
        # 按颜色分组
        # ----------------------------------------------------

        colors = {}

        for variant in group_variants:

            color = (
                variant.get("color")
                or "默认颜色"
            )

            if color not in colors:
                colors[color] = []

            colors[color].append(
                variant
            )

        if colors:

            lines.append("")

            # 颜色
            color_names = list(
                colors.keys()
            )

            lines.append(
                "颜色       "
                + "      ".join(
                    color_names
                )
            )

            # 尺码
            size_parts = []

            for color in color_names:

                sizes = []

                for variant in colors[
                    color
                ]:

                    size = (
                        variant.get("size")
                        or "-"
                    )

                    if size not in sizes:
                        sizes.append(size)

                size_parts.append(
                    " ".join(sizes)
                )

            lines.append(
                "尺码       "
                + "      ".join(
                    size_parts
                )
            )

            # 库存
            stock_parts = []

            for color in color_names:

                color_variants = colors[
                    color
                ]

                available = any(
                    v.get("stock")
                    for v in color_variants
                )

                stock_parts.append(
                    "有货"
                    if available
                    else "无货"
                )

            lines.append(
                "库存       "
                + "      ".join(
                    stock_parts
                )
            )

        lines.append("")
        lines.append("━━━━━━━━━━━━")

        messages.append(
            "\n".join(lines)
        )

    if not messages:
        return ""

    result = "\n".join(messages)

    result += (
        "\n\n🔗 "
        + product["url"]
    )

    return result


# ============================================================
# Telegram
# ============================================================

def telegram_send(text):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "没有 TELEGRAM_BOT_TOKEN，"
            "跳过推送"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "没有 TELEGRAM_CHAT_ID，"
            "跳过推送"
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=30,
        )

        if response.status_code != 200:

            print(
                "Telegram 推送失败：",
                response.text[:1000],
            )

            return False

        print("Telegram 推送成功")

        return True

    except Exception as exc:

        print(
            "Telegram 请求异常：",
            repr(exc),
        )

        return False


# ============================================================
# 历史价格处理
# ============================================================

def get_previous_price(
    history,
    url,
):

    products = history.get(
        "products",
        {},
    )

    item = products.get(url)

    if not isinstance(item, dict):
        return None

    value = item.get(
        "current_price"
    )

    return to_float(value)


def save_product_history(
    history,
    product,
):

    url = product["url"]

    variants = product[
        "variants"
    ]

    price_values = [
        v["price"]
        for v in variants
        if v.get("price") is not None
    ]

    if not price_values:
        return

    current_price = min(
        price_values
    )

    discounts = []

    for variant in variants:

        discount = discount_percent(
            variant.get("price"),
            variant.get("original"),
        )

        if discount:
            discounts.append(
                discount
            )

    max_discount = (
        max(discounts)
        if discounts
        else 0
    )

    history.setdefault(
        "products",
        {},
    )

    history["products"][
        url
    ] = {
        "url": url,
        "name": product["name"],
        "site": product["site"],
        "currency": product[
            "currency"
        ],
        "current_price": current_price,
        "max_discount": max_discount,
        "variants": variants,
        "updated_at": int(
            time.time()
        ),
    }


# ============================================================
# 判断是否应该推送
# ============================================================

def should_alert(
    product,
    previous_price,
):

    if previous_price is None:
        print(
            "首次发现商品：不推送"
        )
        return False

    current_price = product[
        "current_min"
    ]

    # 实际价格没有下降
    if current_price >= previous_price:

        if current_price == previous_price:
            print(
                "实际现价没有变化：不推送"
            )
        else:
            print(
                "实际现价上涨：不推送"
            )

        return False

    # 价格确实下降
    print(
        f"实际现价下降："
        f"{previous_price:.2f}"
        f" -> "
        f"{current_price:.2f}"
    )

    # 检查折扣
    max_discount = 0

    for variant in product[
        "variants"
    ]:

        discount = discount_percent(
            variant.get("price"),
            variant.get("original"),
        )

        max_discount = max(
            max_discount,
            discount,
        )

    if max_discount < MIN_DISCOUNT:

        print(
            f"价格下降，但当前最大折扣 "
            f"{max_discount}% < "
            f"{MIN_DISCOUNT}%：不推送"
        )

        return False

    return True


# ============================================================
# 检查一个商品
# ============================================================

def check_product(
    item,
    history,
):

    url = item["url"]

    if url in EXCLUDED_URLS:
        print(
            "跳过排除商品：",
            url,
        )
        return

    print(
        "检查：",
        item.get(
            "name",
            url,
        ),
    )

    product_data = product_scrape(
        url
    )

    if not product_data:

        print(
            "没有取得商品数据"
        )

        return

    title = get_product_title(
        product_data,
        item.get("name", ""),
    )

    if is_excluded_product(
        title,
        url,
    ):

        print(
            "跳过排除商品：",
            title,
        )

        return

    # 自动发现时只保留男装
    if item.get("discovered"):

        if not is_mens_product(
            title
        ):

            print(
                "跳过非男装：",
                title,
            )

            return

    product = build_current_product(
        item,
        product_data,
    )

    if not product:

        print(
            "没有提取到价格"
        )

        return

    previous_price = (
        get_previous_price(
            history,
            url,
        )
    )

    print(
        f"当前最低实际价格："
        f"{product['current_min']:.2f}"
    )

    if previous_price is not None:

        print(
            f"上次实际价格："
            f"{previous_price:.2f}"
        )

    # 判断是否推送
    alert = should_alert(
        product,
        previous_price,
    )

    if alert:

        message = (
            build_product_message(
                product,
                previous_price,
            )
        )

        if message:

            telegram_send(
                message
            )

    # 无论是否推送，都更新历史
    save_product_history(
        history,
        product,
    )


# ============================================================
# 固定商品轮换
# ============================================================

def get_rotation_products(
    history,
):

    products = history.setdefault(
        "products",
        {},
    )

    state = history.setdefault(
        "meta",
        {},
    )

    index = int(
        state.get(
            "fixed_rotation_index",
            0,
        )
    )

    total = len(
        FIXED_PRODUCTS
    )

    if total == 0:
        return []

    selected = []

    for i in range(
        min(FIXED_ROTATION, total)
    ):

        position = (
            index + i
        ) % total

        selected.append(
            FIXED_PRODUCTS[position]
        )

    state[
        "fixed_rotation_index"
    ] = (
        index + FIXED_ROTATION
    ) % total

    return selected


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "Outdoor Price Monitor"
    )

    print(
        "开始运行 monitor.py"
    )

    print(
        "================================"
    )

    history = load_history()

    # --------------------------------------------------------
    # 1. 自动发现
    # --------------------------------------------------------

    discovered = discovery_products(
        history
    )

    # --------------------------------------------------------
    # 2. 固定商品轮换
    # --------------------------------------------------------

    fixed = get_rotation_products(
        history
    )

    # --------------------------------------------------------
    # 3. 合并
    # --------------------------------------------------------

    products_to_check = []

    seen = set()

    for item in fixed + discovered:

        url = item["url"]

        if url in seen:
            continue

        if url in EXCLUDED_URLS:
            continue

        seen.add(url)

        products_to_check.append(
            item
        )

    print(
        "本次检查商品数量：",
        len(products_to_check),
    )

    # --------------------------------------------------------
    # 4. 检查商品
    # --------------------------------------------------------

    for index, item in enumerate(
        products_to_check,
        start=1,
    ):

        print(
            ""
        )

        print(
            f"========== "
            f"{index}/"
            f"{len(products_to_check)} "
            f"=========="
        )

        try:

            check_product(
                item,
                history,
            )

        except Exception as exc:

            print(
                "商品检查异常：",
                item.get(
                    "url",
                    "",
                ),
            )

            print(
                repr(exc)
            )

        # 防止 Firecrawl 请求过快
        time.sleep(
            FIRECRAWL_DELAY
        )

    # --------------------------------------------------------
    # 5. 保存历史
    # --------------------------------------------------------

    try:

        save_history(
            history
        )

        print(
            ""
        )

        print(
            "价格历史保存成功"
        )

    except Exception as exc:

        print(
            "保存历史失败：",
            repr(exc),
        )

    print(
        ""
    )

    print(
        "本次运行完成"
    )

    print(
        "================================"
    )


if __name__ == "__main__":
    main()
