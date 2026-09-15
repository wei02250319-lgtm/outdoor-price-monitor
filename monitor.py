import os
import re
import json
import time
import html
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests


# =========================
# 基础配置
# =========================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HISTORY_FILE = Path("data/prices.json")

# 每次运行检查 4 个固定商品
BATCH_SIZE = 4

# 每次运行检查 6 个自动发现商品
DISCOVERY_BATCH_SIZE = 6

# 两次 Firecrawl 请求之间等待
REQUEST_INTERVAL = 9

# 当前折扣至少 20%
MIN_DISCOUNT = 20.0

# Firecrawl 单次超时
FIRECRAWL_TIMEOUT = 60

# Firecrawl 最多重试次数
FIRECRAWL_RETRIES = 3


# =========================
# 7 个重点商品
# =========================

FIXED_PRODUCTS = [
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
# 自动发现入口
# =========================

DISCOVERY_PAGES = [
    (
        "REI",
        "https://www.rei.com/c/mens-clothing/f/scd-deals",
        "USD",
    ),
    (
        "Arc'teryx US Outlet",
        "https://outlet.arcteryx.com/us/en/shop/mens",
        "USD",
    ),
    (
        "Arc'teryx Canada Outlet",
        "https://outlet.arcteryx.com/ca/en/shop/mens",
        "CAD",
    ),
    (
        "Patagonia US",
        "https://www.patagonia.com/shop/web-specials/mens",
        "USD",
    ),
    (
        "Patagonia Canada",
        "https://www.patagonia.ca/shop/web-specials/mens",
        "CAD",
    ),
    (
        "The North Face US",
        "https://www.thenorthface.com/en-us/c/sale/mens-sale-317774",
        "USD",
    ),
    (
        "The North Face Canada",
        "https://www.thenorthface.com/en-ca/c/sale-829803",
        "CAD",
    ),
]


SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; OutdoorPriceMonitor/2.0)"
        )
    }
)


# =========================
# 历史记录
# =========================

def default_history():
    return {
        "position": 0,
        "discovery_position": 0,
        "products": {},
        "discovered_products": [],
    }


def load_history():

    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not HISTORY_FILE.exists():
        return default_history()

    try:

        data = json.loads(
            HISTORY_FILE.read_text(
                encoding="utf-8"
            )
        )

        data.setdefault("position", 0)
        data.setdefault("discovery_position", 0)
        data.setdefault("products", {})
        data.setdefault("discovered_products", [])

        return data

    except Exception as error:

        print(
            "历史记录读取失败:",
            error,
        )

        return default_history()


def save_history(history):

    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = HISTORY_FILE.with_suffix(
        ".tmp"
    )

    temp_file.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp_file.replace(HISTORY_FILE)


# =========================
# Firecrawl
# =========================

def firecrawl(url, formats):

    if not FIRECRAWL_API_KEY:
        raise RuntimeError(
            "缺少 FIRECRAWL_API_KEY"
        )

    last_error = None

    for attempt in range(
        1,
        FIRECRAWL_RETRIES + 1,
    ):

        try:

            print(
                f"Firecrawl 请求 "
                f"{attempt}/{FIRECRAWL_RETRIES}: "
                f"{url}"
            )

            response = SESSION.post(
                "https://api.firecrawl.dev/v2/scrape",
                headers={
                    "Authorization": (
                        f"Bearer "
                        f"{FIRECRAWL_API_KEY}"
                    ),
                    "Content-Type": (
                        "application/json"
                    ),
                },
                json={
                    "url": url,
                    "formats": formats,
                    "waitFor": 3000,
                },
                timeout=FIRECRAWL_TIMEOUT,
            )

            if response.status_code == 200:

                body = response.json()

                if body.get("success"):

                    return body.get(
                        "data",
                        {},
                    )

                last_error = RuntimeError(
                    "Firecrawl failed: "
                    + str(body)[:500]
                )

            else:

                last_error = RuntimeError(
                    f"Firecrawl HTTP "
                    f"{response.status_code}: "
                    f"{response.text[:500]}"
                )

                # 404 / 400 这类错误通常重试意义不大
                if response.status_code in {
                    400,
                    401,
                    403,
                    404,
                }:
                    break

        except requests.exceptions.Timeout as error:

            last_error = error

            print(
                f"Firecrawl 超时，"
                f"准备重试: {url}"
            )

        except requests.exceptions.RequestException as error:

            last_error = error

            print(
                f"Firecrawl 网络错误，"
                f"准备重试: {url}"
            )

        except Exception as error:

            last_error = error

            print(
                f"Firecrawl 异常，"
                f"准备重试: {url}"
            )

        if attempt < FIRECRAWL_RETRIES:

            time.sleep(
                5 * attempt
            )

    raise RuntimeError(
        f"Firecrawl 最终失败: "
        f"{last_error}"
    )


