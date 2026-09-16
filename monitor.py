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

# Firecrawl 限流保护
FIRECRAWL_DELAY = 10
RATE_LIMIT_WAIT = 35
FIRECRAWL_TIMEOUT = 90

# 每次自动发现最多增加几个商品
DISCOVERY_LIMIT = 5

# 每次运行检查几个固定商品
FIXED_ROTATION = 4

# ============================================================
# 折扣判断
# ============================================================

MIN_DISCOUNT = 20

# 重要优惠门槛
IMPORTANT_DISCOUNT = 20

# 超值门槛
SUPER_DISCOUNT = 50


# ============================================================
# 数据文件
# ============================================================

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "prices.json"


# ============================================================
# HTTP Session
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/130.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


# ============================================================
# 固定重点商品
# ============================================================

FIXED_PRODUCTS = [
    {
        "name": "Arc'teryx Gamma MX Hoody - Men's",
        "url": "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens",
        "source": "REI",
    },
    {
        "name": "Arc'teryx Gamma Jacket - Men's",
        "url": "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens",
        "source": "REI",
    },
    {
        "name": "Arc'teryx Gamma Pants - Men's",
        "url": "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens",
        "source": "REI",
    },
    {
        "name": "Patagonia R2 TechFace Jacket - Men's",
        "url": "https://www.rei.com/product/222148/patagonia-r2-techface-jacket-mens",
        "source": "REI",
    },
    {
        "name": "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "url": "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
        "source": "REI",
    },
    {
        "name": "Arc'teryx Atom Insulated Jacket - Men's",
        "url": "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
        "source": "REI",
    },
    {
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
        "source": "REI",
    },
]


# ============================================================
# 自动发现来源
# ============================================================

DISCOVERY_SOURCES = [
    {
        "name": "REI",
        "url": "https://www.rei.com/c/mens-clothing/f/scd-deals",
    },
    {
        "name": "Arc'teryx US Outlet",
        "url": "https://outlet.arcteryx.com/us/en/shop/mens",
    },
    {
        "name": "Arc'teryx Canada",
        "url": "https://arcteryx.com/ca/en/c/mens",
    },
    {
        "name": "Patagonia US",
        "url": "https://www.patagonia.com/shop/mens",
    },
    {
        "name": "Patagonia Canada",
        "url": "https://www.patagonia.ca/shop/mens",
    },
    {
        "name": "The North Face US",
        "url": "https://www.thenorthface.com/en-us/c/mens",
    },
    {
        "name": "The North Face Canada",
        "url": "https://www.thenorthface.com/en-ca/c/men",
    },
]


# ============================================================
# 排除商品
# ============================================================

EXCLUDED_URLS = {
    "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
}


EXCLUDED_NAMES = {
    "Patagonia R2 TechFace Hoody - Men's",
}


