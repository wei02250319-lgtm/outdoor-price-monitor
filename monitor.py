import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup

# ============================================================
# REI Outdoor Price Monitor
# 图片 + 降价 + 颜色 + 尺码 + 库存
# ============================================================

FIRECRAWL_API = "https://api.firecrawl.dev/v2/scrape"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()

HISTORY_FILE = "data/prices.json"

REQUEST_TIMEOUT = 90

# Firecrawl 当前限制约 11 次/分钟
# 每轮最多抓 3 个详情页
MAX_DETAIL_PER_RUN = 3

# 两次详情请求之间等待
DETAIL_WAIT_SECONDS = 9

# USD -> RMB
RATES_TO_RMB = {
    "USD": 7.15
}

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
# 基础
# ============================================================

def clean_text(text):
    if text is None:
        return ""

    text = html.unescape(str(text))
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_name(text):
    text = clean_text(text).lower()

    text = text.replace("’", "'")
    text = text.replace("–", "-")
    text = text.replace("—", "-")

    return text


# ============================================================
# History
# ============================================================

def ensure_history_file():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(HISTORY_FILE):
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

            if isinstance(data, dict):
                return data

    except Exception as e:
        print("读取历史失败:", e)

    return {}


def save_history(history):

    ensure_history_file()

    temp_file = HISTORY_FILE + ".tmp"

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

def firecrawl(url, formats=None):

    if formats is None:
        formats = ["markdown"]

    if not FIRECRAWL_API_KEY:
        print("错误：FIRECRAWL_API_KEY 没有读取到")
        return None

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json"
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
            f"Firecrawl: {response.status_code} {url}"
        )

        if response.status_code == 429:

            print("Firecrawl 触发限速，等待后重试一次...")

            time.sleep(12)

            response = requests.post(
                FIRECRAWL_API,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )

            print(
                f"Firecrawl 重试: "
                f"{response.status_code} {url}"
            )

        if response.status_code != 200:

            print(
                response.text[:1000]
            )

            return None

        data = response.json()

        if not data.get("success", True):

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

    text = normalize_name(text)

    for keyword in WATCHLIST:

        keyword = normalize_name(keyword)

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
# URL 标准化
# ============================================================

def normalize_rei_url(url):

    if not url:
        return ""

    url = html.unescape(url)

    url = url.strip()

    if url.startswith("//"):
        url = "https:" + url

    elif url.startswith("/"):
        url = "https://www.rei.com" + url

    url = (
        url
        .split("?")[0]
        .split("#")[0]
    )

    return url.rstrip("/")


# ============================================================
# 从品牌页面提取所有商品链接
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
    # 方法一：Markdown 链接
    # --------------------------------------------------------

    pattern = re.compile(
        r"\[([^\]]+)\]"
        r"\(([^)]+)\)",
        re.I
    )

    for match in pattern.finditer(markdown):

        title = clean_text(
            match.group(1)
        )

        href = normalize_rei_url(
            match.group(2)
        )

        if "rei.com" not in href.lower():
            continue

        if "/product/" not in href.lower():
            continue

        if href in seen:
            continue

        seen.add(href)

        results.append({
            "brand": brand,
            "title": title,
            "url": href
        })

    # --------------------------------------------------------
    # 方法二：直接 URL
    # --------------------------------------------------------

    url_pattern = re.compile(
        r"https?://(?:www\.)?rei\.com/"
        r"product/"
        r"[A-Za-z0-9_\-./]+",
        re.I
    )

    for match in url_pattern.finditer(markdown):

        href = normalize_rei_url(
            match.group(0)
        )

        if href in seen:
            continue

        start = max(
            0,
            match.start() - 800
        )

        end = min(
            len(markdown),
            match.end() + 800
        )

        nearby = markdown[
            start:end
        ]

        title = extract_title_near_url(
            nearby,
            href
        )

        seen.add(href)

        results.append({
            "brand": brand,
            "title": title,
            "url": href
        })

    return results


# ============================================================
# URL 附近标题
# ============================================================