def product_scrape(url):

    data = firecrawl(
        url,
        ["product"],
    )

    return data.get(
        "product"
    ) or {}


def discovery_scrape(url):

    data = firecrawl(
        url,
        ["markdown"],
    )

    return data.get(
        "markdown"
    ) or ""


# =========================
# URL
# =========================

def normalize_url(
    url,
    base_url=None,
):

    if not url:
        return ""

    url = html.unescape(
        str(url).strip()
    )

    # 去掉 markdown / HTML 常见尾部字符
    url = url.rstrip(
        " \t\r\n\"'>"
    )

    if base_url:
        url = urljoin(
            base_url,
            url,
        )

    if not url.startswith(
        "http"
    ):
        return ""

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        return ""

    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    ).rstrip("/")


# =========================
# 判断真正商品 URL
# =========================

def is_product_url(url):

    if not url:
        return False

    parsed = urlparse(url)

    host = (
        parsed.netloc
        .lower()
    )

    path = (
        parsed.path
        .lower()
        .rstrip("/")
    )

    # ---------------------
    # REI
    # ---------------------

    if "rei.com" in host:

        return (
            "/product/" in path
        )

    # ---------------------
    # Arc'teryx Outlet
    # ---------------------

    if "outlet.arcteryx.com" in host:

        # 排除明显分类页
        category_words = {
            "/shop/mens",
            "/shop/mens/",
            "/shop/mens/jackets",
            "/shop/mens/tops",
            "/shop/mens/pants",
            "/shop/mens/fleece",
            "/shop/mens/insulation",
        }

        if path in category_words:
            return False

        # 商品页一般在 shop/mens 后还有商品 slug
        return bool(
            re.search(
                r"/shop/mens/[^/]+",
                path,
                re.I,
            )
        )

    # ---------------------
    # Patagonia
    # ---------------------

    if "patagonia.com" in host:

        # Patagonia 商品页通常带 product
        if "/product/" in path:
            return True

        # 排除分类页
        category_parts = {
            "/shop/web-specials/mens",
            "/shop/web-specials/mens/wool",
            "/shop/web-specials/mens/down-insulation",
            "/shop/web-specials/mens/hemp",
            "/shop/web-specials/mens/econyl",
            "/shop/web-specials/mens/fair-trade",
            "/shop/web-specials/mens/pfc-free",
        }
def is_product_url(url):

    if not url:
        return False

    parsed = urlparse(url)

    host = parsed.netloc.lower()

    path = (
        parsed.path
        .lower()
        .rstrip("/")
    )

    # =====================
    # REI
    # =====================

    if "rei.com" in host:

        return "/product/" in path

    # =====================
    # Arc'teryx Outlet
    # =====================

    if "outlet.arcteryx.com" in host:

        # 实际商品 URL：
        # /us/en/shop/mens/xxxxx
        # /ca/en/shop/mens/xxxxx

        if not re.search(
            r"/shop/mens/[^/]+$",
            path,
            re.I,
        ):
            return False

        # 排除明显分类页
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

        slug = path.rsplit(
            "/",
            1
        )[-1]

        if slug in category_words:
            return False

        return True

    # =====================
    # Patagonia US / Canada
    # =====================

    if (
        "patagonia.com" in host
        or "patagonia.ca" in host
    ):

        # Patagonia 真正商品页使用 /product/
        #
        # 例如：
        # /product/xxxx

        if "/product/" in path:
            return True

        # /shop/web-specials/mens/xxxx
        # 这一类路径可能是分类页，
        # 统一不作为商品页。
        return False

    # =====================
    # The North Face
    # =====================

    if "thenorthface.com" in host:

        # 排除分类页面
        if "/c/" in path:
            return False

        # TNF 常见商品 URL
        if re.search(
            r"/(?:p|product)/",
            path,
            re.I,
        ):
            return True

        # 某些商品 URL 使用编号结尾
        if (
            "/en-us/" in path
            or "/en-ca/" in path
        ):

            return bool(
                re.search(
                    r"[a-z0-9-]+-\d{5,}$",
                    path,
                    re.I,
                )
            )

        return False

    return False

