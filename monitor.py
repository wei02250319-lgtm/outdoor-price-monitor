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

FIRECRAWL_DELAY = 10
RATE_LIMIT_WAIT = 35
FIRECRAWL_TIMEOUT = 90

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "prices.json"

# 折扣达到 20% 才符合条件
MIN_DISCOUNT = 20
IMPORTANT_DISCOUNT = 20
SUPER_DISCOUNT = 50

# 自动发现
DISCOVERY_LIMIT = 5

# 固定商品轮换数量
FIXED_ROTATION = 4


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
# Session
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
)


# ============================================================
# 汇率缓存
# ============================================================

EXCHANGE_RATE_CACHE = {}
EXCHANGE_RATE_CACHE_TIME = {}
EXCHANGE_RATE_CACHE_SECONDS = 1800


# ============================================================
# 基础工具
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None

    text = clean_text(value)

    if not text:
        return None

    text = (
        text.replace(",", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
    )

    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return float(match.group())
    except Exception:
        return None


def title_from_url(url):
    path = urlparse(url).path.rstrip("/")

    if not path:
        return ""

    slug = path.split("/")[-1]

    slug = re.sub(r"\.[a-zA-Z0-9]+$", "", slug)

    slug = slug.replace("-", " ")
    slug = slug.replace("_", " ")

    slug = re.sub(r"\s+", " ", slug)

    return slug.strip().title()


# ============================================================
# JSON 数据
# ============================================================

def load_history():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        return {}

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print("读取价格历史失败：", exc)

    return {}


def save_history(history):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temp_file = DATA_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2,
        )

    temp_file.replace(DATA_FILE)


# ============================================================
# Firecrawl
# ============================================================

def firecrawl_scrape(url, formats=None):
    if not FIRECRAWL_API_KEY:
        print("FIRECRAWL_API_KEY 未设置")
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
            timeout=FIRECRAWL_TIMEOUT,
        )

        print(f"Firecrawl HTTP {response.status_code}: {url}")

        if response.status_code == 429:
            print("Firecrawl 限流，等待 35 秒...")
            time.sleep(RATE_LIMIT_WAIT)
            return None

        if response.status_code != 200:
            print("Firecrawl 请求失败：", response.text[:500])
            return None

        data = response.json()

        return data.get("data", data)

    except Exception as exc:
        print("Firecrawl 请求异常：", exc)
        return None


# ============================================================
# 价格 / 折扣提取
# ============================================================

def extract_currency(product):
    if not isinstance(product, dict):
        return ""

    keys = [
        "currency",
        "currencyCode",
        "currency_code",
    ]

    for key in keys:
        value = product.get(key)

        if value:
            return clean_text(value).upper()

    return ""


def infer_currency(product, item):
    currency = extract_currency(product)

    if currency:
        return currency

    url = clean_text(
        item.get("url", "") if isinstance(item, dict) else ""
    ).lower()

    source = clean_text(
        item.get("source", "") if isinstance(item, dict) else ""
    ).lower()

    if (
        "patagonia.ca" in url
        or "arcteryx.com/ca/" in url
        or "thenorthface.com/en-ca/" in url
        or "canada" in source
    ):
        return "CAD"

    return "USD"


def extract_price_from_value(value):
    if isinstance(value, dict):
        for key in [
            "price",
            "salePrice",
            "currentPrice",
            "amount",
            "value",
        ]:
            result = safe_float(value.get(key))

            if result is not None:
                return result

    return safe_float(value)


def extract_prices(product):
    if not isinstance(product, dict):
        return []

    candidates = []

    # 常见字段
    keys = [
        "price",
        "salePrice",
        "currentPrice",
        "sellingPrice",
        "sale_price",
        "current_price",
    ]

    for key in keys:
        if key in product:
            value = extract_price_from_value(product.get(key))

            if value is not None:
                candidates.append(value)

    # product price 列表
    for key in [
        "prices",
        "priceRange",
        "price_range",
    ]:
        value = product.get(key)

        if isinstance(value, list):
            for item in value:
                price = extract_price_from_value(item)

                if price is not None:
                    candidates.append(price)

        elif isinstance(value, dict):
            for item in value.values():
                price = extract_price_from_value(item)

                if price is not None:
                    candidates.append(price)

    # 去重
    result = []

    for price in candidates:
        if price > 0 and price < 1000000:
            if price not in result:
                result.append(price)

    return result