def extract_title_near_url(
    text,
    url
):

    text = clean_text(text)

    # 常见标题格式
    patterns = [
        r"\[([^\]]+)\]",
        r"#{1,6}\s+(.+?)(?:\s+\$|\s+Compared|\s+Save|$)",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.I
        )

        for match in matches:

            title = clean_text(
                match
            )

            if (
                len(title) >= 5
                and len(title) <= 180
                and not title.startswith("http")
            ):
                return title

    return ""


# ============================================================
# 金额
# ============================================================

def parse_money(value):

    if value is None:
        return None

    text = str(value)

    text = text.replace(",", "")
    text = text.replace("$", "")
    text = text.replace("USD", "")
    text = text.replace("US", "")

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

    value = float(value)

    if value.is_integer():
        return f"${int(value)}"

    return f"${value:.2f}"


def usd_to_rmb(value):

    if value is None:
        return None

    return round(
        float(value)
        * RATES_TO_RMB["USD"]
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
        (original - current)
        / original
        * 100
    )


# ============================================================
# REI 页面直接解析价格
# ============================================================

def extract_rei_price_pairs(
    markdown
):

    if not markdown:
        return []

    text = clean_text(markdown)

    results = []

    # --------------------------------------------------------
    # 例如：
    #
    # $399.83 Compared to $650.00
    #
    # Save 38%
    # --------------------------------------------------------

    patterns = [

        re.compile(
            r"\$\s*([\d,]+(?:\.\d{1,2})?)"
            r"\s+Compared\s+to\s+"
            r"\$\s*([\d,]+(?:\.\d{1,2})?)",
            re.I
        ),

        re.compile(
            r"\$\s*([\d,]+(?:\.\d{1,2})?)"
            r".{0,80}?"
            r"Compared\s+to\s+"
            r"\$\s*([\d,]+(?:\.\d{1,2})?)",
            re.I
        ),

        re.compile(
            r"Now\s+\$\s*([\d,]+(?:\.\d{1,2})?)"
            r".{0,100}?"
            r"(?:Was|Regularly)\s+"
            r"\$\s*([\d,]+(?:\.\d{1,2})?)",
            re.I
        ),
    ]

    for pattern in patterns:

        for match in pattern.finditer(text):

            current = parse_money(
                match.group(1)
            )

            original = parse_money(
                match.group(2)
            )

            if (
                current is None
                or original is None
            ):
                continue

            if original <= current:
                continue

            key = (
                round(current, 2),
                round(original, 2)
            )

            if key not in results:
                results.append(key)

    # --------------------------------------------------------
    # 如果没有找到 Compared to
    # 尝试 Save XX%
    # --------------------------------------------------------

    if not results:

        save_pattern = re.compile(
            r"\$\s*([\d,]+(?:\.\d{1,2})?)"
            r".{0,100}?"
            r"Save\s+(\d+)%"
            r".{0,100}?"
            r"\$\s*([\d,]+(?:\.\d{1,2})?)",
            re.I
        )

        for match in save_pattern.finditer(
            text
        ):

            current = parse_money(
                match.group(1)
            )

            discount = int(
                match.group(2)
            )

            original = parse_money(
                match.group(3)
            )

            if (
                current is None
                or original is None
            ):
                continue

            if original <= current:

                original = round(
                    current
                    / (
                        1
                        - discount / 100
                    ),
                    2
                )

            key = (
                round(current, 2),
                round(original, 2)
            )

            if key not in results:
                results.append(key)

    return results


# ============================================================
# JSON 工具
# ============================================================

def recursive_objects(obj):

    if isinstance(obj, dict):

        yield obj

        for value in obj.values():
            yield from recursive_objects(
                value
            )

    elif isinstance(obj, list):

        for value in obj:
            yield from recursive_objects(
                value
            )


def get_value(
    obj,
    keys
):

    if not isinstance(obj, dict):
        return None

    lower_map = {
        str(k).lower(): v
        for k, v in obj.items()
    }

    for key in keys:

        if key.lower() in lower_map:
            return lower_map[
                key.lower()
            ]

    return None