def extract_product_links(
    markdown,
    base_url,
):

    results = []
    seen = set()

    # Markdown / HTML 中尽可能提取 URL
    patterns = [
        r'\]\(([^)\s]+)\)',
        r'href=["\']([^"\']+)["\']',
        r'(https?://[^\s<>"\']+)',
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            markdown,
            re.I,
        ):

            raw = match.group(1)

            raw = html.unescape(
                raw
            )

            # 去掉 markdown 尾巴
            raw = raw.rstrip(
                ".,);"
            )

            url = normalize_url(
                raw,
                base_url,
            )

            if not url:
                continue

            if not is_product_url(
                url
            ):
                continue

            if url in seen:
                continue

            seen.add(url)
            results.append(url)

    return results


# =========================
# 数值
# =========================

def to_float(value):

    if value is None:
        return None

    if isinstance(
        value,
        dict,
    ):

        for key in (
            "amount",
            "value",
            "price",
        ):

            if key in value:
                return to_float(
                    value[key]
                )

        return None

    if isinstance(
        value,
        (int, float),
    ):
        return float(value)

    text = (
        str(value)
        .replace(",", "")
    )

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text,
    )

    if not match:
        return None

    return float(
        match.group()
    )


def nested(
    obj,
    *keys,
):

    current = obj

    for key in keys:

        if not isinstance(
            current,
            dict,
        ):
            return None

        current = current.get(
            key
        )

    return current


def amount(value):

    if value is None:
        return None

    if isinstance(
        value,
        dict,
    ):

        for key in (
            "amount",
            "value",
        ):

            if key in value:
                return to_float(
                    value[key]
                )

        if "price" in value:
            return amount(
                value["price"]
            )

    return to_float(
        value
    )


def get_price(
    variant,
):

    candidates = [
        variant.get("price"),
        variant.get("currentPrice"),
        nested(
            variant,
            "sale",
            "price",
        ),
        variant.get(
            "discountedPrice"
        ),
    ]

    for candidate in candidates:

        value = amount(
            candidate
        )

        if value is not None:
            return value

    return None


def get_original(
    variant,
):

    candidates = [
        nested(
            variant,
            "sale",
            "originalPrice",
        ),
        variant.get(
            "originalPrice"
        ),
        variant.get(
            "listPrice"
        ),
        variant.get(
            "compareAtPrice"
        ),
    ]

    for candidate in candidates:

        value = amount(
            candidate
        )

        if value is not None:
            return value

    return None


def get_currency(
    variant,
    product,
    default="USD",
):

    for obj in (
        variant,
        product,
    ):

        if not isinstance(
            obj,
            dict,
        ):
            continue

        for key in (
            "currency",
            "currencyCode",
        ):

            if obj.get(key):
                return str(
                    obj[key]
                ).upper()

        paths = [
            (
                "price",
                "currency",
            ),
            (
                "price",
                "currencyCode",
            ),
            (
                "sale",
                "currency",
            ),
            (
                "sale",
                "currencyCode",
            ),
        ]

        for path in paths:

            value = nested(
                obj,
                *path,
            )

            if value:
                return str(
                    value
                ).upper()

    return default


# =========================
# 颜色 / 尺码 / 库存
# =========================

def get_values(
    variant,
):

    values = variant.get(
        "values"
    )

    if not isinstance(
        values,
        dict,
    ):
        values = {}

    color = (
        values.get("color")
        or variant.get("color")
        or variant.get("colour")
        or ""
    )

    size = (
        values.get("size")
        or variant.get("size")
        or ""
    )

    return (
        str(color).strip(),
        str(size).strip(),
    )


def in_stock(
    variant,
):

    candidates = [
        variant.get(
            "availability"
        ),
        variant.get(
            "inStock"
        ),
        nested(
            variant,
            "availability",
            "inStock",
        ),
    ]

    for candidate in candidates:

        if isinstance(
            candidate,
            bool,
        ):
            return candidate

        if isinstance(
            candidate,
            dict,
        ):

            value = candidate.get(
                "inStock"
            )

            if isinstance(
                value,
                bool,
            ):
                return value

        if isinstance(
            candidate,
            str,
        ):

            return (
                candidate.lower()
                not in {
                    "outofstock",
                    "out of stock",
                    "false",
                    "unavailable",
                }
            )

    return True


