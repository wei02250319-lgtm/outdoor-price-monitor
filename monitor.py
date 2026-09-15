import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# ============================================================
# 基本配置
# ============================================================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

HISTORY_FILE = Path("data/prices.json")

# 每次只抓 3 个重点商品
MAX_DETAIL_PER_RUN = 3

# Firecrawl 每分钟限制较低，详情页之间故意等待
DETAIL_WAIT_SECONDS = 9

# 美元 -> 人民币
# 后续可以再接实时汇率
USD_CNY = 7.15

# 只有降价才推送
ONLY_PRICE_DROP = True

# 折扣达到 20% 才作为值得提醒的折扣
ALERT_DISCOUNT_MIN = 20


# ============================================================
# 监控品牌
# ============================================================

BRAND_LIST_URLS = {
    "Arc'teryx": "https://www.rei.com/b/arcteryx/c/all",
    "Patagonia": "https://www.rei.com/b/patagonia/c/all",
    "The North Face": "https://www.rei.com/b/the-north-face/c/all",
}


# ============================================================
# 重点商品
# ============================================================

WATCHLIST = [
    "Arc'teryx Gamma MX",
    "Arc'teryx Gamma Jacket",
    "Arc'teryx Gamma Pant",
    "Patagonia R2 TechFace Jacket",
    "Patagonia R2 TechFace Hoody",
    "Patagonia C1",
    "Patagonia Capilene Cool Daily Graphic Hoody",
    "Arc'teryx Atom Insulated Jacket",
    "Arc'teryx Atom Insulated Hoody",

    # 临时扩大监控范围
    "Arc'teryx Beta AR",
    "Arc'teryx Beta Jacket",
    "Arc'teryx Beta LT",
]


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; Mobile) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Mobile Safari/537.36"
        ),
        "Accept": "application/json",
    }
)


# ============================================================
# 文件
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
        print("读取价格历史失败:", e)

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

    temp_file.replace(HISTORY_FILE)


# ============================================================
# Firecrawl
# ============================================================

def firecrawl_scrape(
    url,
    formats=None
):
    if not FIRECRAWL_API_KEY:
        print("错误：没有 FIRECRAWL_API_KEY")
        return {}

    if formats is None:
        formats = ["markdown"]

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

        if response.status_code == 429:
            print(
                "Firecrawl 触发限速，等待 15 秒后重试..."
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

        data = response.json()

        if not data.get("success", True):
            print(
                "Firecrawl 返回失败:",
                data
            )
            return {}

        return data.get(
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
# 文本清理
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


def clean_product_title(title):
    title = clean_text(title)

    # 修复 Arc'teryxAtom 这种情况
    title = re.sub(
        r"(Arc'teryx)(?=[A-Z])",
        r"\1 ",
        title
    )

    title = re.sub(
        r"(Patagonia)(?=[A-Z])",
        r"\1 ",
        title
    )

    title = re.sub(
        r"(The North Face)(?=[A-Z])",
        r"\1 ",
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

    if not url.startswith("http"):
        return ""

    # 去掉 query
    url = url.split("?")[0]

    return url.rstrip("/")


# ============================================================
# 从列表页寻找商品链接
# ============================================================

def extract_product_links(
    data,
    brand_name
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
    # Markdown 链接
    # --------------------------------------------------------

    markdown_pattern = re.compile(
        r"\]\((https?://www\.rei\.com/product/\d+/[^)\s]+)"
        r"|"
        r"\]\((/product/\d+/[^)\s]+)"
    )

    for match in markdown_pattern.finditer(
        markdown
    ):
        url = (
            match.group(1)
            or match.group(2)
        )

        url = normalize_url(url)

        if "/product/" in url:
            links[url] = {
                "brand": brand_name,
                "url": url,
            }

    # --------------------------------------------------------
    # 原始 HTML
    # --------------------------------------------------------

    html_pattern = re.compile(
        r'https?://www\.rei\.com/product/\d+/[A-Za-z0-9_\-]+'
        r'|'
        r'/product/\d+/[A-Za-z0-9_\-]+'
    )

    for match in html_pattern.finditer(
        raw_html
    ):
        url = normalize_url(
            match.group(0)
        )

        if "/product/" in url:
            links[url] = {
                "brand": brand_name,
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
                href = normalize_url(
                    a.get("href")
                )

                if "/product/" in href:
                    links[href] = {
                        "brand": brand_name,
                        "url": href,
                    }

        except Exception:
            pass

    return list(
        links.values()
    )


# ============================================================
# 重点商品匹配
# ============================================================

def watch_match(
    product_url,
    product_title=""
):
    text = (
        product_url
        + " "
        + product_title
    ).lower()

    # URL/title 统一
    text = text.replace(
        "-",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # Arc'teryx
    arcteryx_words = [
        "arcteryx",
        "arc teryx",
    ]

    # Patagonia
    patagonia_words = [
        "patagonia",
    ]

    # --------------------------------------------------------
    # Arc'teryx Gamma MX
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "gamma" in text
        and "mx" in text
    ):
        return True

    # --------------------------------------------------------
    # Gamma Jacket
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "gamma" in text
        and "jacket" in text
    ):
        return True

    # --------------------------------------------------------
    # Gamma Pants / Pant
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "gamma" in text
        and (
            "pants" in text
            or "pant" in text
        )
    ):
        return True

    # --------------------------------------------------------
    # Beta AR
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "beta" in text
        and "ar" in text
    ):
        return True

    # --------------------------------------------------------
    # Beta Jacket
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "beta" in text
        and "jacket" in text
    ):
        return True

    # --------------------------------------------------------
    # Beta LT
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "beta" in text
        and "lt" in text
    ):
        return True

    # --------------------------------------------------------
    # Atom
    # --------------------------------------------------------

    if (
        any(x in text for x in arcteryx_words)
        and "atom" in text
        and (
            "insulated" in text
            or "jacket" in text
            or "hoody" in text
            or "hood" in text
        )
    ):
        return True

    # --------------------------------------------------------
    # Patagonia R2 TechFace
    # --------------------------------------------------------

    if (
        any(x in text for x in patagonia_words)
        and "r2" in text
        and "techface" in text
    ):
        return True

    # --------------------------------------------------------
    # Patagonia Capilene
    # --------------------------------------------------------

    if (
        any(x in text for x in patagonia_words)
        and "capilene" in text
        and "cool" in text
        and "daily" in text
    ):
        return True

    # --------------------------------------------------------
    # Patagonia C1
    # --------------------------------------------------------

    if (
        any(x in text for x in patagonia_words)
        and re.search(
            r"\bc1\b",
            text
        )
    ):
        return True

    return False