# ============================================================
# 通用工具
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)

    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def first_value(data, keys):
    if not isinstance(data, dict):
        return ""

    for key in keys:
        value = data.get(key)

        if value is not None:
            value = clean_text(value)

            if value:
                return value

    return ""


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = clean_text(value)

    if not text:
        return None

    text = text.replace(",", "")

    match = re.search(
        r"[-+]?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


# ============================================================
# The North Face 商品名称备用解析
# ============================================================

def title_from_url(url):
    """
    当 Firecrawl 没有返回 title/name 时，
    从商品 URL 自动生成商品名称。

    例如：

    mens-1996-retro-nuptse-jacket-NF0A3C8D

    ->
    
    1996 Retro Nuptse Jacket - Men's
    """

    if not url:
        return ""

    try:
        path = urlparse(url).path

        slug = path.rstrip("/").rsplit("/", 1)[-1]

        if not slug:
            return ""

        # 删除 TNF 商品编号
        slug = re.sub(
            r"-[A-Z0-9]{6,}$",
            "",
            slug,
            flags=re.I
        )

        # 删除纯数字商品编号
        slug = re.sub(
            r"-\d{5,}$",
            "",
            slug,
            flags=re.I
        )

        words = slug.replace("-", " ").split()

        if not words:
            return ""

        result = " ".join(words)

        # 删除男性标记
        result = re.sub(
            r"\bmens\b",
            "",
            result,
            flags=re.I
        )

        result = re.sub(
            r"\bmen's\b",
            "",
            result,
            flags=re.I
        )

        result = re.sub(
            r"\bmen\b",
            "",
            result,
            flags=re.I
        )

        result = clean_text(result)

        if not result:
            return ""

        return result.title() + " - Men's"

    except Exception:
        return ""


def get_product_title(product, fallback="", url=""):
    """
    商品名称优先级：

    1. Firecrawl product.title
    2. Firecrawl product.name
    3. 其他标题字段
    4. 已有商品名称
    5. URL 自动生成名称
    """

    if not isinstance(product, dict):
        product = {}

    title = first_value(
        product,
        [
            "title",
            "name",
            "productName",
            "product_title",
        ]
    )

    if title:
        return clean_text(title)

    if fallback:
        fallback = clean_text(fallback)

        if fallback:
            return fallback

    generated = title_from_url(url)

    if generated:
        return generated

    return ""


# ============================================================
# 自动发现服装过滤
# ============================================================

def is_allowed_discovery_product(url):
    """
    自动发现只允许：

    上衣：
    - 夹克
    - 软壳
    - 冲锋衣
    - 羽绒服

    裤子：
    - 长裤
    - 软壳裤
    - 冲锋裤

    排除：
    - 鞋
    - 包
    - 帽子
    - 手套
    - 袜子
    - 行李
    - 装备
    - 户外用品
    - 配件
    - T恤
    - 卫衣
    - Polo
    """

    if not url:
        return False

    try:
        path = urlparse(url).path.lower()

        text = path.replace("-", " ")

        # ----------------------------------------------------
        # 明确排除的非服装
        # ----------------------------------------------------

        excluded_words = [
            "/bags/",
            "/backpacks/",
            "/luggage/",
            "/travel/",
            "/gear/",
            "/equipment/",
            "/camping/",
            "/accessories/",
            "/footwear/",
            "/shoes/",
            "/sandals/",
            "/boots/",
            "/hats/",
            "/gloves/",
            "/socks/",
        ]

        for word in excluded_words:
            if word in path:
                return False

        excluded_text_words = [
            "backpack",
            "luggage",
            "travel canister",
            "sandals",
            "shoes",
            "boots",
            "hat",
            "gloves",
            "socks",
            "camping",
            "equipment",
        ]

        for word in excluded_text_words:
            if word in text:
                return False

        # ----------------------------------------------------
        # 裤子
        # ----------------------------------------------------

        if (
            "pants" in text
            or "trousers" in text
        ):
            return True

        # ----------------------------------------------------
        # 夹克
        # ----------------------------------------------------

        if "jacket" in text:
            return True

        # ----------------------------------------------------
        # 软壳 / 冲锋衣
        # ----------------------------------------------------

        shell_words = [
            "softshell",
            "soft shell",
            "hardshell",
            "hard shell",
            "rain shell",
            "rain-shell",
        ]

        for word in shell_words:
            if word in text and "jacket" in text:
                return True

        # ----------------------------------------------------
        # 羽绒服
        # 要求同时包含 down + jacket
        # 避免误收 down vest 等
        # ----------------------------------------------------

        if (
            "down" in text
            and "jacket" in text
        ):
            return True

        return False

    except Exception:
        return False


# ============================================================
# Firecrawl
# ============================================================

def firecrawl(url, formats=None):
    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")

        return None

    if formats is None:
        formats = ["product"]

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": url,
        "formats": formats,
        "waitFor": 3000,
    }

    for attempt in range(3):

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

            if response.status_code == 200:

                try:
                    return response.json()
                except Exception:
                    print("Firecrawl 返回不是 JSON")
                    return None

            if response.status_code == 429:

                print(
                    f"Firecrawl 限流，等待 {RATE_LIMIT_WAIT} 秒..."
                )

                time.sleep(RATE_LIMIT_WAIT)

                continue

            if response.status_code >= 500:

                wait_time = 10 * (attempt + 1)

                print(
                    f"Firecrawl 服务器错误，等待 {wait_time} 秒..."
                )

                time.sleep(wait_time)

                continue

            print(
                "Firecrawl 请求失败：",
                response.text[:500]
            )

            return None

        except requests.RequestException as exc:

            print(
                "Firecrawl 网络错误：",
                exc
            )

            time.sleep(
                10 * (attempt + 1)
            )

    return None