# ============================================================
# JSON 颜色
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
            "displayColor"
        ]
    )

    if value is None:
        return ""

    if isinstance(value, dict):

        value = get_value(
            value,
            [
                "name",
                "label",
                "value",
                "displayName"
            ]
        )

    return clean_text(value)


# ============================================================
# JSON 尺码
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

    if isinstance(value, dict):

        value = get_value(
            value,
            [
                "name",
                "label",
                "value",
                "displayName"
            ]
        )

    return clean_text(value)


# ============================================================
# JSON 库存
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

    if isinstance(value, dict):

        value = get_value(
            value,
            [
                "status",
                "value",
                "label",
                "name"
            ]
        )

    if isinstance(value, bool):
        return value

    if value is None:
        return None

    text = normalize_name(value)

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
# JSON 当前价格
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
            "finalPrice",
            "price",
            "sale"
        ]
    )

    if isinstance(value, dict):

        value = get_value(
            value,
            [
                "amount",
                "value",
                "price"
            ]
        )

    return parse_money(value)


# ============================================================
# JSON 原价
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
            "was_price"
        ]
    )

    if isinstance(value, dict):

        value = get_value(
            value,
            [
                "amount",
                "value",
                "price"
            ]
        )

    return parse_money(value)


# ============================================================
# JSON 脚本
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

    # JSON-LD
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
                json.loads(text)
            )

        except Exception:
            pass

    # NEXT DATA
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
                    json.loads(text)
                )

            except Exception:
                pass

    # 普通 JSON
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

        if text.startswith("{"):

            try:

                data = json.loads(
                    text
                )

                results.append(data)

            except Exception:
                pass

        elif text.startswith("["):

            try:

                data = json.loads(
                    text
                )

                results.append(data)

            except Exception:
                pass

    return results


# ============================================================
# JSON 变体
# ============================================================

def extract_variants_from_json(
    data
):

    variants = []

    for obj in recursive_objects(data):

        if not isinstance(
            obj,
            dict
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

        # 只有明显像商品变体的对象才收
        if not (
            color
            or size
            or available is not None
        ):
            continue

        variants.append({
            "price": current,
            "original": original,
            "color": color or "未标注颜色",
            "size": size or "未标注尺码",
            "available": available
        })

    return variants


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
                    v.get("price") or 0
                ),
                2
            ),
            round(
                float(
                    v.get("original") or 0
                ),
                2
            ),
            normalize_name(
                v.get("color", "")
            ),
            normalize_name(
                v.get("size", "")
            ),
            v.get("available")
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(v)

    return result


# ============================================================
# 图片
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

    # OpenGraph
    meta = soup.find(
        "meta",
        property="og:image"
    )

    if meta:

        image = meta.get(
            "content",
            ""
        )

        if image:
            return normalize_rei_url(
                image
            )

    # Twitter
    meta = soup.find(
        "meta",
        attrs={
            "name": "twitter:image"
        }
    )

    if meta:

        image = meta.get(
            "content",
            ""
        )

        if image:
            return normalize_rei_url(
                image
            )

    # JSON-LD
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

                if not isinstance(
                    obj,
                    dict
                ):
                    continue

                image = get_value(
                    obj,
                    [
                        "image",
                        "imageUrl",
                        "image_url"
                    ]
                )

                if isinstance(
                    image,
                    list
                ):

                    if image:
                        image = image[0]

                if isinstance(
                    image,
                    dict
                ):

                    image = get_value(
                        image,
                        [
                            "url",
                            "src"
                        ]
                    )

                if image:

                    return normalize_rei_url(
                        image
                    )

        except Exception:
            pass

    # REI 常见媒体地址
    match = re.search(
        r'https?://www\.rei\.com/media/product/[A-Za-z0-9_\-]+',
        raw_html,
        re.I
    )

    if match:

        return match.group(0)

    return ""


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

    for line in markdown.splitlines():

        line = clean_text(line)

        if line.startswith("#"):

            title = re.sub(
                r"^#+\s*",
                "",
                line
            )

            if len(title) >= 5:

                return title

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
# 从 Markdown 获取颜色
# ============================================================