def extract_original_price(product):
    if not isinstance(product, dict):
        return None

    keys = [
        "originalPrice",
        "listPrice",
        "regularPrice",
        "compareAtPrice",
        "original_price",
        "list_price",
    ]

    for key in keys:
        value = extract_price_from_value(product.get(key))

        if value is not None and value > 0:
            return value

    return None


def extract_discount(product, current_price, original_price):
    if current_price is None:
        return None

    if original_price is not None and original_price > current_price:
        return round(
            (original_price - current_price)
            / original_price
            * 100,
            1,
        )

    if isinstance(product, dict):
        for key in [
            "discountPercent",
            "discountPercentage",
            "discount",
        ]:
            value = safe_float(product.get(key))

            if value is not None:
                if value <= 1:
                    value *= 100

                return round(value, 1)

    return 0.0


# ============================================================
# 产品颜色 / 尺码 / 库存
# ============================================================

def extract_variant_info(product):
    colors = []

    if not isinstance(product, dict):
        return colors

    variants = []

    for key in [
        "variants",
        "variantOptions",
        "options",
        "skus",
    ]:
        value = product.get(key)

        if isinstance(value, list):
            variants.extend(value)

    for item in variants:
        if not isinstance(item, dict):
            continue

        color = clean_text(
            item.get("color")
            or item.get("colour")
            or item.get("colorName")
        )

        size = clean_text(
            item.get("size")
            or item.get("sizeName")
        )

        inventory = (
            item.get("inventory")
            if item.get("inventory") is not None
            else item.get("stock")
        )

        if color:
            found = None

            for group in colors:
                if group["color"].lower() == color.lower():
                    found = group
                    break

            if found is None:
                found = {
                    "color": color,
                    "sizes": [],
                    "inventory": None,
                }
                colors.append(found)

            if size and size not in found["sizes"]:
                found["sizes"].append(size)

            if inventory is not None:
                found["inventory"] = inventory

    return colors


# ============================================================
# 产品数据整理
# ============================================================

def build_current_product(item, product):
    if not isinstance(product, dict):
        product = {}

    url = clean_text(item.get("url", ""))

    title = clean_text(
        product.get("title")
        or product.get("name")
        or item.get("name")
        or title_from_url(url)
    )

    prices = extract_prices(product)

    current_price = min(prices) if prices else None

    original_price = extract_original_price(product)

    if original_price is None and prices:
        possible_original = max(prices)

        if possible_original > current_price:
            original_price = possible_original

    discount = extract_discount(
        product,
        current_price,
        original_price,
    )

    currency = infer_currency(product, item)

    variants = extract_variant_info(product)

    return {
        "name": title,
        "url": url,
        "current_price": current_price,
        "original_price": original_price,
        "discount": discount or 0,
        "currency": currency,
        "variants": variants,
        "source": item.get("source", ""),
        "raw": product,
    }


# ============================================================
# 价格组
# ============================================================

def get_min_actual_price(product):
    return safe_float(product.get("current_price"))


def get_max_discount(product):
    return safe_float(product.get("discount")) or 0


def build_price_groups(product):
    variants = product.get("variants", [])

    if not variants:
        return []

    groups = []

    for item in variants:
        if not isinstance(item, dict):
            continue

        color = clean_text(item.get("color"))

        if not color:
            continue

        sizes = item.get("sizes", [])

        if not isinstance(sizes, list):
            sizes = []

        inventory = item.get("inventory")

        groups.append(
            {
                "color": color,
                "sizes": sizes,
                "inventory": inventory,
            }
        )

    return groups


# ============================================================
# 人民币汇率
# ============================================================

