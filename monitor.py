import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup


# ============================================================
# 基本设置
# ============================================================

FIRECRAWL_API = "https://api.firecrawl.dev/v2/scrape"

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

FIRECRAWL_API_KEY = os.getenv(
    "FIRECRAWL_API_KEY",
    ""
).strip()

HISTORY_FILE = "data/prices.json"

REQUEST_TIMEOUT = 90

# Firecrawl 限流保护
FIRECRAWL_WAIT_SECONDS = 12

# 每次运行最多抓几个商品详情
MAX_DETAIL_PER_RUN = 3


# ============================================================
# 重点商品
# ============================================================

WATCHLIST = [
    "gamma mx",
    "gamma jacket",
    "gamma pant",
    "gamma pants",

    "beta ar",
    "beta jacket",
    "beta lt",

    "atom insulated jacket",
    "atom insulated hoody",
    "atom insulated hoodie",
    "atom jacket",

    "r2 techface jacket",
    "r2 techface hoody",
    "r2 techface hoodie",

    "capilene cool daily graphic hoody",
    "capilene cool daily graphic hoodie",

    "c1",
]


# ============================================================
# REI 品牌页面
# ============================================================

BRAND_PAGES = [
    (
        "Arc'teryx",
        "https://www.rei.com/b/arcteryx/c/all"
    ),
    (
        "Patagonia",
        "https://www.rei.com/b/patagonia/c/all"
    ),
    (
        "The North Face",
        "https://www.rei.com/b/the-north-face/c/all"
    ),
]


# ============================================================
# 汇率
# ============================================================

# 暂时使用 USD -> RMB
# 后面再接实时汇率
RATES_TO_RMB = {
    "USD": 7.15
}


# ============================================================
# 基础工具
# ============================================================

def clean_text(text):

    if text is None:
        return ""

    text = html.unescape(
        str(text)
    )

    text = text.replace(
        "\u00a0",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_name(text):

    text = clean_text(
        text
    ).lower()

    text = text.replace(
        "’",
        "'"
    )

    text = text.replace(
        "–",
        "-"
    )

    text = text.replace(
        "—",
        "-"
    )

    return text


def ensure_history_file():

    os.makedirs(
        "data",
        exist_ok=True
    )

    if not os.path.exists(
        HISTORY_FILE
    ):

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {},
                f,
                ensure_ascii=False,
                indent=2
            )


def load_history():

    ensure_history_file()

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            if isinstance(
                data,
                dict
            ):
                return data

    except Exception as e:

        print(
            "读取价格历史失败:",
            e
        )

    return {}


def save_history(history):

    ensure_history_file()

    temp_file = (
        HISTORY_FILE
        + ".tmp"
    )

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

    os.replace(
        temp_file,
        HISTORY_FILE
    )


# ============================================================
# Firecrawl
# ============================================================

