import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# 配置
# ============================================================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

HISTORY_FILE = Path("data/prices.json")

# 每轮最多抓 3 个详情页
MAX_DETAIL_PER_RUN = 3

# Firecrawl 限速保护
DETAIL_WAIT_SECONDS = 9

# 美元人民币汇率
USD_CNY = 7.15

# 只有折扣 >= 20% 才进入提醒
ALERT_DISCOUNT_MIN = 20


# ============================================================
# REI 品牌列表
# ============================================================

BRAND_LIST_URLS = {
    "Arc'teryx":
        "https://www.rei.com/b/arcteryx/c/all",

    "Patagonia":
        "https://www.rei.com/b/patagonia/c/all",

    "The North Face":
        "https://www.rei.com/b/the-north-face/c/all",
}


# ============================================================
# 重点商品
#
# 这里采用“严格匹配”
# 不再把 Beta SL、Atom Vest 等无关商品混进来
# ============================================================

WATCHLIST = [
    "Arc'teryx Gamma MX",
    "Arc'teryx Gamma Jacket",
    "Arc'teryx Gamma Pants",

    "Patagonia R2 TechFace Jacket",
    "Patagonia R2 TechFace Hoody",
    "Patagonia C1",
    "Patagonia Capilene Cool Daily Graphic Hoody",

    "Arc'teryx Atom Insulated Jacket",
    "Arc'teryx Atom Insulated Hoody",
]


# ============================================================
# Session
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 16; Mobile) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json",
})


# ============================================================
# 历史价格
# ============================================================

def load_history():
    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    if not HISTORY_FILE.exists():
        return {}

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
        print(
            "读取历史价格失败:",
            e
        )

    return {}