def get_exchange_rate(currency):
    currency = clean_text(currency).upper()

    if not currency:
        return None

    if currency == "CNY":
        return 1.0

    now = time.time()

    cached_rate = EXCHANGE_RATE_CACHE.get(currency)

    cached_time = EXCHANGE_RATE_CACHE_TIME.get(
        currency,
        0,
    )

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
            print(
                "汇率获取失败：",
                response.status_code,
            )

            return cached_rate

        data = response.json()

        rates = data.get("rates", {})

        rate = safe_float(rates.get("CNY"))

        if rate is None:
            return cached_rate

        EXCHANGE_RATE_CACHE[currency] = rate

        EXCHANGE_RATE_CACHE_TIME[currency] = now

        print(
            f"当前汇率：1 {currency} = "
            f"{rate:.4f} CNY"
        )

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

    return round(
        float(price) * rate,
        2,
    )


# ============================================================
# 得物
# ============================================================

def normalize_product_name(text):
    text = clean_text(text).lower()

    replacements = [
        ("arc'teryx", ""),
        ("arcteryx", ""),
        ("patagonia", ""),
        ("the north face", ""),
        ("north face", ""),
        ("men's", ""),
        ("mens", ""),
        ("men’s", ""),
        ("男款", ""),
        ("男士", ""),
    ]

    for old, new in replacements:
        text = text.replace(old, new)

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return clean_text(text)


def search_dewu_products(keyword):
    """
    得物搜索。

    注意：
    这里使用的是公开可观察到的 H5 搜索接口，
    不是稳定的官方开放平台 API。
    如果接口变化，程序会自动返回不可用，
    不会影响主监控。
    """

    try:
        response = SESSION.get(
            "https://app.dewu.com/api/v1/h5/search/fire/search/list",
            params={
                "title": keyword,
                "page": 0,
                "sortType": 0,
                "sortMode": 1,
                "limit": 20,
                "showHot": -1,
            },
            timeout=20,
        )

        if response.status_code != 200:
            print(
                "得物搜索失败：",
                response.status_code,
            )
            return []

        data = response.json()

        root = data.get("data", {})

        products = root.get(
            "productList",
            [],
        )

        if not isinstance(products, list):
            return []

        return products

    except Exception as exc:
        print("得物搜索异常：", exc)

        return []


def match_dewu_product(title, products):
    target = normalize_product_name(title)

    if not target:
        return None

    target_words = set(target.split())

    best = None
    best_score = 0

    for item in products:
        if not isinstance(item, dict):
            continue

        item_title = clean_text(
            item.get("title")
        )

        if not item_title:
            continue

        candidate = normalize_product_name(
            item_title
        )

        candidate_words = set(
            candidate.split()
        )

        if not candidate_words:
            continue

        overlap = len(
            target_words & candidate_words
        ) / max(
            len(target_words),
            1,
        )

        # 产品匹配至少达到一定程度
        if overlap < 0.35:
            continue

        if overlap > best_score:
            best_score = overlap
            best = item

    return best


def get_dewu_spu_id(item):
    if not isinstance(item, dict):
        return None

    return (
        item.get("spuId")
        or item.get("spuid")
        or item.get("productId")
    )


def get_dewu_search_price(item):
    if not isinstance(item, dict):
        return None

    for key in [
        "minSalePrice",
        "spuMinSalePrice",
        "price",
    ]:
        value = safe_float(
            item.get(key)
        )

        if value is None:
            continue

        # 得物部分接口价格单位为分
        if value >= 10000:
            value = value / 100

        if value > 0:
            return value

    return None


def extract_dewu_size_prices(data):
    """
    尝试从得物返回的数据里找：
    尺码 -> 价格。

    不同版本接口字段可能不同，因此采用
    多种字段兼容方式。
    """

    results = []

    def walk(value):
        if isinstance(value, dict):

            size = clean_text(
                value.get("size")
                or value.get("sizeName")
                or value.get("skuName")
                or value.get("propertyValue")
            )

            price = None

            for key in [
                "minPrice",
                "salePrice",
                "price",
                "minSalePrice",
                "spuMinSalePrice",
            ]:
                price = safe_float(
                    value.get(key)
                )

                if price is not None:
                    break

            if (
                size
                and price is not None
                and price > 0
            ):
                if price >= 10000:
                    price = price / 100

                results.append(
                    (
                        size.upper(),
                        price,
                    )
                )

            for child in value.values():
                walk(child)

        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)

    # 去重
    output = []

    seen = set()

    for size, price in results:
        key = (
            size,
            round(price, 2),
        )

        if key in seen:
            continue

        seen.add(key)

        output.append(
            (
                size,
                price,
            )
        )

    return output


