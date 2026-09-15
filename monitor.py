import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup

# =========================
# 基本配置
# =========================

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

DATA_FILE = "data/prices.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# REI 品牌页
REI_PAGES = [
    "https://www.rei.com/b/arcteryx/c/all",
    "https://www.rei.com/b/patagonia/c/all",
    "https://www.rei.com/b/the-north-face/c/all",
]

# =========================
# 重点商品
# =========================

WATCHLIST = [
    "Beta AR",
    "Beta Jacket",
    "Beta LT",

    "Gamma MX",
    "Gamma Jacket",
    "Gamma Pant",
    "Gamma Pants",

    "Atom Insulated Jacket",
    "Atom Insulated Hoody",
    "Atom Jacket",

    "R2 TechFace Jacket",
    "R2 TechFace Hoody",

    "C1",
    "Capilene Cool Daily Graphic Hoody",
]

# 只重点显示这些尺码
FOCUS_SIZES = ["M", "L", "XL"]

# 每次最多处理多少个商品详情页
MAX_PRODUCTS = 12

USD_RMB = 7.20


# =========================
# Firecrawl
# =========================

def firecrawl(url):
    try:
        payload = {
            "url": url,
            "formats": ["markdown"]
        }

        r = requests.post(
            FIRECRAWL_URL,
            json=payload,
            timeout=120
        )

        print("Firecrawl:", r.status_code, url)

        if r.status_code != 200:
            print(r.text[:500])
            return ""

        data = r.json()

        return (
            data.get("data", {}).get("markdown")
            or data.get("markdown")
            or ""
        )

    except Exception as e:
        print("Firecrawl error:", e)
        return ""


# =========================
# Telegram
# =========================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets 未配置")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(
            url,
            json=payload,
            timeout=30
        )

        print("Telegram:", r.status_code)

        return r.status_code == 200

    except Exception as e:
        print("Telegram error:", e)
        return False


# =========================
# 历史数据
# =========================

def load_history():

    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return {}


def save_history(data):

    os.makedirs(
        os.path.dirname(DATA_FILE),
        exist_ok=True
    )

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================
# 商品链接
# =========================

def get_product_links(markdown):

    links = re.findall(
        r"https?://www\.rei\.com/product/\d+/[^\s\)\]\"<>]+",
        markdown
    )

    result = []

    for url in links:

        url = url.rstrip(".,;")

        if url not in result:
            result.append(url)

    return result


# =========================
# 商品名称
# =========================

def get_product_name(markdown, url):

    # 优先从标题寻找
    lines = markdown.splitlines()

    for line in lines:

        text = line.strip()

        if not text:
            continue

        if len(text) > 150:
            continue

        if (
            "Arc'teryx" in text
            or "Patagonia" in text
            or "The North Face" in text
        ):
            return text.lstrip("# ").strip()

    # URL 兜底
    slug = url.rstrip("/").split("/")[-1]

    slug = re.sub(
        r"^\d+/",
        "",
        slug
    )

    return slug.replace("-", " ").title()


# =========================
# 价格解析
# =========================

def extract_prices(text):

    prices = []

    for m in re.finditer(
        r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text
    ):

        try:
            price = float(m.group(1))

            if price < 10:
                continue

            if price > 3000:
                continue

            prices.append(price)

        except Exception:
            pass

    return sorted(set(prices))


# =========================
# 原价 / 优惠价
# =========================

def build_price_levels(prices):

    if not prices:
        return []

    prices = sorted(set(prices))

    highest = max(prices)

    levels = []

    for price in prices:

        # 最高价作为参考原价
        if price == highest:
            discount = 0
        else:
            discount = round(
                (highest - price) / highest * 100
            )

        levels.append({
            "price": price,
            "original": highest,
            "discount": discount,
            "currency": "USD",
            "rmb": round(price * USD_RMB, 2),
        })

    return levels


# =========================
# 尺码
# =========================

def extract_sizes(text):

    found = []

    patterns = [
        r"\bXXS\b",
        r"\bXS\b",
        r"\bS\b",
        r"\bM\b",
        r"\bL\b",
        r"\bXL\b",
        r"\bXXL\b",
    ]

    for pattern in patterns:

        if re.search(pattern, text):
            size = pattern.replace(
                r"\b",
                ""
            )

            if size not in found:
                found.append(size)

    return found


# =========================
# 颜色
# =========================

def extract_colors(text):

    colors = []

    common_colors = [
        "Black",
        "Blue",
        "Navy",
        "Green",
        "Grey",
        "Gray",
        "Brown",
        "Red",
        "White",
        "Yellow",
        "Orange",
        "Purple",
        "Beige",
        "Tan",
        "Olive",
        "Gold",
        "Silver",
    ]

    for color in common_colors:

        if re.search(
            rf"\b{re.escape(color)}\b",
            text,
            re.I
        ):

            if color not in colors:
                colors.append(color)

    return colors


# =========================
# 变体信息
# =========================

def build_variants(
    markdown,
    prices
):

    levels = build_price_levels(prices)

    sizes = extract_sizes(markdown)

    colors = extract_colors(markdown)

    variants = []

    for level in levels:

        # 原价层保留，但不推送
        variants.append({
            "price": level["price"],
            "original": level["original"],
            "discount": level["discount"],
            "currency": "USD",
            "rmb": level["rmb"],
            "colors": colors,
            "sizes": sizes,
            "focus_sizes": {
                size: size in sizes
                for size in FOCUS_SIZES
            },
        })

    return variants