# ============================================================
# 商品抓取
# ============================================================

def product_scrape(url):

    result = firecrawl(
        url,
        formats=["product"]
    )

    if not result:
        return None

    data = result.get("data")

    if not isinstance(data, dict):
        return None

    product = data.get("product")

    if isinstance(product, dict):
        return product

    # 某些情况下 product 直接就在 data
    product_keys = [
        "title",
        "name",
        "variants",
        "price",
        "pricing",
    ]

    if any(
        key in data
        for key in product_keys
    ):
        return data

    return None


# ============================================================
# 价格解析
# ============================================================

def extract_price(product):

    if not isinstance(product, dict):
        return None

    possible_values = [
        product.get("price"),
        product.get("currentPrice"),
        product.get("salePrice"),
        product.get("amount"),
    ]

    for value in possible_values:

        price = safe_float(value)

        if price is not None:
            return price

    pricing = product.get("pricing")

    if isinstance(pricing, dict):

        for key in [
            "price",
            "current",
            "sale",
            "amount",
        ]:

            price = safe_float(
                pricing.get(key)
            )

            if price is not None:
                return price

    return None


def extract_original_price(product):

    if not isinstance(product, dict):
        return None

    possible_values = [
        product.get("originalPrice"),
        product.get("listPrice"),
        product.get("regularPrice"),
        product.get("compareAtPrice"),
        product.get("wasPrice"),
    ]

    for value in possible_values:

        price = safe_float(value)

        if price is not None:
            return price

    pricing = product.get("pricing")

    if isinstance(pricing, dict):

        for key in [
            "original",
            "list",
            "regular",
            "compareAt",
            "was",
        ]:

            price = safe_float(
                pricing.get(key)
            )

            if price is not None:
                return price

    return None


# ============================================================
# 币种
# ============================================================

def extract_currency(product):

    if not isinstance(product, dict):
        return ""

    value = first_value(
        product,
        [
            "currency",
            "currencyCode",
        ]
    )

    if value:
        return value.upper()

    pricing = product.get("pricing")

    if isinstance(pricing, dict):

        value = first_value(
            pricing,
            [
                "currency",
                "currencyCode",
            ]
        )

        if value:
            return value.upper()

    return ""


# ============================================================
# 颜色 / 尺码 / 库存
# ============================================================

def normalize_list(value):

    if value is None:
        return []

    if isinstance(value, list):

        result = []

        for item in value:

            text = clean_text(item)

            if text:
                result.append(text)

        return result

    if isinstance(value, str):

        parts = re.split(
            r"[,/|]",
            value
        )

        return [
            clean_text(x)
            for x in parts
            if clean_text(x)
        ]

    return []


def extract_variants(product):

    if not isinstance(product, dict):
        return []

    variants = product.get("variants")

    if not isinstance(variants, list):
        return []

    result = []

    for variant in variants:

        if not isinstance(variant, dict):
            continue

        color = first_value(
            variant,
            [
                "color",
                "colour",
                "colorName",
                "colourName",
            ]
        )

        size = first_value(
            variant,
            [
                "size",
                "sizeName",
            ]
        )

        price = None

        for key in [
            "price",
            "currentPrice",
            "salePrice",
            "amount",
        ]:

            price = safe_float(
                variant.get(key)
            )

            if price is not None:
                break

        original_price = None

        for key in [
            "originalPrice",
            "listPrice",
            "regularPrice",
            "compareAtPrice",
            "wasPrice",
        ]:

            original_price = safe_float(
                variant.get(key)
            )

            if original_price is not None:
                break

        stock_value = variant.get("availability")

        if stock_value is None:
            stock_value = variant.get("inStock")

        if stock_value is None:
            stock_value = variant.get("stock")

        stock = clean_text(stock_value)

        result.append({
            "color": color,
            "size": size,
            "price": price,
            "original_price": original_price,
            "stock": stock,
        })

    return result