def get_dewu_size_prices(spu_id):
    """
    尝试查询得物商品 SKU/尺码价格。

    由于该接口可能需要签名、风控或动态参数，
    失败时直接返回空，不影响主监控。
    """

    if not spu_id:
        return []

    try:
        response = SESSION.get(
            "https://dewu.pdd.is/api/search/prices/now",
            params={
                "spuid": spu_id,
            },
            timeout=20,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        return extract_dewu_size_prices(
            data
        )

    except Exception as exc:
        print(
            "得物尺码价格查询异常：",
            exc,
        )

        return []


def get_dewu_price(title):
    """
    得物价格规则：

    1. 优先 L 码
    2. L 码不可用 -> 所有可靠尺码中的最低价
    3. 无可靠匹配 -> None
    """

    if not title:
        return None

    keyword = clean_text(title)

    products = search_dewu_products(
        keyword
    )

    if not products:
        return None

    target = match_dewu_product(
        title,
        products,
    )

    if target is None:
        print(
            "得物没有找到可靠的同款匹配"
        )
        return None

    spu_id = get_dewu_spu_id(
        target
    )

    # --------------------------------------------------------
    # 第一优先：L 码
    # --------------------------------------------------------

    size_prices = get_dewu_size_prices(
        spu_id
    )

    l_prices = []

    all_prices = []

    for size, price in size_prices:

        if price is None:
            continue

        if price <= 0:
            continue

        all_prices.append(price)

        normalized_size = (
            clean_text(size)
            .upper()
            .replace(" ", "")
        )

        if normalized_size in [
            "L",
            "L码",
            "L号",
        ]:
            l_prices.append(price)

    if l_prices:
        price = min(l_prices)

        print(
            f"得物 L 码参考价：¥{price:.0f}"
        )

        return round(
            price,
            2,
        )

    # --------------------------------------------------------
    # 第二优先：所有尺码最低价
    # --------------------------------------------------------

    if all_prices:
        price = min(all_prices)

        print(
            f"得物 L 码不可用，"
            f"改取最低价：¥{price:.0f}"
        )

        return round(
            price,
            2,
        )

    # --------------------------------------------------------
    # 最后才使用搜索结果最低价
    # --------------------------------------------------------

    fallback_price = (
        get_dewu_search_price(
            target
        )
    )

    if fallback_price is not None:
        print(
            f"得物尺码数据不可用，"
            f"使用搜索最低参考价："
            f"¥{fallback_price:.0f}"
        )

        return round(
            fallback_price,
            2,
        )

    print(
        "得物没有找到可靠价格"
    )

    return None


# ============================================================
# Telegram
# ============================================================

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN 未设置")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID 未设置")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}"
        "/sendMessage"
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
            timeout=30,
        )

        if response.status_code != 200:
            print(
                "Telegram 推送失败：",
                response.text[:500],
            )
            return False

        print("Telegram 推送成功")

        return True

    except Exception as exc:
        print(
            "Telegram 推送异常：",
            exc,
        )

        return False


# ============================================================
# Telegram 商品消息
# ============================================================