# =========================
# 只留下优惠层
# =========================

def get_sale_variants(variants):

    sale = []

    for variant in variants:

        discount = variant.get(
            "discount",
            0
        )

        if discount > 0:
            sale.append(variant)

    return sale


# =========================
# 变体签名
# =========================

def variant_signature(variant):

    return {
        "price": variant.get("price"),
        "original": variant.get("original"),
        "discount": variant.get("discount"),
        "colors": variant.get("colors", []),
        "sizes": variant.get("sizes", []),
        "focus_sizes": variant.get(
            "focus_sizes",
            {}
        ),
    }


# =========================
# 判断是否需要推送
# =========================

def should_notify(
    old_product,
    new_product
):

    if not old_product:
        return True

    old_sale = old_product.get(
        "sale_variants",
        []
    )

    new_sale = new_product.get(
        "sale_variants",
        []
    )

    old_signatures = [
        variant_signature(v)
        for v in old_sale
    ]

    new_signatures = [
        variant_signature(v)
        for v in new_sale
    ]

    return old_signatures != new_signatures


# =========================
# 显示尺码
# =========================

def format_sizes(variant):

    focus = variant.get(
        "focus_sizes",
        {}
    )

    result = []

    for size in FOCUS_SIZES:

        if focus.get(size):
            result.append(
                f"{size} ✅"
            )
        else:
            result.append(
                f"{size} ❌"
            )

    return "  ".join(result)


# =========================
# Telegram 消息
# =========================

def build_message(product):

    name = product["name"]

    sale_variants = product.get(
        "sale_variants",
        []
    )

    if not sale_variants:
        return None

    lines = []

    lines.append(
        "🔥 <b>REI 优惠</b>"
    )

    lines.append("")
    lines.append(
        f"<b>{name}</b>"
    )

    lines.append(
        "━━━━━━━━━━━━"
    )

    for index, variant in enumerate(
        sale_variants,
        1
    ):

        price = variant["price"]

        original = variant["original"]

        discount = variant["discount"]

        rmb = variant["rmb"]

        lines.append("")

        if len(sale_variants) > 1:
            lines.append(
                f"<b>优惠 {index}</b>"
            )

        lines.append(
            f"💰 <b>${price:.2f}</b>"
        )

        if original:
            lines.append(
                f"🏷️ 原价 ${original:.2f}"
            )

        lines.append(
            f"📉 <b>{discount}% OFF</b>  "
            f"¥{rmb:,.0f}"
        )

        colors = variant.get(
            "colors",
            []
        )

        if colors:
            lines.append(
                "🎨 " + " / ".join(colors[:5])
            )

        lines.append(
            "📏 " + format_sizes(variant)
        )

        lines.append(
            "📦 有货"
        )

        if index != len(sale_variants):
            lines.append(
                "━━━━━━━━━━━━"
            )

    lines.append("")
    lines.append(
        "🕒 <i>仅优惠层级触发提醒</i>"
    )

    return "\n".join(lines)


# =========================
# 主程序
# =========================

def main():

    print("================================")
    print("REI Outdoor Price Monitor")
    print("================================")

    history = load_history()

    all_products = []

    # -------------------------
    # 先抓品牌列表页
    # -------------------------

    for page_url in REI_PAGES:

        print("")
        print(
            "抓取列表:",
            page_url
        )

        markdown = firecrawl(
            page_url
        )

        if not markdown:
            continue

        links = get_product_links(
            markdown
        )

        print(
            "发现商品:",
            len(links)
        )

        for link in links:

            all_products.append(link)

    # 去重
    all_products = list(
        dict.fromkeys(
            all_products
        )
    )

    print(
        "总商品链接:",
        len(all_products)
    )

    # -------------------------
    # 只处理重点商品
    # -------------------------

    selected = []

    for url in all_products:

        slug = url.lower()

        if any(
            item.lower() in slug
            for item in WATCHLIST
        ):
            selected.append(url)

    # 如果 URL 名称匹配不到，
    # 至少测试前 MAX_PRODUCTS 个
    if not selected:
        selected = all_products[
            :MAX_PRODUCTS
        ]

    selected = selected[
        :MAX_PRODUCTS
    ]

    print(
        "本轮处理:",
        len(selected)
    )

    # -------------------------
    # 详情页
    # -------------------------

    for url in selected:

        print("")
        print(
            "详情:",
            url
        )

        markdown = firecrawl(
            url
        )

        if not markdown:
            continue

        name = get_product_name(
            markdown,
            url
        )

        prices = extract_prices(
            markdown
        )

        print(
            "商品:",
            name
        )

        print(
            "价格:",
            prices
        )

        if not prices:
            continue

        variants = build_variants(
            markdown,
            prices
        )

        sale_variants = get_sale_variants(
            variants
        )

        product = {
            "name": name,
            "url": url,
            "variants": variants,
            "sale_variants": sale_variants,
        }

        old_product = history.get(
            url
        )

        if should_notify(
            old_product,
            product
        ):

            message = build_message(
                product
            )

            if message:

                print(
                    "发送优惠提醒:",
                    name
                )

                send_telegram(
                    message
                )

        else:

            print(
                "没有变化，不推送"
            )

        history[url] = product

        # 避免连续请求过快
        time.sleep(1)

    # -------------------------
    # 保存历史
    # -------------------------

    save_history(
        history
    )

    print("")
    print(
        "运行完成"
    )


if __name__ == "__main__":
    main()