# ============================================================
# 价格解析
# ============================================================

PRICE_RE = re.compile(
    r"\$([\d,]+(?:\.\d{1,2})?)"
)


def money(value):
    try:
        return float(
            str(value)
            .replace(
                ",",
                ""
            )
        )
    except Exception:
        return None


def discount_percent(
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
        (1 - current / original)
        * 100
    )


def usd_to_cny(value):
    if value is None:
        return None

    return round(
        value * USD_CNY,
        2
    )


# ============================================================
# 价格层级
# ============================================================

def extract_price_tiers(markdown):
    if not markdown:
        return []

    text = clean_text(
        markdown
    )

    tiers = []

    # --------------------------------------------------------
    # REI 常见格式
    #
    # $399.83 Compared to $650.00
    # Save 38%
    # --------------------------------------------------------

    pattern = re.compile(
        r"\$([\d,]+(?:\.\d{1,2})?)"
        r"\s*"
        r"(?:Compared to|compare to)"
        r"\s*"
        r"\$([\d,]+(?:\.\d{1,2})?)"
        r"(?:.*?"
        r"(?:Save|save)"
        r"\s*(\d+)%"
        r")?",
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
            else discount_percent(
                current,
                original
            )
        )

        if (
            current is not None
            and original is not None
            and current < original
        ):
            tiers.append(
                {
                    "current": current,
                    "original": original,
                    "discount": discount,
                }
            )

    # --------------------------------------------------------
    # 备用格式：
    # $199.83 / $300
    # --------------------------------------------------------

    if not tiers:
        pattern2 = re.compile(
            r"\$([\d,]+(?:\.\d{1,2})?)"
            r"\s*/\s*"
            r"\$([\d,]+(?:\.\d{1,2})?)"
            r"(?:\s*(\d+)%\s*OFF)?",
            re.I
        )

        for match in pattern2.finditer(
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
                else discount_percent(
                    current,
                    original
                )
            )

            if (
                current is not None
                and original is not None
                and current < original
            ):
                tiers.append(
                    {
                        "current": current,
                        "original": original,
                        "discount": discount,
                    }
                )

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
# 图片
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

    # og:image
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

    # REI media/product
    match = re.search(
        r"https://www\.rei\.com/media/product/\d+",
        raw_html
    )

    if match:
        return match.group(0)

    # markdown 图片
    match = re.search(
        r"!\[[^\]]*\]\((https?://[^)]+)\)",
        markdown
    )

    if match:
        return match.group(1)

    return ""