# ============================================================
# 折扣计算
# ============================================================

def discount_percent(original_price, current_price):

    if (
        original_price is None
        or current_price is None
    ):
        return 0.0

    if original_price <= 0:
        return 0.0

    if current_price >= original_price:
        return 0.0

    discount = (
        (original_price - current_price)
        / original_price
        * 100
    )

    return round(
        discount,
        1
    )


# ============================================================
# 男装判断
# ============================================================

def is_mens_product(title):

    if not title:
        return False

    text = clean_text(title).lower()

    return any(
        marker in text
        for marker in [
            "men's",
            "mens",
            "men’s",
        ]
    )


# ============================================================
# 排除商品判断
# ============================================================

def is_excluded_product(
    url,
    title,
):

    if url in EXCLUDED_URLS:
        return True

    title_clean = clean_text(title)

    if title_clean in EXCLUDED_NAMES:
        return True

    if "r2 techface hoody" in title_clean.lower():
        return True

    return False


# ============================================================
# URL 判断
# ============================================================

def is_product_url(
    url,
    source_name,
):

    if not url:
        return False

    try:

        parsed = urlparse(url)

        host = parsed.netloc.lower()
        path = parsed.path.lower()

        # ----------------------------------------------------
        # REI
        # ----------------------------------------------------

        if "rei.com" in host:

            return "/product/" in path

        # ----------------------------------------------------
        # Arc'teryx Outlet
        # ----------------------------------------------------

        if "outlet.arcteryx.com" in host:

            if "/shop/mens/" not in path:
                return False

            bad_words = [
                "/category/",
                "/collections/",
                "/shop/",
            ]

            for word in bad_words:

                if word in path:
                    continue

            return True

        # ----------------------------------------------------
        # Arc'teryx 正式网站
        # ----------------------------------------------------

        if "arcteryx.com" in host:

            return (
                "/product/" in path
                or "/shop/" in path
                or "/c/" in path
            )

        # ----------------------------------------------------
        # Patagonia
        # ----------------------------------------------------

        if "patagonia.com" in host:
            return (
                "/product/" in path
                or "/shop/" in path
            )

        # ----------------------------------------------------
        # Patagonia Canada
        # ----------------------------------------------------

        if "patagonia.ca" in host:
            return (
                "/product/" in path
                or "/shop/" in path
            )

        # ----------------------------------------------------
        # The North Face
        # ----------------------------------------------------

        if "thenorthface.com" in host:

            if "/c/" in path:
                return False

            if "/p/" in path:
                return True

            if "/product/" in path:
                return True

            return bool(
                re.search(
                    r"-[a-z0-9]{5,}$",
                    path
                )
            )

        return False

    except Exception:
        return False


# ============================================================
# 自动发现链接
# ============================================================

def discover_links(source):

    source_name = source["name"]
    source_url = source["url"]

    print(
        f"发现扫描：{source_name}"
    )

    result = firecrawl(
        source_url,
        formats=["markdown"]
    )

    if not result:
        return []

    data = result.get("data")

    if not isinstance(data, dict):
        return []

    markdown = data.get("markdown") or ""
    html = data.get("html") or ""

    raw_text = (
        markdown
        + "\n"
        + html
    )

    links = set()

    # --------------------------------------------------------
    # markdown 链接
    # --------------------------------------------------------

    markdown_links = re.findall(
        r"\]\((https?://[^)\s]+)\)",
        markdown
    )

    for link in markdown_links:
        links.add(link)

    # --------------------------------------------------------
    # HTML href
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    for a in soup.find_all("a"):

        href = a.get("href")

        if not href:
            continue

        href = clean_text(href)

        if href.startswith("/"):
            href = urljoin(
                source_url,
                href
            )

        if href.startswith("http"):
            links.add(href)

    # --------------------------------------------------------
    # 直接正则提取 URL
    # --------------------------------------------------------

    urls = re.findall(
        r'https?://[^\s"\'<>]+',
        raw_text
    )

    for url in urls:

        url = url.rstrip(
            '.,);]}>"\''
        )

        links.add(url)

    # --------------------------------------------------------
    # 最终过滤
    # --------------------------------------------------------

    result_links = []

    for url in links:

        if not is_product_url(
            url,
            source_name
        ):
            continue

        result_links.append(url)

    result_links = list(
        dict.fromkeys(
            result_links
        )
    )

    print(
        f"发现 {len(result_links)} 个商品链接：{source_name}"
    )

    return result_links


