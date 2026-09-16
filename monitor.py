import os
import re
import json
import time
import html
from pathlib import Path
from urllib.parse import urlparse, urljoin

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

# 自动发现：不设置发现商品数量上限

DATA_FILE = Path("data/prices.json")
DISCOVERED_FILE = Path("data/discovered_products.json")
RESET_MARKER_FILE = Path("data/.history_reset_v1_done")

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
        "url": "https://arcteryx.com/ca/en/c/mens/p",
    },
    {
        "name": "Patagonia US",
        "url": "https://www.patagonia.com/shop/mens",
    },
    {
        "name": "Patagonia Canada",
        "url": "https://www.patagonia.ca/shop/mens",
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
    提取颜色 / 尺码 / 库存。
    重点处理真正的 SKU / variant 对象，避免把页面其它 quantity/count
    之类的字段误当成库存，也避免把 option 名称本身误当成尺码。
    """

    COLOR_KEYS = {
        "color", "colour", "colorname", "colourname",
        "variantcolor", "variantcolour", "optioncolor",
    }
    SIZE_KEYS = {
        "size", "sizename", "variantsize", "optionsize",
    }
    STOCK_KEYS = {
        "inventory", "inventoryquantity", "inventoryqty",
        "stock", "stockquantity", "availablequantity",
        "availableqty", "inventorylevel", "onhand",
        "quantityavailable", "quantityonhand",
        "salablequantity", "availableinventory",
    }
    AVAILABILITY_KEYS = {
        "availability", "instock", "in_stock",
        "isavailable", "sellable", "available",
        "availableforsale", "available_for_sale",
        "currentlyavailable", "stockstatus",
        "inventorypolicy",
    }

    CONTAINER_KEYS = {
        "variants", "variant", "skus", "sku",
        "productvariants", "variantlist", "variantslist",
        "merchandise", "variantitems",
    }
    OPTION_KEYS = {
        "options", "optionvalues", "selectedoptions",
        "selectedoption", "choices", "attributes",
    }

    records = []

    def scalar(value):
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value).strip()
        return ""

    def parse_stock(value):
        """把数字、布尔、库存文案、嵌套库存对象统一转换成库存数量。"""
        if isinstance(value, bool):
            return 1 if value else 0

        if isinstance(value, (int, float)):
            return max(0, int(value))

        if isinstance(value, dict):
            # 常见：{"quantityAvailable": 5}
            priority_keys = (
                "quantityAvailable", "quantityOnHand",
                "availableQuantity", "availableQty",
                "inventoryQuantity", "inventory",
                "quantity", "stock", "count",
            )
            for key in priority_keys:
                if key in value:
                    parsed = parse_stock(value.get(key))
                    if parsed is not None:
                        return parsed

            # 再扫描一次标准化键名
            for key, item in value.items():
                nk = normalize_key(key)
                if nk in {
                    "quantityavailable", "quantityonhand",
                    "availablequantity", "availableqty",
                    "inventoryquantity", "inventoryqty",
                    "quantity", "stock", "count", "onhand",
                }:
                    parsed = parse_stock(item)
                    if parsed is not None:
                        return parsed

            return None

        if isinstance(value, str):
            s = value.strip().lower()

            # 先处理明确库存状态
            if s in {
                "true", "yes", "available", "instock",
                "in stock", "instockstatus", "in stock now",
                "available for sale", "availableforsale",
            }:
                return 1

            if s in {
                "false", "no", "unavailable", "outofstock",
                "out of stock", "sold out", "soldout",
            }:
                return 0

            # 文案中的数量：
            # "5 available", "Only 2 left", "quantityAvailable: 7"
            patterns = [
                r"(?:only\s*)?(\d+(?:\.\d+)?)\s*(?:left|available|in stock)",
                r"(?:available|stock|quantity)\s*[:：]?\s*(\d+(?:\.\d+)?)",
                r"(\d+(?:\.\d+)?)\s*(?:units?|pcs?)\b",
            ]
            for pattern in patterns:
                m = re.search(pattern, s, flags=re.I)
                if m:
                    try:
                        return max(0, int(float(m.group(1))))
                    except Exception:
                        pass

            # 单纯数字字符串
            if re.fullmatch(r"\d+(?:\.\d+)?", s):
                try:
                    return max(0, int(float(s)))
                except Exception:
                    pass

        return None


    def parse_option_value(item):
        """
        把 Shopify/电商常见的：
        {"name":"Color","value":"Black"}
        {"name":"Size","value":"L"}
        解析成 color/size。
        """
        if not isinstance(item, dict):
            return None, None

        name = ""
        value = ""

        for k, v in item.items():
            nk = normalize_key(k)
            if nk in {"name", "optionname", "attribute", "label", "key"}:
                name = scalar(v)
            elif nk in {"value", "optionvalue", "selectedvalue", "displayvalue"}:
                value = scalar(v)

        if not name or not value:
            return None, None

        nn = normalize_key(name)
        if nn in {
            "color", "colour", "colorname", "colourname",
            "variantcolor", "variantcolour",
        }:
            return value, None
        if nn in {
            "size", "sizename", "variantsize",
        }:
            return None, value

        return None, None

    def inspect_variant(obj, inherited_color="", inherited_size=""):
        if not isinstance(obj, dict):
            return

        color = inherited_color
        size = inherited_size
        stock = None

        # 当前对象直接字段
        for key, value in obj.items():
            nk = normalize_key(key)

            if nk in COLOR_KEYS:
                value_text = scalar(value)
                if value_text:
                    color = value_text

            elif nk in SIZE_KEYS:
                value_text = scalar(value)
                if value_text:
                    size = value_text

            elif nk in STOCK_KEYS:
                parsed = parse_stock(value)
                if parsed is not None:
                    stock = parsed

            elif nk in AVAILABILITY_KEYS and stock is None:
                parsed = parse_stock(value)
                if parsed is not None:
                    stock = parsed

            # 很多电商页面把库存藏在 inventory / availability 对象里，
            # 例如 {"inventory": {"quantityAvailable": 3}}
            elif isinstance(value, dict) and (
                nk in {"inventory", "stock", "availability", "inventorydata",
                       "inventorystatus", "quantity"}
            ):
                parsed = parse_stock(value)
                if parsed is not None:
                    stock = parsed

        # 有些站点用 availableForSale=true/false 或 quantityAvailable，
        # 但字段位于 variant 的下一层/更深层对象。递归查找。
        if stock is None:
            def find_nested_stock(node, depth=0):
                if depth > 4:
                    return None
                if isinstance(node, dict):
                    for k, v in node.items():
                        nk = normalize_key(k)
                        if nk in STOCK_KEYS or nk in AVAILABILITY_KEYS:
                            parsed = parse_stock(v)
                            if parsed is not None:
                                return parsed
                        if isinstance(v, (dict, list)):
                            parsed = find_nested_stock(v, depth + 1)
                            if parsed is not None:
                                return parsed
                elif isinstance(node, list):
                    for v in node:
                        parsed = find_nested_stock(v, depth + 1)
                        if parsed is not None:
                            return parsed
                return None

            stock = find_nested_stock(obj)

        # selectedOptions / optionValues / options
        for key, value in obj.items():
            nk = normalize_key(key)
            if nk not in OPTION_KEYS:
                continue

            option_items = value if isinstance(value, list) else [value]
            for option in option_items:
                c, s = parse_option_value(option)
                if c:
                    color = c
                if s:
                    size = s

                # 有些站点是 {"Color":"Black","Size":"L"}
                if isinstance(option, dict):
                    for ok, ov in option.items():
                        on = normalize_key(ok)
                        val = scalar(ov)
                        if not val:
                            continue
                        if on in COLOR_KEYS or on == "color":
                            color = val
                        elif on in SIZE_KEYS or on == "size":
                            size = val

        # 只有真正像 variant/SKU 的对象才作为一条记录
        # 防止 product 根对象被保存成“未知尺码”。
        looks_like_variant = (
            bool(color or size or stock is not None)
            and (
                size
                or stock is not None
                or any(
                    normalize_key(k) in CONTAINER_KEYS
                    for k in obj.keys()
                )
            )
        )

        if looks_like_variant:
            records.append({
                "color": color,
                "size": size,
                "inventory": stock,
            })

        # 继续递归，但传递当前已识别的颜色/尺码
        for key, value in obj.items():
            nk = normalize_key(key)

            if nk in CONTAINER_KEYS:
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            inspect_variant(
                                item,
                                inherited_color=color,
                                inherited_size=size,
                            )
                elif isinstance(value, dict):
                    inspect_variant(
                        value,
                        inherited_color=color,
                        inherited_size=size,
                    )

    def parse_json_string(value):
        if not isinstance(value, str):
            return
        s = value.strip()
        if not s or s[0] not in "[{":
            return
        try:
            parsed = json.loads(s)
        except Exception:
            return
        if isinstance(parsed, dict):
            inspect_variant(parsed)
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    inspect_variant(item)

    # 1. 直接处理明确的 variant/SKU 容器
    if isinstance(data, dict):
        for _, key, value in walk_data(data):
            nk = normalize_key(key)
            if nk in CONTAINER_KEYS:
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            inspect_variant(item)
                        elif isinstance(item, str):
                            parse_json_string(item)
                elif isinstance(value, dict):
                    inspect_variant(value)
                elif isinstance(value, str):
                    parse_json_string(value)

    # 2. JSON-LD / 页面文本中的变体数据
    if isinstance(data, dict):
        text_parts = []
        for key in ("markdown", "html", "rawHtml"):
            value = data.get(key)
            if isinstance(value, str):
                text_parts.append(value)

        combined = "\n".join(text_parts)
        for script in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            combined,
            flags=re.I | re.S,
        ):
            parse_json_string(html.unescape(script))

    # 3. 去重 + 清理
    cleaned = []
    seen = set()

    for item in records:
        color = clean_text(item.get("color", ""))
        size = clean_text(item.get("size", ""))
        inventory = item.get("inventory")

        # 修复常见脏尺码：
        # "Size: L" -> "L"
        # "size-L" -> "L"
        size = re.sub(r"^(?:size|尺码)\s*[:：\-]?\s*", "", size, flags=re.I)
        size = clean_text(size)

        # 只接受合理的服装尺码，避免把颜色/选项文本当成尺码。
        # 同时保留数字腰围等常见男裤尺码。
        if size:
            normalized_size = normalize_key(size)
            valid_size = (
                normalized_size in {
                    "xxxs", "xxs", "xs", "s", "m", "l", "xl",
                    "xxl", "xxxl", "3xl", "4xl",
                    "onesize", "os",
                }
                or bool(re.fullmatch(r"\d{2}(?:x\d{2})?", size.strip(), re.I))
                or bool(re.fullmatch(r"\d{2}(?:\.\d)?", size.strip()))
            )
            if not valid_size:
                size = ""

        if not color and not size:
            continue

        key = (
            color.lower(),
            size.lower(),
            inventory,
        )
        if key in seen:
            continue

        seen.add(key)
        cleaned.append({
            "color": color,
            "size": size,
            "inventory": inventory,
        })

    return cleaned


def format_variant_text(variants):
    if not variants:
        return "暂无"

    colors = {}

    size_order = {
        "xxxs": 0,
        "xxs": 1,
        "xs": 2,
        "s": 3,
        "m": 4,
        "l": 5,
        "xl": 6,
        "xxl": 7,
        "xxxl": 8,
        "3xl": 9,
        "4xl": 10,
        "os": 11,
        "onesize": 12,
        "one size": 12,
    }

    for item in variants:
        color = clean_text(item.get("color", "")) or "默认颜色"
        size = clean_text(item.get("size", "")) or "尺码未知"
        inventory = item.get("inventory")

        if color not in colors:
            colors[color] = {}

        # 同颜色同尺码只保留一次。
        colors[color][size] = inventory

    def sort_size(item):
        size, _ = item
        s = size.strip().lower()
        if s in size_order:
            return (0, size_order[s], s)

        m = re.fullmatch(r"(\d{2})(?:x(\d{2}))?", s)
        if m:
            return (1, int(m.group(1)), int(m.group(2) or 0))

        return (2, s)

    lines = []

    for color, sizes_map in colors.items():
        size_parts = []

        for size, inventory in sorted(sizes_map.items(), key=sort_size):
            if inventory is None:
                stock_text = "库存未知"
            elif inventory > 0:
                stock_text = f"库存{inventory}"
            else:
                stock_text = "缺货"

            size_parts.append(f"{size}({stock_text})")

        lines.append(f"• {color}: " + ", ".join(size_parts))

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

# 每次运行只发现一个官网，避免 Firecrawl 触发限流。
# 这里没有“最多发现几个商品”的限制；抓到多少符合条件的链接就保存多少。
# 监控阶段会轮换历史发现商品，避免单次请求过多。
DISCOVERED_CHECKS_PER_RUN = 5

EXCLUDED_URL_WORDS = (
    "/cart", "/account", "/login", "/stores", "/search", "/help",
    "/about", "/vote", "/ownership", "/shipping", "/returns",
    "/privacy", "/terms", "/contact", "/careers", "/blog", "/events",
    "/community", "/membership", "/gift", "/wishlist", "/size",
    "/filter", "/sort", "/reviews", "/faq",
)

DISCOVERY_BAD_PATH_WORDS = (
    "/store-locator", "/progress-report", "/worth-it", "/stories/",
    "/impact/", "/our-footprint", "/responsible-business",
    "/collections/", "/category/", "/fair-trade", "/pfc-free",
)

EXCLUDED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg",
    ".ico", ".pdf", ".mp4", ".webm", ".zip", ".css", ".js",
)

EXCLUDED_LAST_PARTS = {
    "xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "3xl", "4xl",
    "one-size", "one_size", "men", "mens", "women", "womens",
}


def canonical_url(url):
    """规范化商品 URL，用于去重。"""
    if not isinstance(url, str):
        return ""

    url = html.unescape(url).strip()
    if not url.startswith(("http://", "https://")):
        return ""

    # 去掉片段；查询参数保留与否通常不影响商品身份，因此统一去掉。
    parsed = urlparse(url)
    if not parsed.netloc:
        return ""

    clean_path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{clean_path}"


def load_discovered_products():
    DISCOVERED_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not DISCOVERED_FILE.exists():
        return []

    try:
        with open(DISCOVERED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return []

        result = []
        seen = set()

        for item in data:
            if not isinstance(item, dict):
                continue

            url = canonical_url(item.get("url", ""))
            source_name = clean_text(item.get("source", ""))
            name = clean_text(item.get("name", ""))
            if not url or url in seen:
                continue

            source_obj = next((x for x in DISCOVERY_SOURCES if x.get("name") == source_name), None)
            if source_obj is None:
                continue
            if not _recognize_product_url(source_obj, url):
                continue
            if not candidate_matches_allowed_name(name, url, source_obj):
                continue

            seen.add(url)
            result.append({
                "name": name,
                "url": url,
                "source": source_name,
                "last_checked": int(item.get("last_checked", 0) or 0),
                "invalid_count": int(item.get("invalid_count", 0) or 0),
            })

        return result

    except Exception as exc:
        print("读取自动发现商品库失败：", exc)
        return []


def save_discovered_products(products):
    DISCOVERED_FILE.parent.mkdir(parents=True, exist_ok=True)

    temp_file = DISCOVERED_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)

    temp_file.replace(DISCOVERED_FILE)


def extract_links_from_discovery(data, base_url=""):
    """从 Firecrawl 结果中提取链接，并补全相对 URL。"""
    links = []
    seen = set()

    def add_link(value):
        if not isinstance(value, str):
            return
        value = html.unescape(value).strip().strip('<>')
        if not value:
            return
        if value.startswith('//'):
            value = 'https:' + value
        elif base_url and not value.startswith(('http://', 'https://')):
            value = urljoin(base_url, value)
        if not value.startswith(('http://', 'https://')):
            return
        value = value.split('#', 1)[0]
        url = canonical_url(value)
        if url and url not in seen:
            seen.add(url)
            links.append(url)

    # Firecrawl 的 links 格式通常会直接返回 links 数组；
    # 这里单独处理，避免 walk_data 遍历列表时丢失字段名。
    if isinstance(data, dict):
        direct_links = data.get("links")
        if isinstance(direct_links, list):
            for value in direct_links:
                add_link(value)
        elif isinstance(direct_links, str):
            add_link(direct_links)

    for _, key, value in walk_data(data):
        nk = normalize_key(key)
        if nk in {"url", "link", "producturl", "product_url", "href"}:
            add_link(value)

    if isinstance(data, dict):
        for key in ("markdown", "html", "rawHtml"):
            text = data.get(key)
            if not isinstance(text, str):
                continue
            text = html.unescape(text)
            for match in re.findall(r'https?://[^\s)"\'<>]+', text):
                add_link(match)
            for match in re.findall(r'(?:href|src)=["\']([^"\']+)', text, flags=re.I):
                add_link(match)
            for match in re.findall(r'\]\(([^)\s]+)', text):
                add_link(match)

    return links


def _source_host(source):
    return urlparse(source.get("url", "")).netloc.lower().removeprefix("www.")


def _clean_discovery_url(url):
    return canonical_url(url)


def _is_bad_common_url(path):
    low = path.lower()
    if any(x in low for x in EXCLUDED_URL_WORDS):
        return True
    if any(x in low for x in DISCOVERY_BAD_PATH_WORDS):
        return True
    return False


def _is_size_or_file(path):
    low = path.lower()
    if low.endswith(EXCLUDED_EXTENSIONS):
        return True
    last = low.rstrip('/').split('/')[-1]
    return last in EXCLUDED_LAST_PARTS


def _source_kind(source):
    host = _source_host(source)
    name = normalize_name(source.get("name", ""))
    if "rei.com" in host:
        return "rei"
    if "arcteryx" in host:
        return "arcteryx"
    if "patagonia" in host:
        return "patagonia"
    if "thenorthface" in host or "north face" in name:
        return "tnf"
    return "unknown"


def _recognize_product_url(source, url):
    """按各官网当前商品 URL 结构识别商品链接。"""
    host = _source_host(source)
    clean = _clean_discovery_url(url)
    parsed = urlparse(clean)
    path = parsed.path
    low_path = path.lower()

    if not clean or _is_bad_common_url(low_path) or _is_size_or_file(low_path):
        return False

    if 'rei.com' in host:
        return bool(re.search(r'^/product/[a-z0-9]+(?:/[^/]*)?$', low_path, re.I))

    if 'outlet.arcteryx.com' in host:
        # 例如 /us/en/shop/mens/alpha-jacket-9898
        return bool(re.search(r'^/(?:us|ca)/en/shop/mens/[^/]+$', low_path, re.I))

    if 'arcteryx.com' in host:
        # 当前官网商品页常见形式：/ca/en/shop/mens/gamma-pant
        # 也兼容其它国家/语言路径，只要明确落在 /shop/mens/ 商品目录下。
        return bool(re.search(r'^/(?:[a-z]{2}/)?(?:en|fr|zh)/shop/mens/[^/]+$', low_path, re.I)) or \
               bool(re.search(r'^/(?:[a-z]{2}/)+(?:en|fr|zh)/shop/mens/[^/]+$', low_path, re.I))

    if 'patagonia.com' in host or 'patagonia.ca' in host:
        # Patagonia 商品链接通常为 /product/<slug>.html
        return bool(re.match(r'^/product/[^/]+(?:/[^/]+)?(?:\.html)?$', low_path, re.I))

    return False

def candidate_matches_allowed_name(name, url, source=None):
    """最终品牌、男装、品类过滤。REI 允许三品牌，其它官网只允许各自品牌。"""
    text = normalize_name(f"{name} {url}")
    host = _source_host(source or {}) if source else urlparse(url).netloc.lower().removeprefix('www.')
    source_name = normalize_name((source or {}).get("name", ""))

    # 女装明确排除
    if any(x in text for x in ("women", "womens", "women's", "female")):
        return False

    # REI 自动发现：只允许始祖鸟、巴塔哥尼亚、北面。
    if 'rei.com' in host:
        rei_brand_ok = (
            ("arc'teryx" in text or "arcteryx" in text)
            or ("patagonia" in text)
            or ("the north face" in text or "north face" in text)
        )
        if not rei_brand_ok:
            return False
    elif "arc'teryx" in source_name or "arcteryx" in source_name:
        # Arc'teryx 官网本身已经限定品牌，不要求 slug 再出现品牌名。
        pass
    elif "patagonia" in source_name:
        # Patagonia 官网本身已经限定品牌，不要求 slug 再出现品牌名。
        pass

    # 先排除明确不需要的品类
    if any(normalize_name(word) in text for word in EXCLUDED_CATEGORIES):
        return False

    # Arc'teryx 的 Hoody 是其外套命名的一部分，但普通 hoodie 要排除。
    arcteryx_outerwear = (
        ('arcteryx' in text or "arc'teryx" in text)
        and any(x in text for x in ('hoody', 'hooded', 'parka', 'shell', 'jacket', 'pants', 'pant'))
    )

    category_ok = any(normalize_name(word) in text for word in ALLOWED_CATEGORIES)
    if not category_ok and not arcteryx_outerwear:
        return False

    return True

def _extract_candidate_urls_from_text(text, source):
    """从 Markdown / HTML / rawHtml 中提取商品 URL。"""
    if not isinstance(text, str) or not text:
        return []
    base_url = source.get("url", "")
    urls=[]; seen=set()
    def add(value):
        if not isinstance(value,str): return
        value=html.unescape(value).strip().strip('<>')
        value=value.replace('\\/','/')
        if not value: return
        if value.startswith('//'): value='https:'+value
        elif not value.startswith(('http://','https://')): value=urljoin(base_url,value)
        clean=canonical_url(value)
        if clean and clean not in seen:
            seen.add(clean); urls.append(clean)
    for value in re.findall(r'https?://[^\s"\'<>\\)]+', text, flags=re.I): add(value)
    for value in re.findall(r'(?:href|data-href|data-url|data-product-url|producturl|product_url)=["\']([^"\']+)', text, flags=re.I): add(value)
    for value in re.findall(r'\]\(\s*<?([^\)\s>]+)', text): add(value)
    for value in re.findall(r'["\']((?:/[^"\']+))["\']', text, flags=re.I):
        low=value.lower()
        if any(x in low for x in ('/product/','/shop/','/p/')): add(value)
    return urls


def _build_name_from_url(url):
    """从商品 URL 生成备用商品名；商品页抓到标题后会覆盖它。"""
    parts=[x for x in urlparse(url).path.strip('/').split('/') if x]
    if not parts: return ''
    slug=parts[-1]
    if re.fullmatch(r'nf[a-z0-9-]+', slug, re.I) and len(parts)>=2: slug=parts[-2]
    if slug.lower().endswith('.html'): slug=slug[:-5]
    slug=re.sub(r'[-_]+',' ',slug)
    slug=re.sub(r'\b(?:mens|men|womens|women|male|female)\b','',slug,flags=re.I)
    return re.sub(r'\s+',' ',slug).strip().title()


def discover_products(source):
    data = firecrawl_scrape(source["url"], formats=["markdown"])
    if not data:
        print("没有获得发现页数据")
        return []
    links = extract_links_from_discovery(data, source["url"])
    if isinstance(data, dict):
        for key in ("markdown", "html", "rawHtml"):
            links.extend(_extract_candidate_urls_from_text(data.get(key), source))

    # 去重后再识别，避免同一商品被多个字段重复抓取。
    unique_links = []
    link_seen = set()
    for raw_url in links:
        clean_url = _clean_discovery_url(raw_url)
        if clean_url and clean_url not in link_seen:
            link_seen.add(clean_url)
            unique_links.append(clean_url)

    products, seen_urls = [], set()
    for raw_url in unique_links:
        url = _clean_discovery_url(raw_url)
        if not url or url in seen_urls:
            continue
        if not _recognize_product_url(source, url):
            continue
        seen_urls.add(url)
        name = _build_name_from_url(url)
        if not candidate_matches_allowed_name(name, url, source):
            continue
        products.append({"name": name, "url": url, "source": source["name"]})
    return products


def merge_discovered_products(existing, discovered):
    """把本次发现合并到长期商品池，按规范化 URL 去重。"""
    merged = []
    index = {}

    for item in existing + discovered:
        if not isinstance(item, dict):
            continue

        url = canonical_url(item.get("url", ""))
        if not url:
            continue

        if url in index:
            # 新发现的名称更完整时更新名称/来源
            pos = index[url]
            if len(clean_text(item.get("name", ""))) > len(clean_text(merged[pos].get("name", ""))):
                merged[pos]["name"] = item.get("name", "")
            if item.get("source"):
                merged[pos]["source"] = item.get("source")
            continue

        clean_item = {
            "name": clean_text(item.get("name", "")),
            "url": url,
            "source": clean_text(item.get("source", "")),
            "last_checked": int(item.get("last_checked", 0) or 0),
            "invalid_count": int(item.get("invalid_count", 0) or 0),
        }
        index[url] = len(merged)
        merged.append(clean_item)

    return merged


def choose_discovered_for_check(discovered_products, limit=DISCOVERED_CHECKS_PER_RUN):
    """轮换检查历史发现商品；固定商品不占这里的名额。"""
    if not discovered_products or limit <= 0:
        return []

    # 优先最久没有检查的商品。
    ordered = sorted(
        discovered_products,
        key=lambda x: int(x.get("last_checked", 0) or 0),
    )

    return ordered[:limit]


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

    discount_ok = (
        current_product["discount"]
        >= MIN_DISCOUNT
    )

    if previous:
        previous_price = safe_float(
            previous.get("current_price")
        )

        if previous_price is not None:
            # 已有历史：只有实际降价且折扣达到门槛才推送
            price_changed_down = current_price < previous_price

            if price_changed_down and discount_ok:
                message = build_telegram_message(
                    current_product,
                    previous,
                )

                send_telegram_message(message)

                print("✅ 已推送降价提醒")
    else:
        # 第一次发现：如果已经达到折扣门槛，立即推送一次
        if discount_ok:
            message = build_telegram_message(
                current_product,
                None,
            )

            send_telegram_message(message)

            print("✅ 首次发现折扣商品，已推送提醒")

    # 无论是否推送，都保存最新价格
    history[key] = current_product

    print(
        f"当前价格：{current_price:.2f} "
        f"{current_product.get('currency') or ''}"
    )

    print(
        f"折扣：{current_product['discount']:.1f}%"
    )

    variants = current_product.get("variants") or []
    known_stock = sum(
        1 for item in variants
        if item.get("inventory") is not None
    )

    print(
        f"变体信息：{len(variants)} 条，"
        f"其中已识别库存 {known_stock} 条"
    )


# ============================================================
# 主程序
# ============================================================

def reset_history_once():
    """部署新版监控后，仅第一次运行清空旧价格和旧自动发现商品库。"""
    if RESET_MARKER_FILE.exists():
        return

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    reset_files = [DATA_FILE, DISCOVERED_FILE]
    for target in reset_files:
        try:
            if target.exists():
                target.unlink()
                print(f"🧹 已删除旧记录：{target}")
        except Exception as exc:
            print(f"删除旧记录失败 {target}: {exc}")

    try:
        RESET_MARKER_FILE.write_text(
            "本版本第一次运行已完成历史记录重置。\n",
            encoding="utf-8",
        )
        print("✅ 历史记录已重置：从本次运行开始重新建立价格基线")
    except Exception as exc:
        print("创建历史重置标记失败：", exc)


def main():
    reset_history_once()

    print("=" * 60)
    print("Outdoor Price Monitor")
    print("=" * 60)

    history = load_history()
    discovered_pool = load_discovered_products()

    # --------------------------------------------------------
    # 固定5个商品始终检查
    # --------------------------------------------------------
    products = list(FIXED_PRODUCTS)

    print(f"本次检查固定商品：{len(FIXED_PRODUCTS)}")

    # --------------------------------------------------------
    # 自动发现：本次依次测试全部官网
    # --------------------------------------------------------
    # 发现阶段也使用统一的 Firecrawl 间隔，避免 7 个官网连续请求
    # 触发限流。固定 5 个商品仍然全部检查。
    print("自动发现：本次检查全部官网")

    total_new = 0
    success_sources = 0

    for source_index, source in enumerate(DISCOVERY_SOURCES, start=1):
        print(f"自动发现 {source_index}/{len(DISCOVERY_SOURCES)}：{source['name']}")
        try:
            discovered_now = discover_products(source)
            before_count = len(discovered_pool)
            discovered_pool = merge_discovered_products(
                discovered_pool,
                discovered_now,
            )
            added_now = max(0, len(discovered_pool) - before_count)
            total_new += added_now
            success_sources += 1
            print(f"  发现 {len(discovered_now)} 个，新增 {added_now} 个")
        except Exception as exc:
            print(f"  自动发现异常：{exc}")

        if source_index < len(DISCOVERY_SOURCES):
            print(f"  等待 {FIRECRAWL_DELAY} 秒，避免 Firecrawl 限流...")
            time.sleep(FIRECRAWL_DELAY)

    save_discovered_products(discovered_pool)
    print(
        f"自动发现完成：成功 {success_sources}/{len(DISCOVERY_SOURCES)} 个官网，"
        f"本次新增 {total_new} 个，累计商品库 {len(discovered_pool)} 个"
    )

    # --------------------------------------------------------
    # 固定5个 + 历史自动发现商品（轮换）
    # --------------------------------------------------------
    fixed_urls = {
        canonical_url(item["url"])
        for item in FIXED_PRODUCTS
    }

    selected_discovered = choose_discovered_for_check(
        discovered_pool,
        DISCOVERED_CHECKS_PER_RUN,
    )

    for item in selected_discovered:
        if canonical_url(item.get("url", "")) in fixed_urls:
            continue
        products.append(item)

    print(
        f"本次实际检查商品：{len(products)} "
        f"（固定 {len(FIXED_PRODUCTS)} + 自动发现轮换 {len(products) - len(FIXED_PRODUCTS)}）"
    )

    # --------------------------------------------------------
    # 开始检查
    # --------------------------------------------------------
    checked_urls = set()

    for index, product in enumerate(products, start=1):
        url = canonical_url(product.get("url", ""))
        if url and url in checked_urls:
            continue
        if url:
            checked_urls.add(url)

        print()
        print(f"========== {index}/{len(products)} ==========")

        check_product(product, history)

        # 更新自动发现商品的轮换时间
        if url:
            for item in discovered_pool:
                if canonical_url(item.get("url", "")) == url:
                    item["last_checked"] = int(time.time())
                    break

        if index < len(products):
            print(
                f"等待 {FIRECRAWL_DELAY} 秒，"
                "避免 Firecrawl 限流..."
            )
            time.sleep(FIRECRAWL_DELAY)

    # --------------------------------------------------------
    # 保存历史和自动发现商品库
    # --------------------------------------------------------
    save_history(history)
    save_discovered_products(discovered_pool)

    print()
    print("=" * 60)
    print("本次监控完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