def firecrawl(
    url,
    formats=None
):

    if formats is None:

        formats = [
            "markdown"
        ]

    if not FIRECRAWL_API_KEY:

        print(
            "错误："
            "FIRECRAWL_API_KEY "
            "没有读取到"
        )

        return None

    headers = {
        "Authorization":
            f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type":
            "application/json"
    }

    payload = {
        "url": url,
        "formats": formats,
        "onlyMainContent": False,
        "waitFor": 3000
    }

    try:

        response = requests.post(
            FIRECRAWL_API,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        print(
            "Firecrawl:",
            response.status_code,
            url
        )

        # ----------------------------------------------------
        # 429 限流
        # ----------------------------------------------------

        if response.status_code == 429:

            print(
                "Firecrawl 触发限流，"
                "本次跳过这个请求。"
            )

            return None

        if response.status_code != 200:

            print(
                response.text[:1000]
            )

            return None

        data = response.json()

        if not data.get(
            "success",
            True
        ):

            print(
                "Firecrawl 返回失败:",
                data
            )

            return None

        return data

    except Exception as e:

        print(
            "Firecrawl 请求异常:",
            e
        )

        return None


# ============================================================
# 商品匹配
# ============================================================

def is_watch_product(text):

    text = normalize_name(
        text
    )

    for keyword in WATCHLIST:

        keyword = normalize_name(
            keyword
        )

        if keyword == "c1":

            if re.search(
                r"\bc1\b",
                text
            ):
                return True

        else:

            if keyword in text:

                return True

    return False


# ============================================================
# 提取 REI 商品链接
# ============================================================

def extract_links_from_markdown(
    markdown,
    brand
):

    if not markdown:

        return []

    results = []

    seen = set()

    # --------------------------------------------------------
    # Markdown 链接
    # --------------------------------------------------------

    pattern = re.compile(
        r"\[([^\]]+)\]"
        r"\((https?://www\.rei\.com/"
        r"[^)\s]+|/[^)\s]+)\)",
        re.I
    )

    for match in pattern.finditer(
        markdown
    ):

        title = clean_text(
            match.group(1)
        )

        href = match.group(2)

        if href.startswith(
            "/"
        ):

            href = (
                "https://www.rei.com"
                + href
            )

        href = (
            href
            .split("?")[0]
            .split("#")[0]
        )

        if (
            "/product/" not in href
            and "/products/" not in href
        ):

            continue

        if href in seen:

            continue

        combined = normalize_name(
            title
            + " "
            + href
        )

        if is_watch_product(
            combined
        ):

            seen.add(
                href
            )

            results.append({
                "brand": brand,
                "title": title,
                "url": href
            })

    # --------------------------------------------------------
    # 直接 URL
    # --------------------------------------------------------

    url_pattern = re.compile(
        r"https?://www\.rei\.com/"
        r"(?:product|products)/"
        r"[^\s)\]\"<>]+",
        re.I
    )

    for match in url_pattern.finditer(
        markdown
    ):

        href = match.group(0)

        href = (
            href
            .rstrip(".,;")
            .split("?")[0]
            .split("#")[0]
        )

        if href in seen:

            continue

        start = max(
            0,
            match.start() - 700
        )

        end = min(
            len(markdown),
            match.end() + 700
        )

        nearby = markdown[
            start:end
        ]

        combined = normalize_name(
            href
            + " "
            + nearby
        )

        if is_watch_product(
            combined
        ):

            seen.add(
                href
            )

            results.append({
                "brand": brand,
                "title": "",
                "url": href
            })

    return results


# ============================================================
# 金额处理
# ============================================================

def parse_money(value):

    if value is None:

        return None

    text = str(value)

    text = text.replace(
        ",",
        ""
    )

    text = text.replace(
        "$",
        ""
    )

    text = text.replace(
        "US",
        ""
    )

    text = text.replace(
        "USD",
        ""
    )

    match = re.search(
        r"(\d+(?:\.\d{1,2})?)",
        text
    )

    if not match:

        return None

    try:

        return float(
            match.group(1)
        )

    except Exception:

        return None


def money(value):

    if value is None:

        return ""

    value = float(
        value
    )

    if value.is_integer():

        return (
            f"${int(value)}"
        )

    return (
        f"${value:.2f}"
    )


def calculate_discount(
    original,
    current
):

    if (
        not original
        or not current
        or original <= current
    ):

        return 0

    return round(
        (
            original - current
        )
        / original
        * 100
    )


def usd_to_rmb(value):

    if value is None:

        return None

    return round(
        float(value)
        * RATES_TO_RMB["USD"]
    )


# ============================================================
# JSON 递归
# ============================================================

def recursive_objects(obj):

    if isinstance(
        obj,
        dict
    ):

        yield obj

        for value in obj.values():

            yield from recursive_objects(
                value
            )

    elif isinstance(
        obj,
        list
    ):

        for value in obj:

            yield from recursive_objects(
                value
            )


def get_value(
    obj,
    keys
):

    if not isinstance(
        obj,
        dict
    ):

        return None

    lower_map = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in keys:

        if (
            key.lower()
            in lower_map
        ):

            return lower_map[
                key.lower()
            ]

    return None


# ============================================================
# 颜色
# ============================================================

def detect_color(obj):

    value = get_value(
        obj,
        [
            "color",
            "colour",
            "colorName",
            "color_name",
            "colourName",
            "swatchName",
            "variantColor",
            "optionColor",
            "displayColor",
            "displayColour"
        ]
    )

    if value is None:

        return ""

    if isinstance(
        value,
        dict
    ):

        value = get_value(
            value,
            [
                "name",
                "label",
                "value",
                "displayName"
            ]
        )

    return clean_text(
        value
    )


# ============================================================
# 尺码
# ============================================================

def detect_size(obj):

    value = get_value(
        obj,
        [
            "size",
            "sizeName",
            "size_name",
            "variantSize",
            "dimension",
            "optionSize",
            "displaySize"
        ]
    )

    if value is None:

        return ""

    if isinstance(
        value,
        dict
    ):

        value = get_value(
            value,
            [
                "name",
                "label",
                "value",
                "displayName"
            ]
        )

    return clean_text(
        value
    )


# ============================================================
# 库存
# ============================================================

def detect_availability(obj):

    value = get_value(
        obj,
        [
            "availability",
            "available",
            "inStock",
            "in_stock",
            "isAvailable",
            "stockStatus",
            "inventoryStatus",
            "availabilityStatus"
        ]
    )

    if isinstance(
        value,
        dict
    ):

        value = get_value(
            value,
            [
                "status",
                "value",
                "label",
                "name"
            ]
        )

    if isinstance(
        value,
        bool
    ):

        return value

    if value is None:

        return None

    text = normalize_name(
        value
    )

    if any(
        x in text
        for x in [
            "out of stock",
            "sold out",
            "unavailable",
            "out-of-stock",
            "false"
        ]
    ):

        return False

    if any(
        x in text
        for x in [
            "in stock",
            "available",
            "true",
            "add to cart"
        ]
    ):

        return True

    return None


# ============================================================
# 当前价格
# ============================================================

def detect_price(obj):

    value = get_value(
        obj,
        [
            "salePrice",
            "sale_price",
            "currentPrice",
            "current_price",
            "sellingPrice",
            "selling_price",
            "price",
            "finalPrice",
            "sale"
        ]
    )

    if isinstance(
        value,
        dict
    ):

        value = get_value(
            value,
            [
                "amount",
                "value",
                "price"
            ]
        )

    return parse_money(
        value
    )


# ============================================================
# 原价
# ============================================================

def detect_original_price(obj):

    value = get_value(
        obj,
        [
            "originalPrice",
            "original_price",
            "regularPrice",
            "regular_price",
            "listPrice",
            "list_price",
            "compareAtPrice",
            "compare_at_price",
            "msrp",
            "wasPrice",
            "was_price",
            "retailPrice",
            "retail_price"
        ]
    )

    if isinstance(
        value,
        dict
    ):

        value = get_value(
            value,
            [
                "amount",
                "value",
                "price"
            ]
        )

    return parse_money(
        value
    )


# ============================================================
# 变体判断
# ============================================================

def object_looks_like_variant(
    obj
):

    if not isinstance(
        obj,
        dict
    ):

        return False

    price = detect_price(
        obj
    )

    color = detect_color(
        obj
    )

    size = detect_size(
        obj
    )

    availability = detect_availability(
        obj
    )

    if price is None:

        return False

    if color or size:

        return True

    if availability is not None:

        return True

    return False


# ============================================================
# JSON 提取变体
# ============================================================

def extract_variants_from_json(
    data
):

    variants = []

    for obj in recursive_objects(
        data
    ):

        if not object_looks_like_variant(
            obj
        ):

            continue

        current = detect_price(
            obj
        )

        if current is None:

            continue

        original = detect_original_price(
            obj
        )

        if original is None:

            original = current

        color = detect_color(
            obj
        )

        size = detect_size(
            obj
        )

        available = detect_availability(
            obj
        )

        variants.append({
            "price": current,
            "original": original,
            "color": (
                color
                or "未标注颜色"
            ),
            "size": (
                size
                or "未标注尺码"
            ),
            "available": available
        })

    return variants


# ============================================================
# HTML JSON
# ============================================================

def extract_json_scripts(
    raw_html
):

    if not raw_html:

        return []

    soup = BeautifulSoup(
        raw_html,
        "html.parser"
    )

    results = []

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        text = (
            script.string
            or script.get_text()
        )

        if not text:

            continue

        try:

            results.append(
                json.loads(
                    text
                )
            )

        except Exception:

            pass

    # --------------------------------------------------------
    # 普通 JSON script
    # --------------------------------------------------------

    for script in soup.find_all(
        "script"
    ):

        text = (
            script.string
            or script.get_text()
        )

        if not text:

            continue

        text = text.strip()

        if len(text) < 100:

            continue

        if (
            "__NEXT_DATA__"
            in text
        ):

            continue

        if not (
            text.startswith("{")
            or text.startswith("[")
        ):

            continue

        try:

            results.append(
                json.loads(
                    text
                )
            )

        except Exception:

            pass

    # --------------------------------------------------------
    # NEXT DATA
    # --------------------------------------------------------

    script = soup.find(
        "script",
        id="__NEXT_DATA__"
    )

    if script:

        text = (
            script.string
            or script.get_text()
        )

        if text:

            try:

                results.append(
                    json.loads(
                        text
                    )
                )

            except Exception:

                pass

    return results


# ============================================================
# 商品主图
# ============================================================

def extract_product_image(
    raw_html
):

    if not raw_html:

        return ""

    soup = BeautifulSoup(
        raw_html,
        "html.parser"
    )

    # --------------------------------------------------------
    # OpenGraph
    # --------------------------------------------------------

    for prop in [
        "og:image",
        "og:image:url"
    ]:

        tag = soup.find(
            "meta",
            property=prop
        )

        if (
            tag
            and tag.get("content")
        ):

            image = html.unescape(
                tag["content"]
            ).strip()

            if image.startswith(
                "http"
            ):

                return image

    # --------------------------------------------------------
    # Twitter
    # --------------------------------------------------------

    tag = soup.find(
        "meta",
        attrs={
            "name":
                "twitter:image"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        image = html.unescape(
            tag["content"]
        ).strip()

        if image.startswith(
            "http"
        ):

            return image

    # --------------------------------------------------------
    # image_src
    # --------------------------------------------------------

    tag = soup.find(
        "link",
        rel="image_src"
    )

    if (
        tag
        and tag.get("href")
    ):

        image = html.unescape(
            tag["href"]
        ).strip()

        if image.startswith(
            "http"
        ):

            return image

    # --------------------------------------------------------
    # JSON-LD
    # --------------------------------------------------------

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        text = (
            script.string
            or script.get_text()
        )

        if not text:

            continue

        try:

            data = json.loads(
                text
            )

            for obj in recursive_objects(
                data
            ):

                image = obj.get(
                    "image"
                )

                if isinstance(
                    image,
                    str
                ):

                    if image.startswith(
                        "http"
                    ):

                        return image

                if isinstance(
                    image,
                    list
                ):

                    for item in image:

                        if (
                            isinstance(
                                item,
                                str
                            )
                            and item.startswith(
                                "http"
                            )
                        ):

                            return item

        except Exception:

            pass

    # --------------------------------------------------------
    # HTML 中最后兜底找图片
    # --------------------------------------------------------

    for tag in soup.find_all(
        "img"
    ):

        for attr in [
            "src",
            "data-src",
            "data-lazy-src"
        ]:

            value = tag.get(
                attr
            )

            if not value:

                continue

            value = html.unescape(
                value
            ).strip()

            if value.startswith(
                "http"
            ):

                # 避开明显的 logo/icon
                low = value.lower()

                if any(
                    x in low
                    for x in [
                        "logo",
                        "icon",
                        "sprite"
                    ]
                ):

                    continue

                return value

    return ""


# ============================================================
# 去重
# ============================================================

def deduplicate_variants(
    variants
):

    result = []

    seen = set()

    for v in variants:

        key = (
            round(
                float(
                    v.get(
                        "price"
                    )
                    or 0
                ),
                2
            ),
            round(
                float(
                    v.get(
                        "original"
                    )
                    or 0
                ),
                2
            ),
            normalize_name(
                v.get(
                    "color",
                    ""
                )
            ),
            normalize_name(
                v.get(
                    "size",
                    ""
                )
            ),
            v.get(
                "available"
            )
        )

        if key in seen:

            continue

        seen.add(
            key
        )

        result.append(
            v
        )

    return result


# ============================================================
# Markdown 备用价格解析
# ============================================================

def fallback_markdown_variants(
    markdown
):

    if not markdown:

        return []

    prices = []

    # --------------------------------------------------------
    # 识别 $
    # --------------------------------------------------------

    pattern = re.compile(
        r"\$\s?"
        r"(\d{1,4}(?:,\d{3})*"
        r"(?:\.\d{1,2})?)"
    )

    for match in pattern.finditer(
        markdown
    ):

        value = parse_money(
            match.group(1)
        )

        if value is None:

            continue

        if value not in prices:

            prices.append(
                value
            )

    if len(prices) < 2:

        return []

    original = max(
        prices
    )

    variants = []

    for price in sorted(
        prices
    ):

        if price >= original:

            continue

        variants.append({
            "price": price,
            "original": original,
            "color":
                "页面未明确颜色",
            "size":
                "页面未明确尺码",
            "available": None
        })

    return variants


# ============================================================
# 商品标题
# ============================================================

def get_product_title(
    markdown,
    raw_html,
    list_title=""
):

    if (
        list_title
        and len(list_title) > 3
    ):

        return clean_text(
            list_title
        )

    # Markdown H1
    for line in markdown.splitlines():

        line = clean_text(
            line
        )

        if line.startswith(
            "#"
        ):

            title = re.sub(
                r"^#+\s*",
                "",
                line
            )

            if len(title) >= 5:

                return title

    # HTML title
    if raw_html:

        soup = BeautifulSoup(
            raw_html,
            "html.parser"
        )

        if soup.title:

            title = clean_text(
                soup.title.get_text()
            )

            title = re.sub(
                r"\s*\|\s*REI.*$",
                "",
                title,
                flags=re.I
            )

            if len(title) >= 5:

                return title

    return "REI 商品"


# ============================================================
# 商品详情
# ============================================================

def product_detail(
    url,
    brand,
    list_title=""
):

    print()
    print(
        "抓取重点商品:"
    )
    print(url)

    data = firecrawl(
        url,
        formats=[
            "markdown",
            "rawHtml"
        ]
    )

    if not data:

        print(
            "商品抓取失败"
        )

        return None

    result = data.get(
        "data",
        data
    )

    markdown = (
        result.get(
            "markdown",
            ""
        )
        or ""
    )

    raw_html = (
        result.get(
            "rawHtml",
            ""
        )
        or ""
    )

    title = get_product_title(
        markdown,
        raw_html,
        list_title
    )

    # --------------------------------------------------------
    # 商品图片
    # --------------------------------------------------------

    image_url = extract_product_image(
        raw_html
    )

    if image_url:

        print(
            "发现商品图片:",
            image_url[:150]
        )

    else:

        print(
            "没有发现商品图片"
        )

    variants = []

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    json_data_list = (
        extract_json_scripts(
            raw_html
        )
    )

    for json_data in (
        json_data_list
    ):

        variants.extend(
            extract_variants_from_json(
                json_data
            )
        )

    variants = deduplicate_variants(
        variants
    )

    # --------------------------------------------------------
    # Markdown 备用
    # --------------------------------------------------------

    if not variants:

        variants = (
            fallback_markdown_variants(
                markdown
            )
        )

    if not variants:

        print(
            "没有解析到价格"
        )

        return None

    # --------------------------------------------------------
    # 计算折扣
    # --------------------------------------------------------

    sale_variants = []

    for v in variants:

        if not v.get(
            "original"
        ):

            v["original"] = (
                v["price"]
            )

        discount = calculate_discount(
            v["original"],
            v["price"]
        )

        v["discount"] = discount

        if discount > 0:

            sale_variants.append(
                v
            )

    if not sale_variants:

        print(
            "没有发现折扣商品"
        )

        return None

    # --------------------------------------------------------
    # 按价格档位分组
    # --------------------------------------------------------

    grouped = group_variants_by_price(
        sale_variants
    )

    print(
        "发现折扣价格层级:",
        len(grouped)
    )

    for level in grouped:

        print(
            f"  原价 "
            f"{money(level['original'])}"
            f" -> "
            f"现价 "
            f"{money(level['price'])}"
            f" "
            f"({level['discount']}%)"
        )

    return {
        "brand": brand,
        "name": title,
        "url": url,
        "image": image_url,
        "levels": grouped
    }


# ============================================================
# 按价格 + 原价分组
# ============================================================

def group_variants_by_price(
    variants
):

    groups = {}

    for v in variants:

        key = (
            round(
                float(
                    v["price"]
                ),
                2
            ),
            round(
                float(
                    v["original"]
                ),
                2
            )
        )

        if key not in groups:

            groups[key] = {
                "price":
                    v["price"],
                "original":
                    v["original"],
                "discount":
                    v.get(
                        "discount",
                        0
                    ),
                "colors": {}
            }

        color = (
            clean_text(
                v.get(
                    "color"
                )
            )
            or "未标注颜色"
        )

        size = (
            clean_text(
                v.get(
                    "size"
                )
            )
            or "未标注尺码"
        )

        if (
            color
            not in groups[key]["colors"]
        ):

            groups[key]["colors"][
                color
            ] = {
                "sizes": [],
                "available": []
            }

        color_data = (
            groups[key]["colors"][
                color
            ]
        )

        if (
            size
            not in color_data["sizes"]
        ):

            color_data["sizes"].append(
                size
            )

        available = v.get(
            "available"
        )

        if available is not None:

            color_data[
                "available"
            ].append(
                bool(
                    available
                )
            )

    result = list(
        groups.values()
    )

    result.sort(
        key=lambda x: (
            -x["discount"],
            x["price"]
        )
    )

    return result


# ============================================================
# 最低价格
# ============================================================

def lowest_sale_price(
    product
):

    prices = []

    for level in product.get(
        "levels",
        []
    ):

        price = level.get(
            "price"
        )

        if price is not None:

            prices.append(
                float(price)
            )

    if not prices:

        return None

    return min(
        prices
    )


# ============================================================
# 价格签名
# ============================================================

def make_price_signature(
    product
):

    result = []

    for level in product.get(
        "levels",
        []
    ):

        result.append({
            "price":
                round(
                    level["price"],
                    2
                ),
            "original":
                round(
                    level["original"],
                    2
                ),
            "discount":
                level["discount"]
        })

    result.sort(
        key=lambda x: (
            x["price"],
            x["original"]
        )
    )

    return result


# ============================================================
# 是否降价
# ============================================================

def should_notify(
    product,
    history
):

    url = product["url"]

    current_price = (
        lowest_sale_price(
            product
        )
    )

    if current_price is None:

        return False

    old = history.get(
        url
    )

    # --------------------------------------------------------
    # 第一次发现
    # --------------------------------------------------------

    if not old:

        history[url] = {
            "name":
                product["name"],
            "lowest_price":
                current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated":
                int(
                    time.time()
                )
        }

        print(
            "首次记录，"
            "建立价格基准:",
            product["name"]
        )

        return False

    old_price = old.get(
        "lowest_price"
    )

    if old_price is None:

        history[url] = {
            "name":
                product["name"],
            "lowest_price":
                current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated":
                int(
                    time.time()
                )
        }

        return False

    old_price = float(
        old_price
    )

    # --------------------------------------------------------
    # 核心规则：
    # 只有当前最低价 < 历史最低价
    # 才推送
    # --------------------------------------------------------

    if current_price < old_price:

        print(
            f"发现降价: "
            f"{product['name']} "
            f"{old_price} -> "
            f"{current_price}"
        )

        history[url] = {
            "name":
                product["name"],
            "lowest_price":
                current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated":
                int(
                    time.time()
                )
        }

        return True

    # --------------------------------------------------------
    # 持平 / 涨价：
    # 不推送
    # --------------------------------------------------------

    history[url] = {
        "name":
            product["name"],
        "lowest_price":
            current_price,
        "price_signature":
            make_price_signature(
                product
            ),
        "updated":
            int(
                time.time()
            )
    }

    return False


# ============================================================
# Telegram 文本
# ============================================================

def format_product(
    product
):

    lines = []

    # 品牌
    lines.append(
        f"🏔️ {product['brand']}"
    )

    lines.append("")

    for level in product[
        "levels"
    ]:

        price = level[
            "price"
        ]

        original = level[
            "original"
        ]

        discount = level[
            "discount"
        ]

        rmb_price = usd_to_rmb(
            price
        )

        rmb_original = usd_to_rmb(
            original
        )

        # ----------------------------------------------------
        # 折扣等级
        # ----------------------------------------------------

        if discount >= 50:

            icon = "🚨"

        elif discount >= 30:

            icon = "🔥"

        else:

            icon = "🏷️"

        # ----------------------------------------------------
        # 商品名称
        # ----------------------------------------------------

        lines.append(
            f"{icon} "
            f"{discount}% OFF｜"
            f"{product['name']}"
        )

        # ----------------------------------------------------
        # 原价 / 现价
        # ----------------------------------------------------

        lines.append(
            f"🏷️ 原价 "
            f"{money(original)}"
            f"（¥{int(rmb_original)}）"
            f"｜"
            f"💰 现价 "
            f"{money(price)}"
            f"（¥{int(rmb_price)}）"
        )

        lines.append("")

        colors = list(
            level[
                "colors"
            ].keys()
        )

        if colors:

            # ------------------------------------------------
            # 颜色
            # ------------------------------------------------

            lines.append(
                "颜色       "
                + "      ".join(
                    colors
                )
            )

            # ------------------------------------------------
            # 尺码
            # ------------------------------------------------

            size_values = []

            for color in colors:

                info = (
                    level[
                        "colors"
                    ][color]
                )

                sizes = []

                for size in info[
                    "sizes"
                ]:

                    if (
                        size
                        not in sizes
                    ):

                        sizes.append(
                            size
                        )

                size_values.append(
                    " ".join(
                        sizes
                    )
                )

            lines.append(
                "尺码       "
                + "      ".join(
                    size_values
                )
            )

            # ------------------------------------------------
            # 库存
            # ------------------------------------------------

            stock_values = []

            for color in colors:

                info = (
                    level[
                        "colors"
                    ][color]
                )

                states = info.get(
                    "available",
                    []
                )

                if True in states:

                    stock = "有货"

                elif (
                    states
                    and all(
                        x is False
                        for x in states
                    )
                ):

                    stock = "无货"

                else:

                    stock = "未明确"

                stock_values.append(
                    stock
                )

            lines.append(
                "库存       "
                + "      ".join(
                    stock_values
                )
            )

        lines.append("")

        lines.append(
            "━━━━━━━━━━━━"
        )

        lines.append("")

    # --------------------------------------------------------
    # 最后只放直接链接
    # --------------------------------------------------------

    lines.append(
        product["url"]
    )

    return "\n".join(
        lines
    )


# ============================================================
# Telegram 推送
# ============================================================

def telegram_send(
    message,
    image_url=""
):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "Telegram Bot Token "
            "没有读取到"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "Telegram Chat ID "
            "没有读取到"
        )

        return False

    # ========================================================
    # 有图片：先尝试 sendPhoto
    # ========================================================

    if image_url:

        photo_url = (
            "https://api.telegram.org/"
            f"bot{TELEGRAM_BOT_TOKEN}/"
            "sendPhoto"
        )

        # Telegram caption 上限约 1024
        if len(message) <= 1000:

            caption = message

        else:

            # 图片说明只保留前面的完整头部，
            # 完整文字随后再发
            caption = (
                message[:997]
                + "..."
            )

        payload = {
            "chat_id":
                TELEGRAM_CHAT_ID,
            "photo":
                image_url,
            "caption":
                caption
        }

        try:

            response = requests.post(
                photo_url,
                json=payload,
                timeout=30
            )

            print(
                "Telegram 图片:",
                response.status_code
            )

            if response.status_code == 200:

                # 如果完整信息超过 Telegram 图片 caption
                # 则再补发完整文字
                if len(message) > 1000:

                    time.sleep(0.5)

                    return telegram_send_text(
                        message
                    )

                return True

            print(
                response.text[:1000]
            )

        except Exception as e:

            print(
                "Telegram 图片发送异常:",
                e
            )

    # ========================================================
    # 图片失败 -> 普通文字
    # ========================================================

    return telegram_send_text(
        message
    )


def telegram_send_text(
    message
):

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,
        "text":
            message,
        "disable_web_page_preview":
            True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print(
            "Telegram 文字:",
            response.status_code
        )

        if response.status_code != 200:

            print(
                response.text[:1000]
            )

            return False

        return True

    except Exception as e:

        print(
            "Telegram 推送异常:",
            e
        )

        return False


# ============================================================
# 详情页轮换
# ============================================================

def get_detail_batch(
    watch_products,
    history
):

    if not watch_products:

        return []

    state = history.get(
        "__monitor_state__",
        {}
    )

    next_index = int(
        state.get(
            "next_index",
            0
        )
    )

    total = len(
        watch_products
    )

    batch_size = min(
        MAX_DETAIL_PER_RUN,
        total
    )

    selected = []

    for i in range(
        batch_size
    ):

        index = (
            next_index + i
        ) % total

        selected.append(
            watch_products[
                index
            ]
        )

    # 下一次从后面继续
    history[
        "__monitor_state__"
    ] = {
        "next_index":
            (
                next_index
                + batch_size
            ) % total,
        "total":
            total,
        "updated":
            int(
                time.time()
            )
    }

    return selected


# ============================================================
# 主程序
# ============================================================

def main():

    print()
    print(
        "======================================"
    )
    print(
        "REI Outdoor Price Monitor"
    )
    print(
        "图片 + 降价 + 颜色/尺码/库存"
    )
    print(
        "======================================"
    )
    print()

    # --------------------------------------------------------
    # Secrets
    # --------------------------------------------------------

    if not FIRECRAWL_API_KEY:

        print(
            "错误："
            "FIRECRAWL_API_KEY 未读取"
        )

        return

    if not TELEGRAM_BOT_TOKEN:

        print(
            "警告："
            "TELEGRAM_BOT_TOKEN 未读取"
        )

    if not TELEGRAM_CHAT_ID:

        print(
            "警告："
            "TELEGRAM_CHAT_ID 未读取"
        )

    history = load_history()

    all_products = []

    # ========================================================
    # 1. 抓取品牌列表
    # ========================================================

    for brand, url in BRAND_PAGES:

        print()
        print(
            f"抓取列表: {brand}"
        )

        data = firecrawl(
            url,
            formats=[
                "markdown"
            ]
        )

        if not data:

            print(
                "列表抓取失败"
            )

            # 避免列表连续请求过快
            time.sleep(3)

            continue

        result = data.get(
            "data",
            data
        )

        markdown = (
            result.get(
                "markdown",
                ""
            )
            or ""
        )

        products = (
            extract_links_from_markdown(
                markdown,
                brand
            )
        )

        print(
            f"发现商品: "
            f"{len(products)}"
        )

        all_products.extend(
            products
        )

        # 列表页之间也稍微停一下
        time.sleep(3)

    # ========================================================
    # 2. URL 去重
    # ========================================================

    unique = {}

    for product in all_products:

        unique[
            product["url"]
        ] = product

    all_products = list(
        unique.values()
    )

    print()
    print(
        f"总商品链接: "
        f"{len(all_products)}"
    )

    # ========================================================
    # 3. 匹配重点商品
    # ========================================================

    watch_products = []

    for product in all_products:

        combined = normalize_name(
            product.get(
                "title",
                ""
            )
            + " "
            + product.get(
                "url",
                ""
            )
        )

        if is_watch_product(
            combined
        ):

            watch_products.append(
                product
            )

    print(
        f"重点商品: "
        f"{len(watch_products)}"
    )

    # ========================================================
    # 4. 没找到重点商品
    # ========================================================

    if not watch_products:

        print()
        print(
            "警告：当前没有匹配到重点商品。"
        )

        print(
            "以下是抓到的部分 REI 商品："
        )

        for product in (
            all_products[:30]
        ):

            print(
                product.get(
                    "title",
                    ""
                ),
                product[
                    "url"
                ]
            )

        print()

    # ========================================================
    # 5. 本轮轮换选择详情页
    # ========================================================

    detail_products = get_detail_batch(
        watch_products,
        history
    )

    print()
    print(
        f"本轮抓取详情: "
        f"{len(detail_products)}"
    )

    notifications = []

    # ========================================================
    # 6. 抓详情
    # ========================================================

    for index, item in enumerate(
        detail_products,
        start=1
    ):

        print()
        print(
            f"[{index}/"
            f"{len(detail_products)}]"
        )

        product = product_detail(
            item["url"],
            item["brand"],
            item.get(
                "title",
                ""
            )
        )

        if not product:

            # 即使失败也继续下一个
            time.sleep(
                FIRECRAWL_WAIT_SECONDS
            )

            continue

        if should_notify(
            product,
            history
        ):

            notifications.append(
                product
            )

        # ----------------------------------------------------
        # 重点：
        # Firecrawl 每分钟请求数限制
        # ----------------------------------------------------

        if index < len(
            detail_products
        ):

            print(
                f"等待 "
                f"{FIRECRAWL_WAIT_SECONDS} 秒，"
                f"避免 Firecrawl 限流..."
            )

            time.sleep(
                FIRECRAWL_WAIT_SECONDS
            )

    # ========================================================
    # 7. 保存历史
    # ========================================================

    save_history(
        history
    )

    # ========================================================
    # 8. Telegram
    # ========================================================

    if notifications:

        print()
        print(
            f"发现降价商品: "
            f"{len(notifications)}"
        )

        for product in notifications:

            message = format_product(
                product
            )

            print()
            print(
                message
            )
            print()

            telegram_send(
                message,
                product.get(
                    "image",
                    ""
                )
            )

            time.sleep(1)

    else:

        print()
        print(
            "本次没有发现新的降价。"
        )

    print()
    print(
        "======================================"
    )
    print(
        "运行完成"
    )
    print(
        "======================================")


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":

    main()