def save_history(history):
    HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = HISTORY_FILE.with_suffix(
        ".tmp"
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

    temp_file.replace(
        HISTORY_FILE
    )


# ============================================================
# Firecrawl
# ============================================================

def firecrawl_scrape(
    url,
    formats
):
    if not FIRECRAWL_API_KEY:
        print(
            "错误：FIRECRAWL_API_KEY 未配置"
        )
        return {}

    headers = {
        "Authorization":
            f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type":
            "application/json",
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
            timeout=120
        )

        print(
            "Firecrawl:",
            response.status_code,
            url
        )

        # ----------------------------------------------------
        # 429 限速
        # ----------------------------------------------------

        if response.status_code == 429:

            print(
                "Firecrawl 限速，等待 15 秒后重试..."
            )

            time.sleep(15)

            response = SESSION.post(
                FIRECRAWL_URL,
                headers=headers,
                json=payload,
                timeout=120
            )

            print(
                "Firecrawl 重试:",
                response.status_code,
                url
            )

        if response.status_code != 200:
            print(
                response.text[:1000]
            )
            return {}

        result = response.json()

        if not result.get(
            "success",
            True
        ):
            print(
                "Firecrawl 返回失败:",
                result
            )
            return {}

        return result.get(
            "data",
            {}
        )

    except Exception as e:

        print(
            "Firecrawl 异常:",
            e
        )

        return {}


# ============================================================
# 文本
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = str(text)

    text = (
        text
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\r", " ")
        .replace("\t", " ")
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_title(title):
    title = clean_text(
        title
    )

    # Markdown 链接残留处理
    title = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        title
    )

    title = re.sub(
        r"\s+",
        " ",
        title
    )

    return title.strip()


# ============================================================
# URL
# ============================================================

def normalize_url(url):

    if not url:
        return ""

    url = url.strip()

    if url.startswith("//"):
        url = "https:" + url

    elif url.startswith("/"):
        url = urljoin(
            "https://www.rei.com",
            url
        )

    if not url.startswith(
        "http"
    ):
        return ""

    url = url.split("?")[0]

    return url.rstrip("/")


# ============================================================
# 商品链接
# ============================================================

def extract_product_links(
    data,
    brand
):
    markdown = data.get(
        "markdown",
        ""
    ) or ""

    raw_html = data.get(
        "rawHtml",
        ""
    ) or ""

    links = {}

    # --------------------------------------------------------
    # Markdown
    # --------------------------------------------------------

    patterns = [
        r"\]\((https?://www\.rei\.com/product/\d+/[^)\s]+)",
        r"\]\((/product/\d+/[^)\s]+)",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            markdown,
            re.I
        ):

            url = normalize_url(
                match.group(1)
            )

            if "/product/" in url:

                links[url] = {
                    "brand": brand,
                    "url": url,
                }

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    html_pattern = re.compile(
        r"https?://www\.rei\.com/product/\d+/[A-Za-z0-9_\-]+"
        r"|"
        r"/product/\d+/[A-Za-z0-9_\-]+",
        re.I
    )

    for match in html_pattern.finditer(
        raw_html
    ):

        url = normalize_url(
            match.group(0)
        )

        if "/product/" in url:

            links[url] = {
                "brand": brand,
                "url": url,
            }

    # --------------------------------------------------------
    # BeautifulSoup
    # --------------------------------------------------------

    if raw_html:

        try:

            soup = BeautifulSoup(
                raw_html,
                "lxml"
            )

            for a in soup.find_all(
                "a",
                href=True
            ):

                url = normalize_url(
                    a.get("href")
                )

                if "/product/" in url:

                    links[url] = {
                        "brand": brand,
                        "url": url,
                    }

        except Exception:
            pass

    return list(
        links.values()
    )


# ============================================================
# 商品 slug
# ============================================================

def get_slug(url):
    return (
        url
        .rstrip("/")
        .split("/")[-1]
        .lower()
    )


# ============================================================
# 严格重点商品匹配
# ============================================================

def match_watch_product(
    url
):
    slug = get_slug(
        url
    )

    # --------------------------------------------------------
    # Arc'teryx
    # --------------------------------------------------------

    if (
        slug.startswith(
            "arcteryx-"
        )
    ):

        # Gamma MX
        if (
            "gamma-mx" in slug
            and (
                "hoody" in slug
                or "hood" in slug
                or "jacket" in slug
            )
        ):
            return True

        # Gamma Jacket
        if (
            "gamma-jacket" in slug
            and "gamma-mx" not in slug
        ):
            return True

        # Gamma Pants
        if (
            "gamma-pants" in slug
            or "gamma-pant" in slug
        ):
            return True

        # Atom Insulated Jacket
        if (
            "atom-insulated-jacket"
            in slug
        ):
            return True

        # Atom Insulated Hoody
        if (
            "atom-insulated-hoody"
            in slug
        ):
            return True

        # 注意：
        # Atom Insulated Vest 不匹配
        # Beta SL 不匹配
        # Beta Jacket 不匹配
        # Beta AR 不匹配

        return False

    # --------------------------------------------------------
    # Patagonia
    # --------------------------------------------------------

    if (
        slug.startswith(
            "patagonia-"
        )
    ):

        # R2 TechFace Jacket
        if (
            "r2-techface"
            in slug
            and "jacket" in slug
        ):
            return True

        # R2 TechFace Hoody
        if (
            "r2-techface"
            in slug
            and (
                "hoody" in slug
                or "hood" in slug
            )
        ):
            return True

        # Capilene Cool Daily Graphic Hoody
        if (
            "capilene" in slug
            and "cool" in slug
            and "daily" in slug
            and "graphic" in slug
            and (
                "hoody" in slug
                or "hood" in slug
            )
        ):
            return True

        # C1
        #
        # 这里保留 C1 关键词，
        # 方便后面你提供准确商品链接后进一步锁死
        if (
            re.search(
                r"(^|-)c1(-|$)",
                slug
            )
        ):
            return True

        return False

    return False


# ============================================================
# 美元
# ============================================================

def money(value):
    if value is None:
        return None

    try:
        return float(
            str(value)
            .replace(
                ",",
                ""
            )
            .replace(
                "$",
                ""
            )
            .strip()
        )

    except Exception:
        return None


def usd_to_cny(value):
    if value is None:
        return None

    return round(
        value * USD_CNY,
        2
    )


def calc_discount(
    current,
    original
):
    if (
        current is None
        or original is None
        or original <= 0
        or current >= original
    ):
        return 0

    return round(
        (
            1
            - current / original
        )
        * 100
    )


# ============================================================
# 价格
# ============================================================

def extract_price_tiers(
    markdown
):
    text = clean_text(
        markdown
    )

    tiers = []

    # --------------------------------------------------------
    # REI：
    #
    # $199.83 Compared to $300.00
    # Save 33%
    # --------------------------------------------------------

    pattern = re.compile(
        r"\$([\d,]+(?:\.\d{1,2})?)"
        r"\s*"
        r"(?:Compared\s+to|compare\s+to)"
        r"\s*"
        r"\$([\d,]+(?:\.\d{1,2})?)"
        r"(?:.*?)?"
        r"(?:Save\s*(\d+)%|(\d+)%\s*OFF)?",
        re.I
    )

    for match in pattern.finditer(
        text
    ):

        current = money(
            match.group(1)
        )

        original = money(
            match.group(2)
        )

        discount_value = (
            match.group(3)
            or match.group(4)
        )

        if discount_value:

            discount = int(
                discount_value
            )

        else:

            discount = calc_discount(
                current,
                original
            )

        if (
            current is not None
            and original is not None
            and current < original
        ):

            tiers.append({
                "current":
                    current,
                "original":
                    original,
                "discount":
                    discount,
            })

    # --------------------------------------------------------
    # 备用：
    #
    # $199.83 / $300
    # --------------------------------------------------------

    if not tiers:

        pattern = re.compile(
            r"\$([\d,]+(?:\.\d{1,2})?)"
            r"\s*/\s*"
            r"\$([\d,]+(?:\.\d{1,2})?)"
            r"(?:.*?(\d+)%\s*OFF)?",
            re.I
        )

        for match in pattern.finditer(
            text
        ):

            current = money(
                match.group(1)
            )

            original = money(
                match.group(2)
            )

            discount = (
                int(match.group(3))
                if match.group(3)
                else calc_discount(
                    current,
                    original
                )
            )

            if (
                current is not None
                and original is not None
                and current < original
            ):

                tiers.append({
                    "current":
                        current,
                    "original":
                        original,
                    "discount":
                        discount,
                })

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

    unique = {}

    for tier in tiers:

        key = (
            tier["current"],
            tier["original"]
        )

        unique[key] = tier

    result = list(
        unique.values()
    )

    result.sort(
        key=lambda x: (
            -x["discount"],
            x["current"]
        )
    )

    return result


# ============================================================
# 商品图片
# ============================================================

def extract_image(
    data
):
    raw_html = data.get(
        "rawHtml",
        ""
    ) or ""

    markdown = data.get(
        "markdown",
        ""
    ) or ""

    if raw_html:

        try:

            soup = BeautifulSoup(
                raw_html,
                "lxml"
            )

            for selector in [
                'meta[property="og:image"]',
                'meta[name="twitter:image"]',
            ]:

                tag = soup.select_one(
                    selector
                )

                if tag:

                    image = (
                        tag.get("content")
                        or ""
                    )

                    if image.startswith(
                        "http"
                    ):
                        return image

        except Exception:
            pass

    # REI 图片
    match = re.search(
        r"https://www\.rei\.com/media/product/\d+",
        raw_html
    )

    if match:
        return match.group(0)

    # Markdown
    match = re.search(
        r"!\[[^\]]*\]\((https?://[^)]+)\)",
        markdown
    )

    if match:
        return match.group(1)

    return ""


# ============================================================
# JSON 数据
# ============================================================

def walk_json(
    obj,
    result
):
    if isinstance(
        obj,
        dict
    ):

        result.append(
            obj
        )

        for value in obj.values():

            walk_json(
                value,
                result
            )

    elif isinstance(
        obj,
        list
    ):

        for value in obj:

            walk_json(
                value,
                result
            )


def extract_json_objects(
    raw_html
):
    result = []

    if not raw_html:
        return result

    try:

        soup = BeautifulSoup(
            raw_html,
            "lxml"
        )

        for script in soup.find_all(
            "script"
        ):

            text = (
                script.string
                or script.get_text()
                or ""
            ).strip()

            if not text:
                continue

            script_type = str(
                script.get(
                    "type",
                    ""
                )
            ).lower()

            script_id = str(
                script.get(
                    "id",
                    ""
                )
            ).lower()

            # JSON-LD
            if (
                script_type
                == "application/ld+json"
            ):

                try:

                    obj = json.loads(
                        text
                    )

                    walk_json(
                        obj,
                        result
                    )

                except Exception:
                    pass

            # Next data
            elif (
                "__next_data__"
                in script_id
            ):

                try:

                    obj = json.loads(
                        text
                    )

                    walk_json(
                        obj,
                        result
                    )

                except Exception:
                    pass

    except Exception:
        pass

    return result


# ============================================================
# 变体
# ============================================================

def extract_variants(
    raw_html
):
    objects = extract_json_objects(
        raw_html
    )

    variants = []

    for obj in objects:

        if not isinstance(
            obj,
            dict
        ):
            continue

        # ----------------------------------------------------
        # 当前价格
        # ----------------------------------------------------

        current = None

        for key in [
            "salePrice",
            "sale_price",
            "currentPrice",
            "current_price",
            "price",
        ]:

            if key in obj:

                value = money(
                    obj.get(key)
                )

                if value is not None:

                    current = value
                    break

        # ----------------------------------------------------
        # 原价
        # ----------------------------------------------------

        original = None

        for key in [
            "originalPrice",
            "original_price",
            "compareAtPrice",
            "compare_at_price",
            "regularPrice",
            "regular_price",
        ]:

            if key in obj:

                value = money(
                    obj.get(key)
                )

                if value is not None:

                    original = value
                    break

        if (
            current is None
            or original is None
            or current >= original
        ):
            continue

        # ----------------------------------------------------
        # 颜色
        # ----------------------------------------------------

        color = ""

        for key in [
            "color",
            "colour",
            "colorName",
            "color_name",
        ]:

            if key not in obj:
                continue

            value = obj.get(
                key
            )

            if isinstance(
                value,
                str
            ):

                color = clean_text(
                    value
                )

            elif isinstance(
                value,
                dict
            ):

                color = clean_text(
                    value.get(
                        "name",
                        ""
                    )
                )

            if color:
                break

        # ----------------------------------------------------
        # 尺码
        # ----------------------------------------------------

        size = ""

        for key in [
            "size",
            "sizeName",
            "size_name",
        ]:

            if key not in obj:
                continue

            value = obj.get(
                key
            )

            if isinstance(
                value,
                str
            ):

                size = clean_text(
                    value
                )

            elif isinstance(
                value,
                dict
            ):

                size = clean_text(
                    value.get(
                        "name",
                        ""
                    )
                )

            if size:
                break

        # ----------------------------------------------------
        # 库存
        # ----------------------------------------------------

        available = None

        for key in [
            "available",
            "availability",
            "inStock",
            "in_stock",
        ]:

            if key not in obj:
                continue

            value = obj.get(
                key
            )

            if isinstance(
                value,
                bool
            ):

                available = value

            elif isinstance(
                value,
                str
            ):

                lower = value.lower()

                if (
                    "instock" in lower
                    or "in stock" in lower
                    or "available" in lower
                ):
                    available = True

                elif (
                    "outofstock" in lower
                    or "out of stock" in lower
                    or "soldout" in lower
                    or "sold out" in lower
                ):
                    available = False

            break

        variants.append({
            "current":
                current,

            "original":
                original,

            "discount":
                calc_discount(
                    current,
                    original
                ),

            "color":
                color,

            "size":
                size,

            "available":
                available,
        })

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

    unique = {}

    for item in variants:

        key = (
            item["current"],
            item["original"],
            item["color"],
            item["size"],
        )

        unique[key] = item

    return list(
        unique.values()
    )


# ============================================================
# 变体价格层级
# ============================================================

def build_variant_tiers(
    variants
):
    if not variants:
        return []

    groups = {}

    for item in variants:

        key = (
            item["current"],
            item["original"]
        )

        if key not in groups:

            groups[key] = {
                "current":
                    item["current"],

                "original":
                    item["original"],

                "discount":
                    item["discount"],

                "colors": {},
            }

        color = (
            item["color"]
            or "颜色未明确"
        )

        if color not in groups[
            key
        ]["colors"]:

            groups[
                key
            ]["colors"][color] = {
                "sizes": [],
                "available": [],
            }

        if item["size"]:

            if (
                item["size"]
                not in groups[
                    key
                ]["colors"][color]["sizes"]
            ):

                groups[
                    key
                ]["colors"][color]["sizes"].append(
                    item["size"]
                )

        if (
            item["available"]
            is not None
        ):

            groups[
                key
            ]["colors"][color]["available"].append(
                item["available"]
            )

    result = list(
        groups.values()
    )

    result.sort(
        key=lambda x: (
            -x["discount"],
            x["current"]
        )
    )

    return result


# ============================================================
# 商品详情
# ============================================================

def scrape_product(
    item
):
    url = item["url"]

    data = firecrawl_scrape(
        url,
        [
            "markdown",
            "rawHtml",
        ]
    )

    if not data:
        return None

    markdown = data.get(
        "markdown",
        ""
    ) or ""

    raw_html = data.get(
        "rawHtml",
        ""
    ) or ""

    # --------------------------------------------------------
    # 商品名称
    # --------------------------------------------------------

    title = ""

    match = re.search(
        r"^#\s+(.+)$",
        markdown,
        re.MULTILINE
    )

    if match:

        title = clean_title(
            match.group(1)
        )

    if not title:

        slug = get_slug(
            url
        )

        title = slug.replace(
            "-",
            " "
        ).title()

    # --------------------------------------------------------
    # 图片
    # --------------------------------------------------------

    image = extract_image(
        data
    )

    # --------------------------------------------------------
    # 页面价格
    # --------------------------------------------------------

    page_tiers = extract_price_tiers(
        markdown
    )

    # --------------------------------------------------------
    # 真实变体
    # --------------------------------------------------------

    variants = extract_variants(
        raw_html
    )

    variant_tiers = build_variant_tiers(
        variants
    )

    # --------------------------------------------------------
    # 优先使用真实变体
    # --------------------------------------------------------

    if variant_tiers:

        tiers = variant_tiers

    else:

        # 页面只告诉我们价格，
        # 没有明确告诉我们颜色对应关系
        #
        # 所以不能乱分配颜色
        tiers = []

        for tier in page_tiers:

            tiers.append({
                "current":
                    tier["current"],

                "original":
                    tier["original"],

                "discount":
                    tier["discount"],

                "colors": {
                    "颜色/尺码页面未明确": {
                        "sizes": [],
                        "available": [],
                    }
                },
            })

    # --------------------------------------------------------
    # 去重
    # --------------------------------------------------------

    unique = {}

    for tier in tiers:

        key = (
            tier["current"],
            tier["original"]
        )

        unique[key] = tier

    tiers = list(
        unique.values()
    )

    tiers.sort(
        key=lambda x: (
            -x["discount"],
            x["current"]
        )
    )

    if not tiers:

        print(
            "没有发现折扣商品"
        )

        return {
            "url":
                url,

            "title":
                title,

            "image":
                image,

            "tiers":
                [],
        }

    print(
        "商品名称:",
        title
    )

    if image:

        print(
            "发现商品图片:",
            image
        )

    print(
        "发现折扣价格层级:",
        len(tiers)
    )

    for tier in tiers:

        print(
            "  原价 "
            f"${tier['original']:.2f}"
            " -> 现价 "
            f"${tier['current']:.2f}"
            f" ({tier['discount']}%)"
        )

    return {
        "url":
            url,

        "title":
            title,

        "image":
            image,

        "tiers":
            tiers,
    }


# ============================================================
# 最低价格
# ============================================================

def get_lowest_price(
    product
):
    prices = []

    for tier in product.get(
        "tiers",
        []
    ):

        value = tier.get(
            "current"
        )

        if value is not None:
            prices.append(
                value
            )

    if not prices:
        return None

    return min(
        prices
    )


# ============================================================
# 最佳提醒价格
# ============================================================

def get_alert_tier(
    product
):
    tiers = []

    for tier in product.get(
        "tiers",
        []
    ):

        if (
            tier.get(
                "discount",
                0
            )
            >= ALERT_DISCOUNT_MIN
        ):

            tiers.append(
                tier
            )

    if not tiers:
        return None

    tiers.sort(
        key=lambda x: (
            x["current"],
            -x["discount"]
        )
    )

    return tiers[0]


# ============================================================
# 颜色/尺码/库存
# ============================================================

def format_variant_table(
    tier
):
    colors = tier.get(
        "colors",
        {}
    )

    if not colors:
        return ""

    color_names = list(
        colors.keys()
    )

    # --------------------------------------------------------
    # 如果只是页面价格，没有真实颜色映射
    # --------------------------------------------------------

    if (
        len(color_names) == 1
        and color_names[0]
        == "颜色/尺码页面未明确"
    ):

        return (
            "颜色/尺码/库存："
            "页面未明确"
        )

    lines = []

    # --------------------------------------------------------
    # 颜色
    # --------------------------------------------------------

    lines.append(
        "颜色       "
        + "      ".join(
            color_names
        )
    )

    # --------------------------------------------------------
    # 尺码
    # --------------------------------------------------------

    size_values = []

    for color in color_names:

        sizes = colors[
            color
        ].get(
            "sizes",
            []
        )

        if sizes:

            size_values.append(
                " ".join(
                    sizes
                )
            )

        else:

            size_values.append(
                "未明确"
            )

    lines.append(
        "尺码       "
        + "      ".join(
            size_values
        )
    )

    # --------------------------------------------------------
    # 库存
    # --------------------------------------------------------

    stock_values = []

    for color in color_names:

        available = colors[
            color
        ].get(
            "available",
            []
        )

        if not available:

            stock_values.append(
                "未明确"
            )

        elif any(
            available
        ):

            stock_values.append(
                "有货"
            )

        else:

            stock_values.append(
                "无货"
            )

    lines.append(
        "库存       "
        + "      ".join(
            stock_values
        )
    )

    return "\n".join(
        lines
    )


# ============================================================
# Telegram
# ============================================================

def make_message(
    product
):
    title = product.get(
        "title",
        "未知商品"
    )

    url = product.get(
        "url",
        ""
    )

    tiers = [
        tier
        for tier in product.get(
            "tiers",
            []
        )
        if tier.get(
            "discount",
            0
        ) >= ALERT_DISCOUNT_MIN
    ]

    if not tiers:
        return ""

    blocks = []

    for tier in tiers:

        discount = tier[
            "discount"
        ]

        original = tier[
            "original"
        ]

        current = tier[
            "current"
        ]

        if discount >= 50:

            icon = "🔥🔥"

        elif discount >= 30:

            icon = "🔥"

        else:

            icon = "🏷️"

        block = []

        # 产品名和折扣在最上面
        block.append(
            f"{icon} "
            f"{discount}% OFF｜"
            f"{title}"
        )

        # 原价 / 现价
        block.append(
            "🏷️ 原价 "
            f"${original:.2f}"
            f"（¥{usd_to_cny(original):.0f}）"
            "｜💰 现价 "
            f"${current:.2f}"
            f"（¥{usd_to_cny(current):.0f}）"
        )

        variant_text = (
            format_variant_table(
                tier
            )
        )

        if variant_text:

            block.append(
                variant_text
            )

        # 最后只放直接商品链接
        block.append(
            url
        )

        blocks.append(
            "\n".join(
                block
            )
        )

    return (
        "\n\n"
        .join(
            blocks
        )
    )


def telegram_send_message(
    text
):
    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print(
            "Telegram 未配置"
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            text,

        "disable_web_page_preview":
            False,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=30
        )

        print(
            "Telegram:",
            response.status_code
        )

        return (
            response.status_code
            == 200
        )

    except Exception as e:

        print(
            "Telegram 异常:",
            e
        )

        return False


def telegram_send_photo(
    image,
    caption
):
    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendPhoto"
    )

    payload = {
        "chat_id":
            TELEGRAM_CHAT_ID,

        "photo":
            image,

        "caption":
            caption,
    }

    try:

        response = SESSION.post(
            url,
            data=payload,
            timeout=60
        )

        print(
            "Telegram 图片:",
            response.status_code
        )

        if response.status_code == 200:
            return True

        print(
            response.text[:500]
        )

    except Exception as e:

        print(
            "Telegram 图片异常:",
            e
        )

    return False