# ============================================================
# 加载价格历史
# ============================================================

def load_history():

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if not DATA_FILE.exists():
        return {}

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(data, dict):
                return data

    except Exception as exc:

        print(
            "读取价格历史失败：",
            exc
        )

    return {}


# ============================================================
# 保存历史
# ============================================================

def save_history(history):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = DATA_FILE.with_suffix(
        ".tmp"
    )

    try:

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                history,
                f,
                ensure_ascii=False,
                indent=2
            )

        temp_file.replace(
            DATA_FILE
        )

        print(
            "价格历史保存成功"
        )

    except Exception as exc:

        print(
            "保存价格历史失败：",
            exc
        )


# ============================================================
# 获取上次价格
# ============================================================

def get_previous_price(
    history,
    url
):

    item = history.get(url)

    if not isinstance(item, dict):
        return None

    value = item.get(
        "current_min"
    )

    return safe_float(value)


# ============================================================
# 当前商品整理
# ============================================================

def build_current_product(
    product,
    item,
):

    title = get_product_title(
        product,
        item.get("name", ""),
        item.get("url", ""),
    )

    price = extract_price(
        product
    )

    original_price = extract_original_price(
        product
    )

    currency = extract_currency(
        product
    )

    variants = extract_variants(
        product
    )

    # --------------------------------------------------------
    # 如果没有 variants
    # 用主商品价格构造一个
    # --------------------------------------------------------

    if not variants and price is not None:

        variants = [
            {
                "color": "",
                "size": "",
                "price": price,
                "original_price": original_price,
                "stock": "",
            }
        ]

    # --------------------------------------------------------
    # 补齐 variants 中缺失的价格
    # --------------------------------------------------------

    for variant in variants:

        if variant.get("price") is None:
            variant["price"] = price

        if (
            variant.get("original_price")
            is None
        ):
            variant["original_price"] = (
                original_price
            )

    return {
        "name": title,
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "currency": currency,
        "price": price,
        "original_price": original_price,
        "variants": variants,
    }


# ============================================================
# 价格组
# ============================================================

def build_price_groups(
    product
):

    groups = {}

    currency = product.get(
        "currency"
    ) or ""

    for variant in product.get(
        "variants",
        []
    ):

        price = variant.get(
            "price"
        )

        original = variant.get(
            "original_price"
        )

        if price is None:
            continue

        discount = discount_percent(
            original,
            price
        )

        key = (
            currency,
            price
        )

        if key not in groups:
            groups[key] = {
                "currency": currency,
                "price": price,
                "original_price": original,
                "discount": discount,
                "colors": [],
            }

        color = variant.get(
            "color",
            ""
        )

        size = variant.get(
            "size",
            ""
        )

        stock = variant.get(
            "stock",
            ""
        )

        groups[key]["colors"].append({
            "color": color,
            "size": size,
            "stock": stock,
        })

    return list(
        groups.values()
    )


# ============================================================
# 最低实际价格
# ============================================================

def get_min_actual_price(
    product
):

    prices = []

    for variant in product.get(
        "variants",
        []
    ):

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


# ============================================================
# 最大折扣
# ============================================================