def build_product_message(
    product,
    previous_price=None,
):
    title = clean_text(
        product.get("name")
    )

    current_price = get_min_actual_price(
        product
    )

    original_price = safe_float(
        product.get("original_price")
    )

    max_discount = get_max_discount(
        product
    )

    currency = clean_text(
        product.get("currency")
    )

    url = clean_text(
        product.get("url")
    )

    lines = []

    if max_discount >= SUPER_DISCOUNT:
        lines.append("🔥🔥 超级折扣")

    elif max_discount >= IMPORTANT_DISCOUNT:
        lines.append("🔥 重要折扣")

    else:
        lines.append("🛍️ 商品价格变化")

    lines.append("")
    lines.append(f"📦 {title}")

    # --------------------------------------------------------
    # 人民币参考价
    # --------------------------------------------------------

    cny_price = convert_to_cny(
        current_price,
        currency,
    )

    if cny_price is not None:
        lines.append(
            f"🇨🇳 人民币参考价："
            f"¥{cny_price:,.0f}"
        )
        lines.append(
            "💱 按实时汇率换算"
        )
    else:
        lines.append(
            "🇨🇳 人民币参考价：暂不可用"
        )

    # --------------------------------------------------------
    # 得物参考价
    # --------------------------------------------------------

    dewu_price = get_dewu_price(
        title
    )

    if dewu_price is not None:
        lines.append(
            f"🛒 得物参考价："
            f"¥{dewu_price:,.0f}"
        )
    else:
        lines.append(
            "🛒 得物参考价：暂不可用"
        )

    lines.append("")

    # --------------------------------------------------------
    # 折扣
    # --------------------------------------------------------

    lines.append(
        f"🏷️ 折扣："
        f"{max_discount:.1f}%"
    )

    if original_price is not None:
        lines.append(
            f"💰 原价："
            f"{currency} "
            f"{original_price:,.2f}"
        )

    if current_price is not None:
        lines.append(
            f"💵 当前实际价："
            f"{currency} "
            f"{current_price:,.2f}"
        )

    # --------------------------------------------------------
    # 价格下降
    # --------------------------------------------------------

    if (
        previous_price is not None
        and current_price is not None
        and current_price < previous_price
    ):
        drop = previous_price - current_price

        lines.append(
            f"📉 价格下降："
            f"{currency} "
            f"{drop:,.2f}"
        )

        lines.append(
            f"🔻 {previous_price:,.2f}"
            f" → "
            f"{current_price:,.2f}"
        )

    # --------------------------------------------------------
    # 颜色 / 尺码 / 库存
    # --------------------------------------------------------

    groups = build_price_groups(
        product
    )

    if groups:
        lines.append("")
        lines.append("🎨 颜色 / 尺码 / 库存：")

        for group in groups:
            color = group.get(
                "color",
                "",
            )

            sizes = group.get(
                "sizes",
                [],
            )

            inventory = group.get(
                "inventory"
            )

            size_text = (
                ", ".join(
                    sizes
                )
                if sizes
                else "暂无"
            )

            inventory_text = (
                str(inventory)
                if inventory is not None
                else "暂无"
            )

            lines.append(
                f"• {color}"
            )

            lines.append(
                f"  尺码：{size_text}"
            )

            lines.append(
                f"  库存：{inventory_text}"
            )

    # --------------------------------------------------------
    # 商品链接
    # --------------------------------------------------------

    if url:
        lines.append("")
        lines.append(
            f"🔗 {url}"
        )

    return "\n".join(lines)


# ============================================================
# 推送判断
# ============================================================

def should_alert(
    product,
    previous_price,
):
    current_price = get_min_actual_price(
        product
    )

    discount = get_max_discount(
        product
    )

    if current_price is None:
        print(
            "没有当前实际价格：不推送"
        )
        return False

    if discount < MIN_DISCOUNT:
        print(
            f"折扣不足 {MIN_DISCOUNT}%："
            f"不推送"
        )
        return False

    if previous_price is None:
        print(
            "首次发现商品：不推送"
        )
        return False

    if current_price < previous_price:
        print(
            "实际价格下降：准备推送"
        )
        return True

    if current_price == previous_price:
        print(
            "实际现价没有变化：不推送"
        )
        return False

    if current_price > previous_price:
        print(
            "实际价格上涨：不推送"
        )
        return False

    return False


# ============================================================
# 保存历史
# ============================================================

def save_product_history(
    history,
    product,
):
    url = clean_text(
        product.get("url")
    )

    current_price = get_min_actual_price(
        product
    )

    if not url or current_price is None:
        return

    history[url] = {
        "name": product.get("name", ""),
        "price": current_price,
        "currency": product.get(
            "currency",
            "",
        ),
        "updated_at": int(
            time.time()
        ),
    }


# ============================================================
# 单商品检查
# ============================================================