def extract_markdown_colors(
    markdown
):

    colors = []

    if not markdown:
        return colors

    # 常见：
    # Color: Black
    # Color Black
    pattern = re.compile(
        r"(?:Color|Colour)\s*[:\-]?\s*"
        r"([A-Za-z][A-Za-z0-9 /&.'\-]{2,80})",
        re.I
    )

    for match in pattern.finditer(
        markdown
    ):

        color = clean_text(
            match.group(1)
        )

        if color:

            if color not in colors:
                colors.append(color)

    return colors


# ============================================================
# Markdown 备用价格
# ============================================================

def fallback_markdown_variants(
    markdown
):

    pairs = extract_rei_price_pairs(
        markdown
    )

    variants = []

    for current, original in pairs:

        discount = calculate_discount(
            original,
            current
        )

        if discount <= 0:
            continue

        variants.append({
            "price": current,
            "original": original,
            "color": "页面未明确颜色",
            "size": "页面未明确尺码",
            "available": None
        })

    return variants


# ============================================================
# 商品详情
# ============================================================

def product_detail(
    url,
    brand,
    list_title=""
):

    print()
    print("抓取重点商品:")
    print(url)

    data = firecrawl(
        url,
        formats=[
            "markdown",
            "rawHtml"
        ]
    )

    if not data:

        print("商品抓取失败")

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

    print(
        "商品名称:",
        title
    )

    # --------------------------------------------------------
    # 图片
    # --------------------------------------------------------

    image = extract_product_image(
        raw_html
    )

    if image:

        print(
            "发现商品图片:",
            image
        )

    else:

        print(
            "没有找到商品图片"
        )

    # --------------------------------------------------------
    # JSON 变体
    # --------------------------------------------------------

    variants = []

    json_data_list = (
        extract_json_scripts(
            raw_html
        )
    )

    for json_data in json_data_list:

        variants.extend(
            extract_variants_from_json(
                json_data
            )
        )

    variants = deduplicate_variants(
        variants
    )

    # --------------------------------------------------------
    # JSON 没抓到价格
    # 使用 REI 页面文字
    # --------------------------------------------------------

    price_pairs = (
        extract_rei_price_pairs(
            markdown
        )
    )

    if price_pairs:

        print(
            "页面识别价格:"
        )

        for current, original in price_pairs:

            discount = calculate_discount(
                original,
                current
            )

            print(
                f"  {money(current)}"
                f" / "
                f"{money(original)}"
                f" / "
                f"{discount}% OFF"
            )

    # --------------------------------------------------------
    # 如果 JSON 没有折扣变体
    # 用页面价格建立价格层级
    # --------------------------------------------------------

    json_sale_variants = []

    for v in variants:

        original = (
            v.get("original")
        )

        current = (
            v.get("price")
        )

        if (
            original
            and current
            and original > current
        ):

            v["discount"] = (
                calculate_discount(
                    original,
                    current
                )
            )

            json_sale_variants.append(
                v
            )

    # --------------------------------------------------------
    # 如果页面价格能识别
    # 优先补充价格
    # --------------------------------------------------------

    if price_pairs:

        for current, original in price_pairs:

            exists = False

            for v in json_sale_variants:

                if (
                    abs(
                        float(
                            v["price"]
                        )
                        - current
                    ) < 0.01
                    and
                    abs(
                        float(
                            v["original"]
                        )
                        - original
                    ) < 0.01
                ):

                    exists = True
                    break

            if not exists:

                json_sale_variants.append({
                    "price": current,
                    "original": original,
                    "color": "页面未明确颜色",
                    "size": "页面未明确尺码",
                    "available": None,
                    "discount":
                        calculate_discount(
                            original,
                            current
                        )
                })

    # --------------------------------------------------------
    # 最后备用
    # --------------------------------------------------------

    if not json_sale_variants:

        json_sale_variants = (
            fallback_markdown_variants(
                markdown
            )
        )

        for v in json_sale_variants:

            v["discount"] = (
                calculate_discount(
                    v["original"],
                    v["price"]
                )
            )

    if not json_sale_variants:

        print(
            "没有发现折扣商品"
        )

        return None

    # --------------------------------------------------------
    # 过滤真正折扣
    # --------------------------------------------------------

    sale_variants = []

    for v in json_sale_variants:

        if (
            v["original"]
            > v["price"]
        ):

            v["discount"] = (
                calculate_discount(
                    v["original"],
                    v["price"]
                )
            )

            sale_variants.append(v)

    if not sale_variants:

        print(
            "没有发现折扣商品"
        )

        return None

    # --------------------------------------------------------
    # 分组
    # --------------------------------------------------------

    grouped = group_variants_by_price(
        sale_variants
    )

    print(
        f"发现折扣价格层级: "
        f"{len(grouped)}"
    )

    for level in grouped:

        print(
            f"  原价 {money(level['original'])}"
            f" -> "
            f"现价 {money(level['price'])}"
            f" "
            f"({level['discount']}%)"
        )

    return {
        "brand": brand,
        "name": title,
        "url": url,
        "image": image,
        "levels": grouped
    }