def get_max_discount(
    product
):

    discounts = []

    for variant in product.get(
        "variants",
        []
    ):

        discount = discount_percent(
            variant.get(
                "original_price"
            ),
            variant.get(
                "price"
            )
        )

        discounts.append(
            discount
        )

    if not discounts:
        return 0.0

    return max(discounts)


# ============================================================
# Telegram 消息
# ============================================================

def build_product_message(
    product
):

    title = product.get(
        "name",
        "未知商品"
    )

    url = product.get(
        "url",
        ""
    )

    currency = product.get(
        "currency",
        ""
    )

    groups = build_price_groups(
        product
    )

    # 只显示达到 20% 的折扣
    groups = [
        group
        for group in groups
        if group["discount"] >= MIN_DISCOUNT
    ]

    if not groups:
        return None

    max_discount = max(
        group["discount"]
        for group in groups
    )

    if max_discount >= SUPER_DISCOUNT:

        icon = "🚨"
        label = "超级优惠"

    elif max_discount >= IMPORTANT_DISCOUNT:

        icon = "🔥"
        label = "重要优惠"

    else:

        icon = "🏷️"
        label = "优惠"

    lines = []

    lines.append(
        f"{icon} {max_discount:.0f}% OFF｜{title}"
    )

    if max_discount >= SUPER_DISCOUNT:
        lines.append(
            "⭐ 超级优惠"
        )

    for group in groups:

        price = group["price"]
        original = group["original_price"]

        if original is None:
            original = price

        drop = original - price

        lines.append(
            f"🏷️ 原价 {currency} {original:.2f}"
            f"｜💰 现价 {currency} {price:.2f}"
        )

        lines.append(
            f"📉 降价 {currency} {drop:.2f}"
            f"（{currency} {original:.2f}"
            f" → {currency} {price:.2f}）"
        )

        color_map = {}

        for item in group["colors"]:

            color = item.get(
                "color"
            ) or "默认颜色"

            size = item.get(
                "size"
            ) or ""

            stock = item.get(
                "stock"
            ) or ""

            if color not in color_map:
                color_map[color] = {
                    "sizes": [],
                    "stock": [],
                }

            if size:
                color_map[color]["sizes"].append(
                    size
                )

            if stock:
                color_map[color]["stock"].append(
                    stock
                )

        if color_map:

            colors = list(
                color_map.keys()
            )

            lines.append(
                "颜色       "
                + "       ".join(colors)
            )

            size_parts = []

            stock_parts = []

            for color in colors:

                sizes = list(
                    dict.fromkeys(
                        color_map[color]["sizes"]
                    )
                )

                stocks = list(
                    dict.fromkeys(
                        color_map[color]["stock"]
                    )
                )

                size_parts.append(
                    " ".join(sizes)
                    if sizes
                    else "-"
                )

                stock_parts.append(
                    " ".join(stocks)
                    if stocks
                    else "-"
                )

            lines.append(
                "尺码       "
                + "       ".join(size_parts)
            )

            lines.append(
                "库存       "
                + "       ".join(stock_parts)
            )

    lines.append(
        ""
    )

    lines.append(
        "━━━━━━━━━━━━"
    )

    lines.append(
        ""
    )

    lines.append(
        f"🔗 {url}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# Telegram 推送
# ============================================================

def telegram_send(
    message
):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "没有 TELEGRAM_BOT_TOKEN"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "没有 TELEGRAM_CHAT_ID"
        )
        return False

    telegram_url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:

        response = SESSION.post(
            telegram_url,
            json=payload,
            timeout=30,
        )

        if response.status_code == 200:

            print(
                "Telegram 推送成功"
            )

            return True

        print(
            "Telegram 推送失败：",
            response.status_code,
            response.text[:500]
        )

    except Exception as exc:

        print(
            "Telegram 网络错误：",
            exc
        )

    return False


# ============================================================
# 是否应该推送
# ============================================================