def check_product(
    item,
    history,
):
    print(
        "检查：",
        item.get("name", ""),
    )

    product_data = firecrawl_scrape(
        item["url"],
        formats=["product"],
    )

    if not product_data:
        print(
            "没有获取到商品数据"
        )
        return

    product = build_current_product(
        item,
        product_data,
    )

    current_price = get_min_actual_price(
        product
    )

    if current_price is None:
        print(
            "没有获取到有效价格"
        )
        return

    print(
        f"当前最低实际价格："
        f"{current_price}"
    )

    old = history.get(
        item["url"]
    )

    previous_price = None

    if isinstance(old, dict):
        previous_price = safe_float(
            old.get("price")
        )

    if previous_price is not None:
        print(
            f"上次实际价格："
            f"{previous_price}"
        )

    if should_alert(
        product,
        previous_price,
    ):
        message = build_product_message(
            product,
            previous_price,
        )

        send_telegram_message(
            message
        )

    save_product_history(
        history,
        product,
    )


# ============================================================
# 自动发现链接
# ============================================================

ALLOWED_BRANDS = [
    "arcteryx",
    "arc'teryx",
    "patagonia",
    "the north face",
    "thenorthface",
]


def is_allowed_discovery_product(
    url,
):
    text = clean_text(url).lower()

    # 排除包 / 行李
    excluded = [
        "bag",
        "bags",
        "backpack",
        "luggage",
        "duffel",
        "travel",
        "suitcase",
        "gear",
        "equipment",
        "camping",
        "tent",
        "sleeping",
        "chair",
        "stove",
        "cooler",
        "accessories",
        "accessory",
        "footwear",
        "shoes",
        "shoe",
        "sandals",
        "boots",
        "hat",
        "hats",
        "gloves",
        "socks",
    ]

    if any(
        word in text
        for word in excluded
    ):
        return False

    # 排除明显的非目标服装
    excluded_clothing = [
        "t-shirt",
        "tshirt",
        "tee",
        "polo",
        "sweatshirt",
        "hoodie",
    ]

    if any(
        word in text
        for word in excluded_clothing
    ):
        return False

    # 男装
    mens_ok = (
        "mens" in text
        or "men's" in text
        or "/mens/" in text
        or "/men/" in text
        or "-mens" in text
        or "-men-" in text
    )

    if not mens_ok:
        return False

    # 目标类别
    allowed_category = [
        "jacket",
        "jackets",
        "softshell",
        "soft-shell",
        "hardshell",
        "hard-shell",
        "rain",
        "down",
        "pants",
        "pant",
        "trouser",
    ]

    if not any(
        word in text
        for word in allowed_category
    ):
        return False

    return True


def is_allowed_brand(
    url,
    source_name="",
):
    text = (
        clean_text(url)
        + " "
        + clean_text(source_name)
    ).lower()

    return any(
        brand in text
        for brand in ALLOWED_BRANDS
    )


def is_product_url(
    url,
    source_name="",
):
    parsed = urlparse(url)

    host = parsed.netloc.lower()

    if not host:
        return False

    allowed_hosts = [
        "rei.com",
        "arcteryx.com",
        "outlet.arcteryx.com",
        "patagonia.com",
        "patagonia.ca",
        "thenorthface.com",
    ]

    if not any(
        host.endswith(
            allowed
        )
        for allowed in allowed_hosts
    ):
        return False

    if not is_allowed_brand(
        url,
        source_name,
    ):
        # REI 本身可能没有品牌写进 URL，
        # 由后续商品标题再做品牌判断。
        if "rei.com" not in host:
            return False

    return is_allowed_discovery_product(
        url
    )


def discover_links(source):
    source_name = source["name"]
    source_url = source["url"]

    print(
        "自动发现：",
        source_name,
    )

    data = firecrawl_scrape(
        source_url,
        formats=["markdown"],
    )

    if not data:
        return []

    markdown = clean_text(
        data.get("markdown", "")
    )

    html = clean_text(
        data.get("html", "")
    )

    links = set()

    # Markdown 链接
    for match in re.findall(
        r"\[[^\]]*\]\((https?://[^)\s]+)\)",
        markdown,
    ):
        links.add(match)

    # HTML 链接
    if html:
        try:
            soup = BeautifulSoup(
                html,
                "lxml",
            )

            for a in soup.find_all(
                "a",
                href=True,
            ):
                href = a.get("href")

                if href.startswith("/"):
                    href = urljoin(
                        source_url,
                        href,
                    )

                if href.startswith(
                    "http://"
                ) or href.startswith(
                    "https://"
                ):
                    links.add(href)

        except Exception as exc:
            print(
                "解析 HTML 失败：",
                exc,
            )

    # 原始 URL
    for url in re.findall(
        r"https?://[^\s\"'<>]+",
        markdown + " " + html,
    ):
        links.add(url)

    result = []

    for url in links:
        url = url.rstrip(
            ".,);]}>\"'"
        )

        if not is_product_url(
            url,
            source_name,
        ):
            continue

        result.append(
            {
                "name": title_from_url(
                    url
                ),
                "url": url,
                "source": source_name,
            }
        )

    return result