# ============================================================
# 分组
# ============================================================

def group_variants_by_price(
    variants
):

    groups = {}

    for v in variants:

        key = (
            round(
                float(v["price"]),
                2
            ),
            round(
                float(v["original"]),
                2
            )
        )

        if key not in groups:

            groups[key] = {
                "price": v["price"],
                "original": v["original"],
                "discount": v.get(
                    "discount",
                    0
                ),
                "colors": {}
            }

        color = (
            clean_text(
                v.get("color")
            )
            or "未标注颜色"
        )

        size = (
            clean_text(
                v.get("size")
            )
            or "未标注尺码"
        )

        if color not in groups[
            key
        ]["colors"]:

            groups[key]["colors"][
                color
            ] = {
                "sizes": [],
                "available": []
            }

        color_data = (
            groups[key]["colors"][color]
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
                bool(available)
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

    return min(prices)


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
            "price": round(
                level["price"],
                2
            ),
            "original": round(
                level["original"],
                2
            ),
            "discount": level[
                "discount"
            ]
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

    old = history.get(url)

    # --------------------------------------------------------
    # 第一次发现
    # --------------------------------------------------------

    if not old:

        history[url] = {
            "name": product["name"],
            "lowest_price": current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated": int(
                time.time()
            )
        }

        print(
            "首次记录，建立价格基准"
        )

        return False

    old_price = old.get(
        "lowest_price"
    )

    if old_price is None:

        history[url] = {
            "name": product["name"],
            "lowest_price": current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated": int(
                time.time()
            )
        }

        return False

    old_price = float(
        old_price
    )

    # --------------------------------------------------------
    # 只有下降才推送
    # --------------------------------------------------------

    if current_price < old_price:

        print(
            f"发现降价: "
            f"{product['name']} "
            f"{money(old_price)}"
            f" -> "
            f"{money(current_price)}"
        )

        history[url] = {
            "name": product["name"],
            "lowest_price": current_price,
            "price_signature":
                make_price_signature(
                    product
                ),
            "updated": int(
                time.time()
            )
        }

        return True

    # --------------------------------------------------------
    # 持平/涨价不推送
    # --------------------------------------------------------

    history[url] = {
        "name": product["name"],
        "lowest_price": current_price,
        "price_signature":
            make_price_signature(
                product
            ),
        "updated": int(
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

    for level in product["levels"]:

        price = level["price"]
        original = level["original"]
        discount = level["discount"]

        rmb_price = usd_to_rmb(
            price
        )

        rmb_original = usd_to_rmb(
            original
        )

        if discount >= 50:

            icon = "🚨"

        elif discount >= 30:

            icon = "🔥"

        else:

            icon = "🏷️"

        # ----------------------------------------------------
        # 商品名 + 折扣
        # ----------------------------------------------------

        lines.append(
            f"{icon} "
            f"{discount}% OFF｜"
            f"{product['name']}"
        )

        lines.append(
            f"🏷️ 原价 {money(original)}"
            f"（¥{int(rmb_original)}）"
            f"｜"
            f"💰 现价 {money(price)}"
            f"（¥{int(rmb_price)}）"
        )

        lines.append("")

        colors = list(
            level["colors"].keys()
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
                    level["colors"][color]
                )

                sizes = []

                for size in info[
                    "sizes"
                ]:

                    if size not in sizes:
                        sizes.append(size)

                size_values.append(
                    " ".join(sizes)
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
                    level["colors"][color]
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

    # 商品链接单独放最后
    lines.append(
        product["url"]
    )

    return "\n".join(lines)


# ============================================================
# Telegram 文本发送
# ============================================================

def telegram_send_message(
    message
):

    if not TELEGRAM_BOT_TOKEN:
        print(
            "Telegram Bot Token 没有读取到"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "Telegram Chat ID 没有读取到"
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print(
            "Telegram 文本:",
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
# Telegram 图片发送
# ============================================================

def telegram_send_photo(
    image_url,
    caption
):

    if not TELEGRAM_BOT_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    if not image_url:
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    )

    # Telegram caption 最长 1024 字符
    short_caption = caption

    if len(short_caption) > 1024:

        short_caption = (
            short_caption[:1000]
            + "..."
        )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "photo": image_url,
        "caption": short_caption
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=40
        )

        print(
            "Telegram 图片:",
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
            "Telegram 图片推送异常:",
            e
        )

        return False


# ============================================================
# Telegram 智能发送
# ============================================================

def telegram_send_product(
    product
):

    message = format_product(
        product
    )

    image = product.get(
        "image",
        ""
    )

    # --------------------------------------------------------
    # 有图片：
    # 先尝试图片
    # --------------------------------------------------------

    if image:

        success = telegram_send_photo(
            image,
            message
        )

        if success:

            # 如果完整内容超过 Telegram 图片 caption 限制，
            # 再补发完整文字。
            if len(message) > 1024:

                time.sleep(0.5)

                telegram_send_message(
                    message
                )

            return True

    # --------------------------------------------------------
    # 图片失败，自动退回纯文字
    # --------------------------------------------------------

    return telegram_send_message(
        message
    )


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
            "错误：FIRECRAWL_API_KEY 未读取"
        )

        return

    if not TELEGRAM_BOT_TOKEN:

        print(
            "警告：TELEGRAM_BOT_TOKEN 未读取"
        )

    if not TELEGRAM_CHAT_ID:

        print(
            "警告：TELEGRAM_CHAT_ID 未读取"
        )

    history = load_history()

    all_products = []

    # --------------------------------------------------------
    # 品牌列表
    # --------------------------------------------------------

    for brand, url in BRAND_PAGES:

        print()
        print(
            f"抓取列表: {brand}"
        )

        data = firecrawl(
            url,
            formats=["markdown"]
        )

        if not data:

            print(
                "列表抓取失败"
            )

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
            f"发现商品: {len(products)}"
        )

        all_products.extend(
            products
        )

        # 品牌列表之间稍微停一下
        time.sleep(2)

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 匹配重点商品
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 当前轮只抓 3 个
    # --------------------------------------------------------

    detail_products = (
        watch_products[
            :MAX_DETAIL_PER_RUN
        ]
    )

    print()
    print(
        f"本轮抓取详情: "
        f"{len(detail_products)}"
    )

    # --------------------------------------------------------
    # 如果没有重点商品
    # --------------------------------------------------------

    if not watch_products:

        print()
        print(
            "警告：没有匹配到重点商品"
        )

        for product in all_products[:30]:

            print(
                product.get(
                    "title",
                    ""
                ),
                product["url"]
            )

    notifications = []

    # --------------------------------------------------------
    # 详情
    # --------------------------------------------------------

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

        if product:

            if should_notify(
                product,
                history
            ):

                notifications.append(
                    product
                )

        # 避免 Firecrawl 429
        if index < len(detail_products):

            print(
                f"等待 "
                f"{DETAIL_WAIT_SECONDS} 秒..."
            )

            time.sleep(
                DETAIL_WAIT_SECONDS
            )

    # --------------------------------------------------------
    # 保存历史
    # --------------------------------------------------------

    save_history(
        history
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

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
            print(message)
            print()

            telegram_send_product(
                product
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


if __name__ == "__main__":
    main()