# ============================================================
# 从 JSON-LD / 页面 JSON 中寻找商品信息
# ============================================================

def walk_json(
    obj,
    results
):
    if isinstance(obj, dict):

        results.append(obj)

        for value in obj.values():
            walk_json(
                value,
                results
            )

    elif isinstance(obj, list):

        for value in obj:
            walk_json(
                value,
                results
            )


def extract_json_objects(
    raw_html
):
    objects = []

    if not raw_html:
        return objects

    try:
        soup = BeautifulSoup(
            raw_html,
            "lxml"
        )

        for script in soup.find_all(
            "script"
        ):

            text = script.string

            if not text:
                text = script.get_text()

            if not text:
                continue

            text = text.strip()

            # JSON-LD
            if (
                script.get(
                    "type",
                    ""
                ).lower()
                == "application/ld+json"
            ):

                try:
                    obj = json.loads(
                        text
                    )

                    walk_json(
                        obj,
                        objects
                    )

                except Exception:
                    pass

            # Next / React / 页面状态
            elif (
                "__NEXT_DATA__"
                in str(
                    script.get(
                        "id",
                        ""
                    )
                )
            ):

                try:
                    obj = json.loads(
                        text
                    )

                    walk_json(
                        obj,
                        objects
                    )

                except Exception:
                    pass

    except Exception:
        pass

    return objects


# ============================================================
# 变体信息
#
# 重要：
# 如果页面没有明确告诉我们某个价格对应哪个颜色/尺码，
# 就绝不强行绑定。
# ============================================================

