import os
import re
import json
import time
import html
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# 基础配置
# ============================================================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

MIN_DISCOUNT = 20
IMPORTANT_DISCOUNT = 20
SUPER_DISCOUNT = 50

# 每30分钟检查一次时，5个固定商品全部检查
FIXED_ROTATION = 5

# Firecrawl 限流保护
FIRECRAWL_DELAY = 10

# 自动发现
DISCOVERY_LIMIT = 5

DATA_FILE = Path("data/prices.json")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 16) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36"
        )
    }
)


# ============================================================
# 固定监控商品
# ============================================================

FIXED_PRODUCTS = [
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
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
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
# 允许品牌 / 分类
# ============================================================

ALLOWED_BRANDS = [
    "arc'teryx",
    "arcteryx",
    "patagonia",
    "the north face",
    "north face",
]

ALLOWED_CATEGORIES = [
    "jacket",
    "jackets",
    "softshell",
    "soft shell",
    "hardshell",
    "hard shell",
    "rain shell",
    "rain jacket",
    "down jacket",
    "down jackets",
    "pants",
    "pant",
    "softshell pants",
    "soft shell pants",
    "hardshell pants",
    "hard shell pants",
    "rain pants",
]

EXCLUDED_CATEGORIES = [
    "shoe",
    "shoes",
    "footwear",
    "sandal",
    "sandals",
    "boot",
    "boots",
    "bag",
    "bags",
    "backpack",
    "backpacks",
    "luggage",
    "travel",
    "tent",
    "tents",
    "sleeping bag",
    "camping",
    "equipment",
    "gear",
    "glove",
    "gloves",
    "hat",
    "hats",
    "beanie",
    "sock",
    "socks",
    "t-shirt",
    "tshirts",
    "tee",
    "sweatshirt",
    "sweatshirts",
    "hoodie",
    "hoodies",
    "polo",
    "polos",
]


# ============================================================
# 汇率缓存
# ============================================================

EXCHANGE_RATE_CACHE = {}
EXCHANGE_RATE_CACHE_TIME = {}
EXCHANGE_RATE_CACHE_SECONDS = 1800


# ============================================================
# 通用函数
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return ""

    return str(value).strip()


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()

        if not text:
            return None

        text = text.replace(",", "")
        text = text.replace("$", "")
        text = text.replace("CA$", "")
        text = text.replace("CAD", "")
        text = text.replace("USD", "")
        text = text.replace("C$", "")
        text = text.replace("US$", "")
        text = text.replace("€", "")
        text = text.replace("£", "")
        text = text.replace("¥", "")

        match = re.search(r"-?\d+(?:\.\d+)?", text)

        if not match:
            return None

        try:
            number = float(match.group(0))
        except Exception:
            return None

    if number <= 0:
        return None

    # 防止把商品编号、评分等误识别为价格
    if number > 20000:
        return None

    return number


def normalize_name(text):
    text = clean_text(text).lower()
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# JSON 数据
# ============================================================

def load_history():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print("读取价格历史失败：", exc)

    return {}


def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = DATA_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    temp_file.replace(DATA_FILE)


# ============================================================
# Firecrawl
# ============================================================

def firecrawl_scrape(url, formats=None):
    if not FIRECRAWL_API_KEY:
        print("错误：没有设置 FIRECRAWL_API_KEY")
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
    }

    try:
        response = SESSION.post(
            FIRECRAWL_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        print(f"Firecrawl HTTP {response.status_code}: {url}")

        if response.status_code == 429:
            print("Firecrawl 达到请求限制，本次跳过")
            return None

        if response.status_code != 200:
            print("Firecrawl 返回错误：", response.text[:500])
            return None

        result = response.json()

        if isinstance(result, dict):
            return result.get("data", result)

        return result

    except Exception as exc:
        print("Firecrawl 请求异常：", exc)
        return None


# ============================================================
# 递归遍历数据
# ============================================================

def walk_data(value, path=()):
    """
    递归遍历 Firecrawl 返回的数据。
    返回：
        path, key, value
    """

    if isinstance(value, dict):
        for key, item in value.items():
            yield path, str(key), item

            yield from walk_data(
                item,
                path + (str(key),),
            )

    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_data(
                item,
                path + (str(index),),
            )


# ============================================================
# 价格提取
# ============================================================

CURRENT_PRICE_KEYS = {
    "price",
    "saleprice",
    "sale_price",
    "currentprice",
    "current_price",
    "sellingprice",
    "selling_price",
    "discountprice",
    "discount_price",
    "finalprice",
    "final_price",
    "nowprice",
    "now_price",
    "minsaleprice",
    "min_sale_price",
}

ORIGINAL_PRICE_KEYS = {
    "originalprice",
    "original_price",
    "listprice",
    "list_price",
    "regularprice",
    "regular_price",
    "compareatprice",
    "compare_at_price",
    "wasprice",
    "was_price",
    "fullprice",
    "full_price",
    "msrp",
}


def normalize_key(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def collect_price_candidates(data, wanted_keys):
    candidates = []

    for path, key, value in walk_data(data):
        normalized_key = normalize_key(key)

        if normalized_key not in wanted_keys:
            continue

        number = safe_float(value)

        if number is None:
            continue

        candidates.append(
            {
                "price": number,
                "key": key,
                "path": path,
            }
        )

    return candidates


def collect_offer_prices(data):
    candidates = []

    for path, key, value in walk_data(data):
        normalized_key = normalize_key(key)

        if normalized_key not in {
            "offers",
            "offer",
            "price",
            "lowprice",
            "highprice",
        }:
            continue

        if isinstance(value, dict):
            for k, v in value.items():
                nk = normalize_key(k)

                if nk in {
                    "price",
                    "lowprice",
                    "highprice",
                }:
                    number = safe_float(v)

                    if number is not None:
                        candidates.append(number)

        else:
            number = safe_float(value)

            if number is not None:
                candidates.append(number)

    return candidates


def extract_prices(data):
    """
    从 Firecrawl product 数据中尽可能稳健地提取当前价格。
    """

    candidates = collect_price_candidates(
        data,
        {normalize_key(x) for x in CURRENT_PRICE_KEYS},
    )

    prices = [item["price"] for item in candidates]

    # 再检查 offers / price 等结构
    prices.extend(collect_offer_prices(data))

    prices = [
        p for p in prices
        if 1 <= p <= 20000
    ]

    if not prices:
        return []

    # 去重
    unique = []

    for price in prices:
        if not any(abs(price - x) < 0.01 for x in unique):
            unique.append(price)

    return unique


def extract_original_price(data):
    candidates = collect_price_candidates(
        data,
        {normalize_key(x) for x in ORIGINAL_PRICE_KEYS},
    )

    prices = [
        item["price"]
        for item in candidates
        if 1 <= item["price"] <= 20000
    ]

    unique = []

    for price in prices:
        if not any(abs(price - x) < 0.01 for x in unique):
            unique.append(price)

    if unique:
        return max(unique)

    return None


# ============================================================
# JSON-LD / Markdown 价格备用提取
# ============================================================

def extract_prices_from_text(text):
    if not text:
        return []

    text = html.unescape(str(text))

    results = []

    patterns = [
        r'"price"\s*:\s*"?(?:USD|CAD|C\$|US\$|\$)?\s*([0-9]+(?:\.[0-9]+)?)',
        r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"salePrice"\s*:\s*"?(?:USD|CAD|C\$|US\$|\$)?\s*([0-9]+(?:\.[0-9]+)?)',
        r'"currentPrice"\s*:\s*"?(?:USD|CAD|C\$|US\$|\$)?\s*([0-9]+(?:\.[0-9]+)?)',
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            number = safe_float(match)

            if number is not None and 1 <= number <= 20000:
                results.append(number)

    unique = []

    for price in results:
        if not any(abs(price - x) < 0.01 for x in unique):
            unique.append(price)

    return unique


# ============================================================
# 原价 / 当前价
# ============================================================

def choose_current_price(data):
    prices = extract_prices(data)

    if prices:
        # product 数据里如果有多个价格，优先较低价格作为实际当前价
        return min(prices)

    # 尝试从 markdown / html / json 文本中提取
    text_parts = []

    if isinstance(data, dict):
        for key in ["markdown", "html", "rawHtml"]:
            value = data.get(key)

            if isinstance(value, str):
                text_parts.append(value)

    text = "\n".join(text_parts)

    prices = extract_prices_from_text(text)

    if prices:
        return min(prices)

    return None


def choose_original_price(data, current_price):
    original = extract_original_price(data)

    if original is not None:
        if current_price is None:
            return original

        if original >= current_price:
            return original

    prices = extract_prices(data)

    if prices:
        larger = [
            p for p in prices
            if current_price is None or p >= current_price
        ]

        if larger:
            return max(larger)

    return None


# ============================================================
# 币种
# ============================================================

def extract_currency(data, url=""):
    currency_keys = {
        "currency",
        "currencycode",
        "currency_code",
    }

    for _, key, value in walk_data(data):
        nk = normalize_key(key)

        if nk in currency_keys:
            text = clean_text(value).upper()

            if text in {"USD", "CAD", "CNY", "EUR", "GBP", "JPY", "DKK"}:
                return text

    # 根据官网自动推断
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if "rei.com" in host:
        return "USD"

    if "outlet.arcteryx.com" in host:
        if "/ca/" in path:
            return "CAD"
        return "USD"

    if "arcteryx.com" in host:
        if "/ca/" in path:
            return "CAD"
        return "USD"

    if "patagonia.ca" in host:
        return "CAD"

    if "patagonia.com" in host:
        return "USD"

    if "thenorthface.com" in host:
        if "/en-ca/" in path:
            return "CAD"
        return "USD"

    return None


# ============================================================
# 汇率
# ============================================================

def get_exchange_rate(currency):
    currency = clean_text(currency).upper()

    if not currency:
        return None

    if currency == "CNY":
        return 1.0

    now = time.time()

    cached_rate = EXCHANGE_RATE_CACHE.get(currency)
    cached_time = EXCHANGE_RATE_CACHE_TIME.get(currency, 0)

    if (
        cached_rate is not None
        and now - cached_time < EXCHANGE_RATE_CACHE_SECONDS
    ):
        return cached_rate

    try:
        response = SESSION.get(
            "https://api.frankfurter.app/latest",
            params={
                "from": currency,
                "to": "CNY",
            },
            timeout=20,
        )

        if response.status_code != 200:
            print("汇率获取失败：", response.status_code)
            return cached_rate

        data = response.json()
        rates = data.get("rates", {})

        rate = safe_float(rates.get("CNY"))

        if rate is None:
            return cached_rate

        EXCHANGE_RATE_CACHE[currency] = rate
        EXCHANGE_RATE_CACHE_TIME[currency] = now

        return rate

    except Exception as exc:
        print("汇率获取异常：", exc)
        return cached_rate


def convert_to_cny(price, currency):
    if price is None:
        return None

    currency = clean_text(currency).upper()

    if not currency:
        return None

    rate = get_exchange_rate(currency)

    if rate is None:
        return None

    return round(float(price) * rate, 2)


# ============================================================
# 商品信息
# ============================================================

def extract_product_title(data, fallback_name=""):
    title_keys = {
        "title",
        "name",
        "productname",
        "product_name",
    }

    candidates = []

    for _, key, value in walk_data(data):
        nk = normalize_key(key)

        if nk not in title_keys:
            continue

        text = clean_text(value)

        if len(text) < 3:
            continue

        if len(text) > 300:
            continue

        candidates.append(text)

    if candidates:
        # 通常第一个就是商品标题
        return candidates[0]

    return fallback_name


def product_matches_allowed_brand(name):
    text = normalize_name(name)

    return any(
        normalize_name(brand) in text
        for brand in ALLOWED_BRANDS
    )


def product_matches_allowed_category(name):
    text = normalize_name(name)

    if any(
        normalize_name(word) in text
        for word in EXCLUDED_CATEGORIES
    ):
        return False

    return any(
        normalize_name(word) in text
        for word in ALLOWED_CATEGORIES
    )


# ============================================================
# 颜色 / 尺码 / 库存
# ============================================================

def extract_variant_info(data):
    """
    尽可能从 Firecrawl product 数据中读取颜色、尺码、库存。
    """

    variants = []

    def parse_variant(obj):
        if not isinstance(obj, dict):
            return

        color = ""
        size = ""
        inventory = None

        for key, value in obj.items():
            nk = normalize_key(key)

            if nk in {
                "color",
                "colour",
                "colorname",
                "colourname",
            }:
                color = clean_text(value)

            elif nk in {
                "size",
                "sizename",
            }:
                size = clean_text(value)

            elif nk in {
                "inventory",
                "inventoryquantity",
                "inventory_qty",
                "quantity",
                "stock",
                "stockquantity",
                "availablequantity",
            }:
                number = safe_float(value)

                if number is not None:
                    inventory = int(number)

        if color or size or inventory is not None:
            variants.append(
                {
                    "color": color,
                    "size": size,
                    "inventory": inventory,
                }
            )

    for _, key, value in walk_data(data):
        nk = normalize_key(key)

        if nk in {
            "variants",
            "variant",
            "options",
            "skus",
            "sku",
        }:
            if isinstance(value, list):
                for item in value:
                    parse_variant(item)

            elif isinstance(value, dict):
                parse_variant(value)

    # 去重
    result = []
    seen = set()

    for item in variants:
        key = (
            item.get("color", ""),
            item.get("size", ""),
            item.get("inventory"),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def format_variant_text(variants):
    if not variants:
        return "暂无"

    colors = {}

    for item in variants:
        color = item.get("color") or "默认颜色"
        size = item.get("size") or "未知尺码"
        inventory = item.get("inventory")

        if color not in colors:
            colors[color] = []

        if inventory is None:
            stock_text = "库存未知"
        elif inventory > 0:
            stock_text = f"库存{inventory}"
        else:
            stock_text = "缺货"

        colors[color].append(
            f"{size}({stock_text})"
        )

    lines = []

    for color, sizes in colors.items():
        lines.append(
            f"• {color}: " + ", ".join(sizes)
        )

    return "\n".join(lines)


# ============================================================
# 得物参考价
# ============================================================

def get_dewu_reference_price(product_name):
    """
    得物参考价规则：
    1. 优先 L 码
    2. L 不可用 -> 最低可靠价格
    3. 无可靠数据 -> None

    注意：
    得物公开接口并非稳定官方开放接口，因此这里采用尽力获取。
    不会伪造价格。
    """

    try:
        url = "https://app.dewu.com/api/v1/h5/search/fire/search/list"

        params = {
            "keyword": product_name,
            "limit": 20,
            "page": 1,
        }

        response = SESSION.get(
            url,
            params=params,
            timeout=15,
            headers={
                "User-Agent": SESSION.headers["User-Agent"],
                "Accept": "application/json",
            },
        )

        if response.status_code != 200:
            return None

        data = response.json()

        prices_l = []
        prices_all = []

        def walk_dewu(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield key, item
                    yield from walk_dewu(item)

            elif isinstance(value, list):
                for item in value:
                    yield from walk_dewu(item)

        for key, value in walk_dewu(data):
            nk = normalize_key(key)

            if nk in {
                "minsaleprice",
                "min_sale_price",
                "saleprice",
                "sale_price",
                "price",
            }:
                price = safe_float(value)

                if price is None:
                    continue

                # 得物接口通常以分为单位
                if price > 10000:
                    price = price / 100

                if not (50 <= price <= 50000):
                    continue

                prices_all.append(price)

        # 尝试直接从返回 JSON 中寻找 L 码附近的价格
        raw_text = json.dumps(
            data,
            ensure_ascii=False,
        )

        l_matches = re.findall(
            r'.{0,300}"(?:size|尺码)".{0,80}"L".{0,300}',
            raw_text,
            flags=re.I,
        )

        for block in l_matches:
            found = re.findall(
                r'(?:price|minSalePrice|salePrice)["\']?\s*[:=]\s*["\']?([0-9]+(?:\.[0-9]+)?)',
                block,
                flags=re.I,
            )

            for value in found:
                price = safe_float(value)

                if price is None:
                    continue

                if price > 10000:
                    price /= 100

                if 50 <= price <= 50000:
                    prices_l.append(price)

        if prices_l:
            return round(min(prices_l), 2)

        if prices_all:
            return round(min(prices_all), 2)

    except Exception:
        pass

    return None


# ============================================================
# 自动发现商品
# ============================================================

def extract_links_from_discovery(data):
    links = []

    def add_link(value):
        if not isinstance(value, str):
            return

        value = value.strip()

        if not value.startswith("http"):
            return

        if value not in links:
            links.append(value)

    for _, key, value in walk_data(data):
        nk = normalize_key(key)

        if nk in {
            "url",
            "link",
            "producturl",
            "product_url",
            "href",
        }:
            add_link(value)

    # markdown / html 里的 URL
    if isinstance(data, dict):
        for key in ["markdown", "html", "rawHtml"]:
            text = data.get(key)

            if isinstance(text, str):
                found = re.findall(
                    r'https?://[^\s)"\'<>]+',
                    text,
                )

                for url in found:
                    add_link(url)

    return links


def discover_products(source):
    data = firecrawl_scrape(
        source["url"],
        formats=["markdown"],
    )

    if not data:
        return []

    links = extract_links_from_discovery(data)

    products = []
    seen_urls = set()

    # 明确排除的页面/路径
    excluded_words = [
        "/cart",
        "/account",
        "/login",
        "/stores",
        "/search",
        "/help",
        "/about",
        "/vote",
        "/ownership",
        "/shipping",
        "/returns",
        "/privacy",
        "/terms",
        "/contact",
        "/careers",
        "/blog",
        "/events",
        "/community",
        "/membership",
        "/gift",
        "/wishlist",
        "/size",
        "/filter",
        "/sort",
    ]

    # 图片、视频、文件全部排除
    excluded_extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".avif",
        ".svg",
        ".ico",
        ".pdf",
        ".mp4",
        ".webm",
        ".zip",
    )

    # 尺码、颜色等筛选页面
    excluded_last_parts = {
        "xxs",
        "xs",
        "s",
        "m",
        "l",
        "xl",
        "xxl",
        "xxxl",
        "3xl",
        "4xl",
        "one-size",
        "one_size",
    }

    for url in links:
        if not url:
            continue

        low = url.lower().strip()

        # 去掉查询参数，只用于判断路径
        clean_url = low.split("?", 1)[0]
        path = clean_url.rstrip("/")

        # ① 图片/文件直接排除
        if clean_url.endswith(excluded_extensions):
            continue

        # ② 非商品页面排除
        if any(word in low for word in excluded_words):
            continue

        # ③ 最后一段是尺码，排除
        last_part = path.split("/")[-1]

        if last_part in excluded_last_parts:
            continue

        # ④ Patagonia 的 shop/mens、shop/mens/xxs 等分类页面排除
        if "/shop/mens" in path:
            parts = [x for x in path.split("/") if x]

            # /shop/mens 本身
            if len(parts) <= 2:
                continue

            # /shop/mens/xxs、/shop/mens/xs 等
            if len(parts) == 3 and parts[-1] in excluded_last_parts:
                continue

        # ⑤ 必须是允许品牌
        if not any(
            brand in low
            for brand in [
                "patagonia",
                "arcteryx",
                "arc-teryx",
                "northface",
                "north-face",
            ]
        ):
            continue

        # ⑥ 必须有商品页面特征
        product_path = any(
            keyword in path
            for keyword in [
                "/product/",
                "/products/",
                "/item/",
                "/p/",
            ]
        )

        # Patagonia 等网站有些商品页面不一定使用 /product/
        # 这种情况下，至少要求 URL 看起来像具体商品，而不是分类页
        if not product_path:
            if path.endswith(("/mens", "/men", "/c/mens", "/c/men")):
                continue

            # 最后一段太短，通常是筛选条件
            if len(last_part) < 5:
                continue

        # ⑦ 去重
        if url in seen_urls:
            continue

        seen_urls.add(url)

        # ⑧ 生成临时商品名称
        name = url.rstrip("/").split("/")[-1]
        name = name.split("?", 1)[0]

        name = (
            name
            .replace("-", " ")
            .replace("_", " ")
            .strip()
        )

        if not name:
            continue

        products.append(
            {
                "name": name,
                "url": url,
                "source": source["name"],
            }
        )

        if len(products) >= DISCOVERY_LIMIT:
            break

    return products


# ============================================================
# 单个商品构建
# ============================================================

def build_current_product(product, data):
    name = extract_product_title(
        data,
        product.get("name", ""),
    )

    current_price = choose_current_price(data)

    original_price = choose_original_price(
        data,
        current_price,
    )

    currency = extract_currency(
        data,
        product.get("url", ""),
    )

    variants = extract_variant_info(data)

    if current_price is None:
        return None

    if original_price is None:
        original_price = current_price

    if original_price < current_price:
        original_price = current_price

    if original_price > 0:
        discount = (
            (original_price - current_price)
            / original_price
            * 100
        )
    else:
        discount = 0

    cny_price = convert_to_cny(
        current_price,
        currency,
    )

    dewu_price = get_dewu_reference_price(
        name
    )

    return {
        "name": name,
        "url": product.get("url", ""),
        "source": product.get("source", ""),
        "currency": currency,
        "current_price": round(current_price, 2),
        "original_price": round(original_price, 2),
        "discount": round(discount, 1),
        "cny_price": cny_price,
        "dewu_price": dewu_price,
        "variants": variants,
        "updated_at": int(time.time()),
    }


# ============================================================
# Telegram
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("没有 Telegram Bot Token")
        return False

    if not TELEGRAM_CHAT_ID:
        print("没有 Telegram Chat ID")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False,
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=20,
        )

        if response.status_code != 200:
            print("Telegram 推送失败：", response.text[:500])
            return False

        return True

    except Exception as exc:
        print("Telegram 推送异常：", exc)
        return False


def build_telegram_message(product, previous):
    name = product["name"]

    current = product["current_price"]
    original = product["original_price"]
    discount = product["discount"]

    currency = product.get("currency") or ""

    previous_price = None

    if previous:
        previous_price = safe_float(
            previous.get("current_price")
        )

    if previous_price is not None:
        drop = previous_price - current

        price_line = (
            f"💰 价格：{previous_price:.2f} "
            f"→ {current:.2f} {currency}\n"
            f"📉 本次降价：{drop:.2f} {currency}"
        )
    else:
        price_line = (
            f"💰 当前价：{current:.2f} {currency}"
        )

    lines = [
        "🔥 户外商品降价提醒",
        "",
        f"🏷️ 折扣：{discount:.1f}%",
        f"📦 商品：{name}",
        f"💵 原价：{original:.2f} {currency}",
        price_line,
    ]

    cny = product.get("cny_price")

    if cny is not None:
        lines.extend(
            [
                "",
                f"🇨🇳 人民币参考价：¥{cny:,.0f}",
                "💱 按实时汇率换算",
            ]
        )

    dewu = product.get("dewu_price")

    if dewu is not None:
        lines.append(
            f"🛒 得物参考价：¥{dewu:,.0f}"
        )
    else:
        lines.append(
            "🛒 得物参考价：暂不可用"
        )

    variants = product.get("variants") or []

    lines.extend(
        [
            "",
            "🎨 颜色 / 尺码 / 库存：",
            format_variant_text(variants),
            "",
            f"🔗 {product['url']}",
        ]
    )

    return "\n".join(lines)


# ============================================================
# 商品检查
# ============================================================

def check_product(product, history):
    print("检查：", product["name"])

    data = firecrawl_scrape(
        product["url"],
        formats=["product", "markdown"],
    )

    if not data:
        print("没有获得商品数据")
        return

    current_product = build_current_product(
        product,
        data,
    )

    if current_product is None:
        print("没有获取到有效价格")
        return

    current_price = current_product["current_price"]

    key = product["url"]

    previous = history.get(key)

    if previous:
        previous_price = safe_float(
            previous.get("current_price")
        )

        if previous_price is not None:
            # 只有实际降价才可能推送
            price_changed_down = current_price < previous_price

            discount_ok = (
                current_product["discount"]
                >= MIN_DISCOUNT
            )

            if price_changed_down and discount_ok:
                message = build_telegram_message(
                    current_product,
                    previous,
                )

                send_telegram_message(message)

                print("✅ 已推送降价提醒")

    # 无论是否推送，都保存最新价格
    history[key] = current_product

    print(
        f"当前价格：{current_price:.2f} "
        f"{current_product.get('currency') or ''}"
    )

    print(
        f"折扣：{current_product['discount']:.1f}%"
    )


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("Outdoor Price Monitor")
    print("=" * 60)

    history = load_history()

    # --------------------------------------------------------
    # 固定5个商品全部检查
    # --------------------------------------------------------

    products = list(FIXED_PRODUCTS)

    print(
        f"本次检查固定商品：{len(FIXED_PRODUCTS)}"
    )

    # --------------------------------------------------------
    # 自动发现
    # --------------------------------------------------------

    # 根据当前时间轮换发现来源
    rotation_index = (
        int(time.time() / 1800)
        % len(DISCOVERY_SOURCES)
    )

    source = DISCOVERY_SOURCES[rotation_index]

    print(
        "自动发现：",
        source["name"],
    )

    try:
        discovered = discover_products(source)

        fixed_urls = {
            item["url"]
            for item in FIXED_PRODUCTS
        }

        for item in discovered:
            if item["url"] in fixed_urls:
                continue

            # 先根据 URL 做基础过滤
            url_text = normalize_name(
                item["url"]
            )

            if any(
                normalize_name(word) in url_text
                for word in EXCLUDED_CATEGORIES
            ):
                continue

            products.append(item)

    except Exception as exc:
        print("自动发现异常：", exc)

    print(
        f"本次实际检查商品：{len(products)}"
    )

    # --------------------------------------------------------
    # 开始检查
    # --------------------------------------------------------

    for index, product in enumerate(products, start=1):
        print()
        print(
            f"========== {index}/{len(products)} =========="
        )

        check_product(
            product,
            history,
        )

        if index < len(products):
            print(
                f"等待 {FIRECRAWL_DELAY} 秒，"
                "避免 Firecrawl 限流..."
            )
            time.sleep(FIRECRAWL_DELAY)

    # --------------------------------------------------------
    # 保存历史
    # --------------------------------------------------------

    save_history(history)

    print()
    print("=" * 60)
    print("本次监控完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