# ============================================================
# 自动发现商品详情过滤
# ============================================================

def product_matches_allowed_brand(
    product,
):
    text = clean_text(
        product.get("name", "")
    ).lower()

    if not text:
        return False

    return any(
        brand in text
        for brand in ALLOWED_BRANDS
    )


def discovery_products():
    results = []

    # 每次运行轮换少量来源，
    # 避免 Firecrawl 超过限制。
    timestamp = int(
        time.time()
        / 1800
    )

    source_count = len(
        DISCOVERY_SOURCES
    )

    if source_count == 0:
        return []

    start = (
        timestamp
        % source_count
    )

    selected = []

    for i in range(
        min(2, source_count)
    ):
        selected.append(
            DISCOVERY_SOURCES[
                (start + i)
                % source_count
            ]
        )

    for source in selected:
        links = discover_links(
            source
        )

        for item in links:
            if len(results) >= DISCOVERY_LIMIT:
                break

            results.append(item)

        if len(results) >= DISCOVERY_LIMIT:
            break

        time.sleep(
            FIRECRAWL_DELAY
        )

    return results


# ============================================================
# 固定商品轮换
# ============================================================

def get_rotation_products():
    timestamp = int(
        time.time()
        / 1800
    )

    total = len(
        FIXED_PRODUCTS
    )

    if total == 0:
        return []

    start = (
        timestamp
        % total
    )

    selected = []

    for i in range(
        min(
            FIXED_ROTATION,
            total,
        )
    ):
        selected.append(
            FIXED_PRODUCTS[
                (start + i)
                % total
            ]
        )

    return selected


# ============================================================
# 主程序
# ============================================================

def main():
    print("=" * 60)
    print("Outdoor Price Monitor")
    print("=" * 60)

    if not FIRECRAWL_API_KEY:
        print(
            "警告：FIRECRAWL_API_KEY 未设置"
        )

    if not TELEGRAM_BOT_TOKEN:
        print(
            "警告：TELEGRAM_BOT_TOKEN 未设置"
        )

    if not TELEGRAM_CHAT_ID:
        print(
            "警告：TELEGRAM_CHAT_ID 未设置"
        )

    history = load_history()

    # --------------------------------------------------------
    # 固定商品
    # --------------------------------------------------------

    fixed_products = get_rotation_products()

    print(
        f"本次检查固定商品："
        f"{len(fixed_products)}"
    )

    all_products = []

    for item in fixed_products:
        all_products.append(item)

    # --------------------------------------------------------
    # 自动发现
    # --------------------------------------------------------

    discovered = discovery_products()

    fixed_urls = {
        item["url"]
        for item in fixed_products
    }

    for item in discovered:
        if item["url"] in fixed_urls:
            continue

        all_products.append(item)

    # 去重
    unique = []

    seen = set()

    for item in all_products:
        url = item.get("url")

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)

        unique.append(item)

    all_products = unique

    print(
        f"本次实际检查商品："
        f"{len(all_products)}"
    )

    # --------------------------------------------------------
    # 开始检查
    # --------------------------------------------------------

    for index, item in enumerate(
        all_products,
        start=1,
    ):
        print("")
        print(
            f"========== "
            f"{index}/{len(all_products)} "
            f"=========="
        )

        try:
            check_product(
                item,
                history,
            )

        except Exception as exc:
            print(
                "检查商品出现异常：",
                exc,
            )

        # Firecrawl 限流保护
        if index < len(all_products):
            print(
                "等待 10 秒，"
                "避免 Firecrawl 限流..."
            )

            time.sleep(
                FIRECRAWL_DELAY
            )

    # --------------------------------------------------------
    # 保存价格历史
    # --------------------------------------------------------

    save_history(history)

    print("")
    print("=" * 60)
    print("本次监控完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