# ============================================================
# 判断是否降价
# ============================================================

def should_notify(
    old_record,
    product
):
    current_price = get_lowest_price(
        product
    )

    if current_price is None:
        return False

    # --------------------------------------------------------
    # 第一次发现
    # --------------------------------------------------------

    if not old_record:

        print(
            "首次发现，建立基线，不推送。"
        )

        return False

    old_price = old_record.get(
        "lowest_price"
    )

    if old_price is None:

        return False

    # --------------------------------------------------------
    # 只有价格下降才推送
    # --------------------------------------------------------

    if current_price >= old_price:

        print(
            "价格没有下降："
            f"${old_price:.2f}"
            " -> "
            f"${current_price:.2f}"
        )

        return False

    # --------------------------------------------------------
    # 折扣至少 20%
    # --------------------------------------------------------

    alert_tier = get_alert_tier(
        product
    )

    if alert_tier is None:

        print(
            "价格下降，但折扣不足 20%，不推送。"
        )

        return False

    print(
        "发现真正降价："
        f"${old_price:.2f}"
        " -> "
        f"${current_price:.2f}"
    )

    return True


# ============================================================
# 历史记录
# ============================================================

def make_history_record(
    product
):
    return {
        "title":
            product.get(
                "title",
                ""
            ),

        "url":
            product.get(
                "url",
                ""
            ),

        "lowest_price":
            get_lowest_price(
                product
            ),

        "tiers":
            product.get(
                "tiers",
                []
            ),

        "updated_at":
            int(
                time.time()
            ),
    }


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
        "严格商品匹配 + 轮询 + 降价提醒"
    )

    print(
        "======================================"
    )

    if not FIRECRAWL_API_KEY:

        print(
            "错误：FIRECRAWL_API_KEY 未配置"
        )

        return

    history = load_history()

    # ========================================================
    # 1. 抓品牌列表
    # ========================================================

    all_products = {}

    for brand, url in BRAND_LIST_URLS.items():

        print()
        print(
            "抓取列表:",
            brand
        )

        data = firecrawl_scrape(
            url,
            ["markdown"]
        )

        if not data:

            print(
                "列表抓取失败"
            )

            continue

        links = extract_product_links(
            data,
            brand
        )

        print(
            "发现商品:",
            len(links)
        )

        for item in links:

            all_products[
                item["url"]
            ] = item

    print()
    print(
        "总商品链接:",
        len(all_products)
    )

    # ========================================================
    # 2. 严格筛选重点商品
    # ========================================================

    watch_products = []

    for item in all_products.values():

        if match_watch_product(
            item["url"]
        ):

            watch_products.append(
                item
            )

    # 稳定排序
    watch_products.sort(
        key=lambda x: x["url"]
    )

    print(
        "重点商品:",
        len(watch_products)
    )

    for index, item in enumerate(
        watch_products,
        1
    ):

        print(
            f"  {index}. "
            f"{item['url']}"
        )

    # ========================================================
    # 3. 轮询
    # ========================================================

    monitor_state = history.get(
        "__monitor_state__",
        {}
    )

    try:

        next_index = int(
            monitor_state.get(
                "next_index",
                0
            )
        )

    except Exception:

        next_index = 0

    total = len(
        watch_products
    )

    if total == 0:

        detail_products = []

        history[
            "__monitor_state__"
        ] = {
            "next_index": 0
        }

    else:

        if next_index >= total:

            next_index = 0

        end_index = (
            next_index
            + MAX_DETAIL_PER_RUN
        )

        if end_index <= total:

            detail_products = (
                watch_products[
                    next_index:end_index
                ]
            )

        else:

            detail_products = (
                watch_products[
                    next_index:
                ]
                + watch_products[
                    :end_index - total
                ]
            )

        next_index_after = (
            next_index
            + MAX_DETAIL_PER_RUN
        ) % total

        history[
            "__monitor_state__"
        ] = {
            "next_index":
                next_index_after
        }

    print()

    print(
        "轮询位置:",
        next_index,
        "->",
        history[
            "__monitor_state__"
        ]["next_index"]
    )

    print(
        "本轮抓取详情:",
        len(detail_products)
    )

    # ========================================================
    # 4. 详情
    # ========================================================

    for index, item in enumerate(
        detail_products,
        1
    ):

        print()
        print(
            f"[{index}/{len(detail_products)}]"
        )

        print(
            "抓取重点商品:"
        )

        print(
            item["url"]
        )

        product = scrape_product(
            item
        )

        if product is None:

            continue

        key = product[
            "url"
        ]

        old_record = history.get(
            key
        )

        # ====================================================
        # 降价判断
        # ====================================================

        if should_notify(
            old_record,
            product
        ):

            message = make_message(
                product
            )

            if message:

                image = product.get(
                    "image",
                    ""
                )

                sent = False

                if image:

                    sent = (
                        telegram_send_photo(
                            image,
                            message
                        )
                    )

                if not sent:

                    telegram_send_message(
                        message
                    )

        # ====================================================
        # 保存历史
        # ====================================================

        history[
            key
        ] = make_history_record(
            product
        )

        # ====================================================
        # 限速
        # ====================================================

        if (
            index
            < len(detail_products)
        ):

            print(
                f"等待 "
                f"{DETAIL_WAIT_SECONDS} 秒..."
            )

            time.sleep(
                DETAIL_WAIT_SECONDS
            )

    # ========================================================
    # 5. 保存
    # ========================================================

    save_history(
        history
    )

    print()
    print(
        "本轮价格历史已保存。"
    )

    print()
    print(
        "======================================"
    )

    print(
        "运行完成"
    )

    print(
        "======================================"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