def should_alert(
    product,
    previous_price,
):

    current_price = get_min_actual_price(
        product
    )

    if current_price is None:
        print(
            "没有有效实际价格：不推送"
        )
        return False

    # --------------------------------------------------------
    # 第一次发现
    # --------------------------------------------------------

    if previous_price is None:

        print(
            "首次发现商品：不推送"
        )

        return False

    # --------------------------------------------------------
    # 价格不变
    # --------------------------------------------------------

    if current_price == previous_price:

        print(
            "实际现价没有变化：不推送"
        )

        return False

    # --------------------------------------------------------
    # 价格上涨
    # --------------------------------------------------------

    if current_price > previous_price:

        print(
            f"实际价格上涨："
            f"{previous_price:.2f}"
            f" → "
            f"{current_price:.2f}"
            f"：不推送"
        )

        return False

    # --------------------------------------------------------
    # 价格下降
    # --------------------------------------------------------

    print(
        f"实际价格下降："
        f"{previous_price:.2f}"
        f" → "
        f"{current_price:.2f}"
    )

    max_discount = get_max_discount(
        product
    )

    print(
        f"当前最大折扣："
        f"{max_discount:.1f}%"
    )

    # --------------------------------------------------------
    # 价格下降 + 折扣 >= 20%
    # --------------------------------------------------------

    if max_discount >= IMPORTANT_DISCOUNT:

        print(
            "满足推送条件："
            "价格下降 + 折扣达到 20%"
        )

        return True

    print(
        "价格下降，但折扣低于 20%：不推送"
    )

    return False


# ============================================================
# 保存单个商品历史
# ============================================================

def save_product_history(
    history,
    product
):

    url = product.get(
        "url"
    )

    if not url:
        return

    current_price = get_min_actual_price(
        product
    )

    max_discount = get_max_discount(
        product
    )

    history[url] = {
        "name": product.get(
            "name",
            ""
        ),
        "source": product.get(
            "source",
            ""
        ),
        "current_min": current_price,
        "max_discount": max_discount,
        "currency": product.get(
            "currency",
            ""
        ),
    }


# ============================================================
# 检查商品
# ============================================================

def check_product(
    item,
    history,
):

    url = item.get(
        "url",
        ""
    )

    print(
        "检查：",
        item.get(
            "name",
            ""
        )
    )

    product_data = product_scrape(
        url
    )

    if not product_data:

        print(
            "商品抓取失败：跳过"
        )

        return

    # --------------------------------------------------------
    # 修复 The North Face 商品名称为空
    # --------------------------------------------------------

    title = get_product_title(
        product_data,
        item.get("name", ""),
        url,
    )

    if not title:

        print(
            "无法识别商品名称：跳过"
        )

        return

    # --------------------------------------------------------
    # 排除商品
    # --------------------------------------------------------

    if is_excluded_product(
        url,
        title
    ):

        print(
            "跳过排除商品：",
            title
        )

        return

    # --------------------------------------------------------
    # 自动发现商品必须是男装
    # --------------------------------------------------------

    if item.get(
        "discovered",
        False
    ):

        if not is_mens_product(
            title
        ):

            print(
                "跳过非男装：",
                title
            )

            return

    # --------------------------------------------------------
    # 构建商品
    # --------------------------------------------------------

    product = build_current_product(
        product_data,
        {
            **item,
            "name": title,
        }
    )

    current_price = get_min_actual_price(
        product
    )

    if current_price is None:

        print(
            "没有实际价格：跳过"
        )

        return

    print(
        f"当前最低实际价格："
        f"{current_price:.2f}"
    )

    previous_price = get_previous_price(
        history,
        url
    )

    if previous_price is not None:

        print(
            f"上次实际价格："
            f"{previous_price:.2f}"
        )

    # --------------------------------------------------------
    # 判断是否推送
    # --------------------------------------------------------

    if should_alert(
        product,
        previous_price
    ):

        message = build_product_message(
            product
        )

        if message:

            print(
                "准备发送 Telegram："
            )

            print(
                message
            )

            telegram_send(
                message
            )

    # --------------------------------------------------------
    # 无论是否推送，都保存最新价格
    # --------------------------------------------------------

    save_product_history(
        history,
        product
    )