def variant_key(
    variant,
):

    for key in (
        "sku",
        "id",
        "variantId",
        "variant_id",
    ):

        if variant.get(key):
            return str(
                variant[key]
            )

    color, size = get_values(
        variant
    )

    return (
        f"{color}|{size}"
    )


# =========================
# 折扣
# =========================

def calculate_discount(
    original,
    current,
):

    if (
        original
        and current is not None
        and original > 0
        and current < original
    ):

        return round(
            (
                original - current
            )
            / original
            * 100,
            1,
        )

    return None


def money(
    value,
    currency,
):

    if value is None:
        return "-"

    symbols = {
        "USD": "$",
        "CAD": "C$",
        "CNY": "¥",
    }

    symbol = symbols.get(
        currency,
        currency + " ",
    )

    return (
        f"{symbol}"
        f"{value:.2f}"
    )


# =========================
# 商品解析
# =========================

def get_product_title(
    product,
    fallback,
):

    return (
        product.get("title")
        or product.get("name")
        or fallback
    )


def get_product_variants(
    product,
    default_currency,
):

    variants = product.get(
        "variants"
    )

    if (
        not isinstance(
            variants,
            list,
        )
        or not variants
    ):
        variants = [product]

    results = []

    for variant in variants:

        if not isinstance(
            variant,
            dict,
        ):
            continue

        current = get_price(
            variant
        )

        original = get_original(
            variant
        )

        if current is None:
            continue

        color, size = get_values(
            variant
        )

        results.append(
            {
                "key": variant_key(
                    variant
                ),
                "price": current,
                "original": original,
                "currency": get_currency(
                    variant,
                    product,
                    default_currency,
                ),
                "color": (
                    color
                    or "默认颜色"
                ),
                "size": (
                    size
                    or "默认尺码"
                ),
                "stock": in_stock(
                    variant
                ),
            }
        )

    return results


# =========================
# 男装过滤
# =========================

def is_mens(
    title,
    url,
    product,
):

    text = " ".join(
        [
            str(title or ""),
            str(url or ""),
            str(
                product.get(
                    "description"
                )
                or ""
            ),
        ]
    ).lower()

    markers = [
        "men's",
        "men’s",
        "mens",
        "m's ",
        "male",
        "/mens/",
        "-mens",
    ]

    return any(
        marker in text
        for marker in markers
    )


# =========================
# Telegram
# =========================

def send_telegram(
    text,
):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "Telegram 未配置，跳过推送"
        )

        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
    )

    response = SESSION.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


# =========================
# 汇率
# =========================

def exchange_rates():

    try:

        response = SESSION.get(
            "https://open.er-api.com/"
            "v6/latest/CNY",
            timeout=20,
        )

        response.raise_for_status()

        data = response.json()

        rates = data.get(
            "rates",
            {},
        )

        return {
            "USD": float(
                rates.get(
                    "USD",
                    0,
                )
            ),
            "CAD": float(
                rates.get(
                    "CAD",
                    0,
                )
            ),
        }

    except Exception as error:

        print(
            "汇率获取失败:",
            error,
        )

        return {
            "USD": 0,
            "CAD": 0,
        }


def to_cny(
    value,
    currency,
    rates,
):

    if value is None:
        return None

    if currency == "CNY":
        return value

    rate = rates.get(
        currency,
        0,
    )

    if not rate:
        return None

    return round(
        value / rate,
        2,
    )


# =========================
# Telegram 报警
# =========================