def find_variant_data(
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

        keys = {
            str(k).lower()
            for k in obj.keys()
        }

        # 找价格字段
        current = None
        original = None

        for key in [
            "saleprice",
            "sale_price",
            "currentprice",
            "current_price",
            "price",
        ]:

            if key in obj:
                current = money(
                    obj.get(key)
                )

                if current is not None:
                    break

        for key in [
            "originalprice",
            "original_price",
            "compareatprice",
            "compare_at_price",
            "regularprice",
            "regular_price",
        ]:

            if key in obj:
                original = money(
                    obj.get(key)
                )

                if original is not None:
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
            "colorname",
            "color_name",
        ]:

            if key in obj:
                value = obj.get(key)

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
            "sizename",
            "size_name",
        ]:

            if key in obj:

                value = obj.get(key)

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
            "instock",
            "in_stock",
            "inventory",
        ]:

            if key in obj:

                value = obj.get(key)

                if isinstance(
                    value,
                    bool
                ):
                    available = value

                elif isinstance(
                    value,
                    str
                ):

                    value_lower = (
                        value.lower()
                    )

                    if any(
                        x in value_lower
                        for x in [
                            "instock",
                            "in stock",
                            "available",
                        ]
                    ):
                        available = True

                    elif any(
                        x in value_lower
                        for x in [
                            "outofstock",
                            "out of stock",
                            "soldout",
                            "sold out",
                        ]
                    ):
                        available = False

                break

        variants.append(
            {
                "current": current,
                "original": original,
                "discount":
                    discount_percent(
                        current,
                        original
                    ),
                "color": color,
                "size": size,
                "available": available,
            }
        )

    # 去重
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
# 将变体整理成价格层级
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
        ]:
            groups[
                key
            ]["colors"][color] = {
                "sizes": [],
                "available": [],
            }

        if item["size"]:

            if item["size"] not in groups[
                key
            ]["colors"][color]["sizes"]:

                groups[
                    key
                ]["colors"][color]["sizes"].append(
                    item["size"]
                )

        if item["available"] is not None:

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

    # Markdown 第一批标题
    title_match = re.search(
        r"^#\s+(.+)$",
        markdown,
        re.MULTILINE
    )

    if title_match:
        title = clean_product_title(
            title_match.group(1)
        )

    if not title:

        # 从 URL 推断
        last = url.rstrip(
            "/"
        ).split("/")[-1]

        title = last.replace(
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
    # 价格
    # --------------------------------------------------------

    price_tiers = extract_price_tiers(
        markdown
    )

    # --------------------------------------------------------
    # 真正的变体
    # --------------------------------------------------------

    variants = find_variant_data(
        raw_html
    )

    variant_tiers = build_variant_tiers(
        variants
    )

    # --------------------------------------------------------
    # 如果找到真正的变体价格
    # 优先使用变体价格
    # --------------------------------------------------------

    if variant_tiers:

        tiers = variant_tiers

    else:

        tiers = []

        for tier in price_tiers:

            tiers.append(
                {
                    "current":
                        tier["current"],
                    "original":
                        tier["original"],
                    "discount":
                        tier["discount"],
                    "colors": {
                        "颜色/尺码页面未明确":
                            {
                                "sizes": [],
                                "available": [],
                            }
                    },
                }
            )

    # --------------------------------------------------------
    # 只保留真正打折价格
    # --------------------------------------------------------

    tiers = [
        x
        for x in tiers
        if (
            x.get("current")
            is not None
            and x.get("original")
            is not None
            and x["current"]
            < x["original"]
        )
    ]

    if not tiers:
        print(
            "没有发现折扣商品"
        )
        return {
            "url": url,
            "title": title,
            "image": image,
            "tiers": [],
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
            "  原价 ${:.2f} -> "
            "现价 ${:.2f} ({}%)".format(
                tier["original"],
                tier["current"],
                tier["discount"]
            )
        )

    return {
        "url": url,
        "title": title,
        "image": image,
        "tiers": tiers,
    }


# ============================================================
# 最低价格
# ============================================================

def lowest_price(product):
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

    return min(prices)


# ============================================================
# 计算最值得提醒的折扣
# ============================================================

def best_alert_tier(
    product
):
    candidates = []

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
            candidates.append(
                tier
            )

    if not candidates:
        return None

    # 最低价格优先
    candidates.sort(
        key=lambda x: (
            x["current"],
            -x["discount"]
        )
    )

    return candidates[0]


# ============================================================
# 格式化颜色 / 尺码
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

    names = list(
        colors.keys()
    )

    lines = []

    # --------------------------------------------------------
    # 颜色横向
    # --------------------------------------------------------

    lines.append(
        "颜色       "
        + "      ".join(
            names
        )
    )

    # --------------------------------------------------------
    # 尺码横向
    # --------------------------------------------------------

    size_parts = []

    for color in names:

        sizes = colors[
            color
        ].get(
            "sizes",
            []
        )

        if sizes:
            size_text = " ".join(
                sizes
            )
        else:
            size_text = "未明确"

        size_parts.append(
            size_text
        )

    lines.append(
        "尺码       "
        + "      ".join(
            size_parts
        )
    )

    # --------------------------------------------------------
    # 库存
    # --------------------------------------------------------

    stock_parts = []

    for color in names:

        available = colors[
            color
        ].get(
            "available",
            []
        )

        if not available:
            stock_text = "未明确"

        elif any(
            available
        ):
            stock_text = "有货"

        else:
            stock_text = "无货"

        stock_parts.append(
            stock_text
        )

    lines.append(
        "库存       "
        + "      ".join(
            stock_parts
        )
    )

    return "\n".join(
        lines
    )


# ============================================================
# Telegram 文本
# ============================================================

def make_telegram_message(
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

    tiers = product.get(
        "tiers",
        []
    )

    # 只展示达到 20% 的折扣层级
    alert_tiers = [
        tier
        for tier in tiers
        if tier.get(
            "discount",
            0
        ) >= ALERT_DISCOUNT_MIN
    ]

    if not alert_tiers:
        return ""

    parts = []

    for index, tier in enumerate(
        alert_tiers
    ):

        discount = tier[
            "discount"
        ]

        current = tier[
            "current"
        ]

        original = tier[
            "original"
        ]

        # ----------------------------------------------------
        # 折扣等级
        # ----------------------------------------------------

        if discount >= 50:
            icon = "🔥🔥"
        elif discount >= 30:
            icon = "🔥"
        else:
            icon = "🏷️"

        # ----------------------------------------------------
        # 标题
        # ----------------------------------------------------

        block = []

        block.append(
            f"{icon} {discount}% OFF｜{title}"
        )

        block.append(
            "🏷️ 原价 "
            f"${original:.2f}"
            f"（¥{usd_to_cny(original):.0f}）"
            "｜💰 现价 "
            f"${current:.2f}"
            f"（¥{usd_to_cny(current):.0f}）"
        )

        # ----------------------------------------------------
        # 颜色/尺码/库存
        # ----------------------------------------------------

        variant_text = (
            format_variant_table(
                tier
            )
        )

        if variant_text:
            block.append(
                variant_text
            )

        # ----------------------------------------------------
        # 商品链接
        # ----------------------------------------------------

        block.append(
            url
        )

        parts.append(
            "\n".join(block)
        )

    return (
        "\n\n"
        + "\n\n━━━━━━━━━━━━\n\n"
        .join(parts)
    )


# ============================================================
# Telegram
# ============================================================

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

    api = (
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
            api,
            json=payload,
            timeout=30
        )

        print(
            "Telegram:",
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

    api = (
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
            api,
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
            response.text[:1000]
        )

    except Exception as e:
        print(
            "Telegram 图片异常:",
            e
        )

    return False


# ============================================================
# 是否应该推送
# ============================================================

def should_notify(
    old_record,
    product
):
    current_lowest = lowest_price(
        product
    )

    if current_lowest is None:
        return False

    # --------------------------------------------------------
    # 第一次发现
    # 建立基线，不推
    # --------------------------------------------------------

    if not old_record:
        print(
            "首次发现，建立价格基线，不推送。"
        )
        return False

    old_lowest = old_record.get(
        "lowest_price"
    )

    if old_lowest is None:
        return False

    # --------------------------------------------------------
    # 只有价格下降才推
    # --------------------------------------------------------

    if current_lowest >= old_lowest:
        print(
            f"价格没有下降："
            f"${old_lowest:.2f} -> "
            f"${current_lowest:.2f}"
        )
        return False

    # --------------------------------------------------------
    # 必须至少有 20% 折扣
    # --------------------------------------------------------

    alert_tier = best_alert_tier(
        product
    )

    if alert_tier is None:
        print(
            "价格下降，但折扣不足 20%，不推送。"
        )
        return False

    print(
        "检测到降价："
        f"${old_lowest:.2f} -> "
        f"${current_lowest:.2f}"
    )

    return True


# ============================================================
# 保存商品历史
# ============================================================

def product_history_record(
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
            lowest_price(
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
        "轮询 + 图片 + 降价 + 颜色/尺码/库存"
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
    # 第一步：抓品牌列表
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
    # 第二步：筛重点商品
    # ========================================================

    watch_products = []

    for item in all_products.values():

        if watch_match(
            item["url"]
        ):
            watch_products.append(
                item
            )

    # --------------------------------------------------------
    # URL 排序，保证轮询顺序稳定
    # --------------------------------------------------------

    watch_products.sort(
        key=lambda x: x["url"]
    )

    print(
        "重点商品:",
        len(watch_products)
    )

    for i, item in enumerate(
        watch_products,
        1
    ):
        print(
            f"  {i}. {item['url']}"
        )

    # ========================================================
    # 第三步：轮询
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

    total_watch = len(
        watch_products
    )

    if total_watch == 0:

        detail_products = []

        history[
            "__monitor_state__"
        ] = {
            "next_index": 0
        }

    else:

        if next_index >= total_watch:
            next_index = 0

        end_index = (
            next_index
            + MAX_DETAIL_PER_RUN
        )

        if end_index <= total_watch:

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
                    :end_index - total_watch
                ]
            )

        next_round = (
            next_index
            + MAX_DETAIL_PER_RUN
        ) % total_watch

        history[
            "__monitor_state__"
        ] = {
            "next_index":
                next_round
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
    # 第四步：抓详情
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

        # ====================================================
        # 历史记录 key
        # ====================================================

        key = product[
            "url"
        ]

        old_record = history.get(
            key
        )

        # ====================================================
        # 是否推送
        # ====================================================

        notify = should_notify(
            old_record,
            product
        )

        if notify:

            message = (
                make_telegram_message(
                    product
                )
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
        ] = product_history_record(
            product
        )

        # ====================================================
        # 详情页限速
        # ====================================================

        if index < len(
            detail_products
        ):

            print(
                f"等待 {DETAIL_WAIT_SECONDS} 秒..."
            )

            time.sleep(
                DETAIL_WAIT_SECONDS
            )

    # ========================================================
    # 保存
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
# 启动
# ============================================================

if __name__ == "__main__":
    main()