# ============================================================
# 自动发现商品
# ============================================================

def discovery_products(
    history
):

    known_urls = set(
        history.keys()
    )

    for item in FIXED_PRODUCTS:

        known_urls.add(
            item["url"]
        )

    for url in EXCLUDED_URLS:

        known_urls.add(
            url
        )

    discovered = []

    # --------------------------------------------------------
    # 每次运行只轮换 2 个来源
    # --------------------------------------------------------

    if not DISCOVERY_SOURCES:
        return []

    history_count = len(
        history
    )

    start_index = (
        history_count
        // max(
            1,
            DISCOVERY_LIMIT
        )
    ) % len(
        DISCOVERY_SOURCES
    )

    selected_sources = []

    for i in range(
        min(
            2,
            len(DISCOVERY_SOURCES)
        )
    ):

        index = (
            start_index + i
        ) % len(
            DISCOVERY_SOURCES
        )

        selected_sources.append(
            DISCOVERY_SOURCES[index]
        )

    # --------------------------------------------------------
    # 扫描
    # --------------------------------------------------------

    for source in selected_sources:

        links = discover_links(
            source
        )

        for url in links:

            if url in known_urls:
                continue

            # ------------------------------------------------
            # 关键优化：
            # 在 Firecrawl 商品详情前先过滤
            # ------------------------------------------------

            if not is_allowed_discovery_product(
                url
            ):

                print(
                    "跳过非目标服装：",
                    url
                )

                continue

            known_urls.add(
                url
            )

            discovered.append({
                "name": "",
                "url": url,
                "source": source["name"],
                "discovered": True,
            })

            if len(discovered) >= DISCOVERY_LIMIT:

                break

        if len(discovered) >= DISCOVERY_LIMIT:

            break

    print(
        f"本次新增发现商品："
        f"{len(discovered)}"
    )

    return discovered


# ============================================================
# 固定商品轮换
# ============================================================

def get_rotation_products():

    total = len(
        FIXED_PRODUCTS
    )

    if total == 0:
        return []

    history = load_history()

    rotation_seed = len(
        history
    )

    start = (
        rotation_seed
        % total
    )

    result = []

    for i in range(
        min(
            FIXED_ROTATION,
            total
        )
    ):

        index = (
            start + i
        ) % total

        result.append(
            {
                **FIXED_PRODUCTS[index],
                "discovered": False,
            }
        )

    return result


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
    # 自动发现
    # --------------------------------------------------------

    discovered = discovery_products(
        history
    )

    # --------------------------------------------------------
    # 固定商品
    # --------------------------------------------------------

    fixed_products = get_rotation_products()

    # --------------------------------------------------------
    # 合并
    # --------------------------------------------------------

    products = []

    seen = set()

    for item in (
        fixed_products
        + discovered
    ):

        url = item.get(
            "url"
        )

        if not url:
            continue

        if url in seen:
            continue

        seen.add(
            url
        )

        products.append(
            item
        )

    print(
        f"本次检查商品数量："
        f"{len(products)}"
    )

    # --------------------------------------------------------
    # 逐个检查
    # --------------------------------------------------------

    for index, item in enumerate(
        products,
        start=1
    ):

        print(
            f"\n========== "
            f"{index}/{len(products)} "
            f"=========="
        )

        try:

            check_product(
                item,
                history
            )

        except Exception as exc:

            print(
                "检查商品发生异常：",
                exc
            )

        # ----------------------------------------------------
        # Firecrawl 限流保护
        # ----------------------------------------------------

        if index < len(products):

            print(
                f"等待 {FIRECRAWL_DELAY} 秒，"
                f"避免 Firecrawl 限流..."
            )

            time.sleep(
                FIRECRAWL_DELAY
            )

    # --------------------------------------------------------
    # 保存历史
    # --------------------------------------------------------

    save_history(
        history
    )

    print(
        "本次运行完成"
    )

    print(
        "=========="
    )


# ============================================================
# 程序入口
# ============================================================

if __name__ == "__main__":
    main()