def build_alert(
    title,
    url,
    rows,
    changed_keys,
    rates,
):

    # -------------------------
    # 第一步：
    # 找到真正发生降价的价格档
    # -------------------------

    changed_tiers = set()

    for row in rows:

        if (
            row["key"]
            not in changed_keys
        ):
            continue

        if row["previous"] is None:
            continue

        if not (
            row["price"]
            < row["previous"]
        ):
            continue

        if (
            row["discount"] is None
            or row["discount"]
            < MIN_DISCOUNT
        ):
            continue

        changed_tiers.add(
            (
                row["original"],
                row["price"],
                row["currency"],
            )
        )

    if not changed_tiers:
        return None

    # -------------------------
    # 第二步：
    # 一个价格档发生降价后，
    # 把这个价格档全部规格都显示
    # -------------------------

    groups = {}

    for row in rows:

        tier = (
            row["original"],
            row["price"],
            row["currency"],
        )

        if tier not in changed_tiers:
            continue

        groups.setdefault(
            tier,
            [],
        ).append(row)

    blocks = []

    for (
        original,
        price,
        currency,
    ), group in sorted(
        groups.items(),
        key=lambda item: -item[0][1],
    ):

        discount = (
            calculate_discount(
                original,
                price,
            )
            or 0
        )

        if discount >= 50:
            icon = "🚨"
        elif discount >= 30:
            icon = "🔥"
        else:
            icon = "🏷️"

        cny_price = to_cny(
            price,
            currency,
            rates,
        )

        lines = [
            (
                f"{icon} "
                f"{discount:.0f}% OFF"
                f"｜{title}"
            ),
            (
                f"🏷️ 原价 "
                f"{money(original, currency)}"
                f"｜💰 现价 "
                f"{money(price, currency)}"
            ),
            (
                f"💴 约 ¥"
                f"{cny_price or '-'}"
            ),
            "",
        ]

        # 按颜色分组
        colors = list(
            dict.fromkeys(
                row["color"]
                for row in group
            )
        )

        lines.append(
            "颜色｜"
            + "  |  ".join(
                colors
            )
        )

        for color in colors:

            color_rows = [
                row
                for row in group
                if row["color"]
                == color
            ]

            sizes = list(
                dict.fromkeys(
                    row["size"]
                    for row in color_rows
                )
            )

            stock_text = list(
                dict.fromkeys(
                    (
                        "有货"
                        if row["stock"]
                        else "无货"
                    )
                    for row in color_rows
                )
            )

            lines.append(
                f"尺码｜{color}："
                + " ".join(
                    sizes
                )
            )

            lines.append(
                f"库存｜{color}："
                + " ".join(
                    stock_text
                )
            )

        lines.append("")
        lines.append(url)

        blocks.append(
            "\n".join(lines)
        )

    return (
        "\n\n"
        "━━━━━━━━━━━━"
        "\n\n"
    ).join(
        blocks
    )


# =========================
# 自动发现
# =========================

def discover_urls(
    history,
):

    fixed_urls = {
        url.rstrip("/")
        for _, url
        in FIXED_PRODUCTS
    }

    # -------------------------
    # 清理历史中的分类页
    # -------------------------

    cleaned = []

    for item in history.get(
        "discovered_products",
        [],
    ):

        if isinstance(
            item,
            dict,
        ):

            url = item.get(
                "url",
                "",
            )

            if is_product_url(
                url
            ):
                cleaned.append(
                    item
                )

        elif isinstance(
            item,
            str,
        ):

            if is_product_url(
                item
            ):
                cleaned.append(
                    {
                        "url": item,
                        "source": "旧记录",
                        "currency": "USD",
                    }
                )

    history[
        "discovered_products"
    ] = cleaned

    existing = {
        item["url"].rstrip("/")
        for item in cleaned
        if isinstance(
            item,
            dict,
        )
        and item.get("url")
    }

    new_items = []

    for (
        source,
        page,
        currency,
    ) in DISCOVERY_PAGES:

        try:

            print(
                f"发现扫描：{source}"
            )

            markdown = discovery_scrape(
                page
            )

            urls = extract_product_links(
                markdown,
                page,
            )

            print(
                f"发现 {len(urls)} 个商品链接："
                f"{source}"
            )

            for url in urls:

                clean_url = url.rstrip(
                    "/"
                )

                if clean_url in fixed_urls:
                    continue

                if clean_url in existing:
                    continue

                if not is_product_url(
                    clean_url
                ):
                    continue

                existing.add(
                    clean_url
                )

                new_items.append(
                    {
                        "url": clean_url,
                        "source": source,
                        "currency": currency,
                    }
                )

            time.sleep(
                REQUEST_INTERVAL
            )

        except Exception as error:

            print(
                f"发现失败 {source}: "
                f"{error}"
            )

    history[
        "discovered_products"
    ].extend(
        new_items
    )

    print(
        "本次新增发现商品：",
        len(new_items)
    )

    return history


# =========================
# 检查单个商品
# =========================

def process_one(
    name,
    url,
    history,
    default_currency,
    is_auto=False,
    rates=None,
):

    print(
        f"检查：{name}"
    )

    try:

        # 自动发现再次检查 URL
        # 防止历史里残留分类页
        if is_auto and not is_product_url(
            url
        ):

            print(
                "跳过非商品链接：",
                url,
            )

            return

        product = product_scrape(
            url
        )

        title = get_product_title(
            product,
            name,
        )

        # 自动发现只保留男装
        if (
            is_auto
            and not is_mens(
                title,
                url,
                product,
            )
        ):

            print(
                "跳过非男装：",
                title,
            )

            return

        rows = get_product_variants(
            product,
            default_currency,
        )

        if not rows:

            print(
                "没有提取到价格"
            )

            return

        if is_auto:

            history_key = (
                f"auto:{url}"
            )

        else:

            history_key = name

        previous = (
            history["products"]
            .get(
                history_key,
                {},
            )
            .get(
                "variants",
                {},
            )
        )

        changed_keys = set()

        for row in rows:

            old = previous.get(
                row["key"],
                {},
            )

            old_price = old.get(
                "price"
            )

            row["previous"] = (
                old_price
            )

            row["discount"] = (
                calculate_discount(
                    row["original"],
                    row["price"],
                )
            )

            # 只有实际当前售价下降
            if (
                old_price is not None
                and row["price"]
                < old_price
            ):

                changed_keys.add(
                    row["key"]
                )

        alert = build_alert(
            title,
            url,
            rows,
            changed_keys,
            rates or {},
        )

        if alert:

            send_telegram(
                alert
            )

            print(
                "已推送：",
                title,
            )

        # 保存最新价格
        history[
            "products"
        ][history_key] = {
            "title": title,
            "url": url,
            "updated": int(
                time.time()
            ),
            "variants": {
                row["key"]: {
                    "price": row[
                        "price"
                    ],
                    "original": row[
                        "original"
                    ],
                    "currency": row[
                        "currency"
                    ],
                    "color": row[
                        "color"
                    ],
                    "size": row[
                        "size"
                    ],
                    "stock": row[
                        "stock"
                    ],
                }
                for row in rows
            },
        }

    except Exception as error:

        print(
            "商品检查失败：",
            error,
        )


# =========================
# 主程序
# =========================

def main():

    if not FIRECRAWL_API_KEY:

        raise SystemExit(
            "缺少 FIRECRAWL_API_KEY"
        )

    history = load_history()

    rates = exchange_rates()

    # -------------------------
    # 1. 扫描所有官网
    # -------------------------

    history = discover_urls(
        history
    )

    # -------------------------
    # 2. 7 个重点商品轮询
    # 每次 4 个
    # -------------------------

    start = (
        history["position"]
        % len(FIXED_PRODUCTS)
    )

    fixed_batch = [
        FIXED_PRODUCTS[
            (start + i)
            % len(FIXED_PRODUCTS)
        ]
        for i in range(
            BATCH_SIZE
        )
    ]

    for (
        name,
        url,
    ) in fixed_batch:

        process_one(
            name,
            url,
            history,
            "USD",
            False,
            rates,
        )

        time.sleep(
            REQUEST_INTERVAL
        )

    history["position"] = (
        start
        + len(fixed_batch)
    ) % len(FIXED_PRODUCTS)

    # -------------------------
    # 3. 自动发现商品
    # 每次 6 个
    # -------------------------

    discovered = history.get(
        "discovered_products",
        [],
    )

    if discovered:

        start = (
            history[
                "discovery_position"
            ]
            % len(discovered)
        )

        count = min(
            DISCOVERY_BATCH_SIZE,
            len(discovered),
        )

        batch = [
            discovered[
                (start + i)
                % len(discovered)
            ]
            for i in range(
                count
            )
        ]

        for item in batch:

            process_one(
                item["url"],
                item["url"],
                history,
                item.get(
                    "currency",
                    "USD",
                ),
                True,
                rates,
            )

            time.sleep(
                REQUEST_INTERVAL
            )

        history[
            "discovery_position"
        ] = (
            start + count
        ) % len(discovered)

    # -------------------------
    # 4. 保存历史
    # -------------------------

    save_history(
        history
    )

    print(
        "本次运行完成"
    )


if __name__ == "__main__":
    main()
