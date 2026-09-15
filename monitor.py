import os
import re
import json
import requests
from datetime import datetime, timezone

# =========================
# 基本设置
# =========================

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

REI_URL = "https://www.rei.com/b/arcteryx/c/all"

DATA_FILE = "data/prices.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 重点商品
WATCHLIST = [
    "Gamma MX",
    "Gamma Jacket",
    "Gamma Pant",
    "Gamma Pants",
    "Atom Insulated Jacket",
    "Atom Insulated Hoody",
]

# 重点关注尺码
FOCUS_SIZES = ["M", "L", "XL"]


# =========================
# 文件
# =========================

def load_history():
    if not os.path.exists(DATA_FILE):
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(data):
    os.makedirs("data", exist_ok=True)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================
# Telegram
# =========================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram 配置不存在")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(
            url,
            data=data,
            timeout=30
        )

        print("Telegram:", r.status_code)

        return r.status_code == 200

    except Exception as e:
        print("Telegram 错误:", e)
        return False


# =========================
# Firecrawl
# =========================

def firecrawl(url):
    payload = {
        "url": url,
        "formats": ["markdown"]
    }

    try:
        r = requests.post(
            FIRECRAWL_URL,
            json=payload,
            timeout=120
        )

        print("Firecrawl:", r.status_code)

        if r.status_code != 200:
            print(r.text[:500])
            return ""

        result = r.json()

        return result.get("data", {}).get("markdown", "")

    except Exception as e:
        print("Firecrawl 错误:", e)
        return ""


# =========================
# 商品链接
# =========================

def get_product_links(markdown):

    links = re.findall(
        r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
        markdown
    )

    links = list(dict.fromkeys(links))

    return links


# =========================
# 商品名称
# =========================

def get_product_name(text):

    patterns = [
        r"(Arc'teryx[^\n]+)",
        r"(Arc’teryx[^\n]+)"
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:
            name = match.group(1).strip()

            name = name.split("$")[0].strip()

            return name

    return "Arc'teryx 商品"


# =========================
# 价格
# =========================

def get_prices(text):

    prices = re.findall(
        r'\$\s?(\d+(?:\.\d{2})?)',
        text
    )

    prices = [
        float(x)
        for x in prices
    ]

    # 去重
    prices = list(dict.fromkeys(prices))

    if not prices:
        return None, None

    if len(prices) == 1:
        return prices[0], None

    # REI 常见格式：
    # $199.83 - $400.00
    sale_price = min(prices)
    original_price = max(prices)

    return sale_price, original_price


# =========================
# 折扣
# =========================

def calculate_discount(sale, original):

    if not sale or not original:
        return 0

    if original <= sale:
        return 0

    discount = (
        1 - sale / original
    ) * 100

    return round(discount, 1)


# =========================
# 人民币
# =========================

def usd_to_rmb(usd):

    # 暂时使用一个保守汇率。
    # 后面再接实时汇率。
    rate = 7.2

    return round(usd * rate, 2)


# =========================
# 尺码
# =========================

def get_sizes(text):

    possible = [
        "XS",
        "S",
        "M",
        "L",
        "XL",
        "XXL"
    ]

    found = []

    for size in possible:

        pattern = rf"\b{size}\b"

        if re.search(pattern, text):
            found.append(size)

    return found


# =========================
# 颜色
# =========================

def get_colors(text):

    colors = []

    color_words = [
        "Black",
        "Blue",
        "Green",
        "Red",
        "Grey",
        "Gray",
        "White",
        "Brown",
        "Orange",
        "Yellow",
        "Purple",
        "Navy",
        "Stone",
        "Sapphire",
        "Mantis",
        "Cloud",
        "Moon"
    ]

    for word in color_words:

        if re.search(
            rf"\b{re.escape(word)}\b",
            text,
            re.I
        ):
            colors.append(word)

    return list(dict.fromkeys(colors))


# =========================
# 是否重点商品
# =========================

def is_watchlist(name):

    name_lower = name.lower()

    for item in WATCHLIST:

        if item.lower() in name_lower:
            return True

    return False


# =========================
# 是否应该推送
# =========================

def should_notify(old, current):

    if not old:
        # 第一次发现商品
        # 只有有折扣才推送
        return current["discount"] > 0

    old_price = old.get("price")
    new_price = current.get("price")

    old_discount = old.get("discount", 0)
    new_discount = current.get("discount", 0)

    # 价格变化
    if old_price and new_price:

        if old_price != new_price:
            return True

    # 从无折扣进入折扣
    if old_discount == 0 and new_discount > 0:
        return True

    # 折扣增加
    if new_discount > old_discount:
        return True

    # 重点商品，价格变化就提醒
    if current["watchlist"] and old_price != new_price:
        return True

    # 尺码变化
    if old.get("sizes", []) != current.get("sizes", []):
        return True

    # 颜色变化
    if old.get("colors", []) != current.get("colors", []):
        return True

    return False


# =========================
# Telegram 消息
# =========================

def build_message(product):

    name = product["name"]

    price = product["price"]
    original = product["original"]
    discount = product["discount"]

    rmb = usd_to_rmb(price)

    if discount >= 50:
        level = "🔥🔥🔥 超级优惠"

    elif discount >= 30:
        level = "🔥🔥 大促"

    elif discount >= 20:
        level = "🔥 优惠"

    elif discount > 0:
        level = "🏷️ 促销"

    else:
        level = ""

    lines = []

    lines.append(
        f"🏔️ {name}"
    )

    lines.append("")

    lines.append(
        f"🇺🇸 REI价格：${price:.2f}"
    )

    lines.append(
        f"🇨🇳 人民币：¥{rmb:.2f}"
    )

    if original and original > price:

        lines.append(
            f"原价：${original:.2f}"
        )

        lines.append(
            f"折扣：{discount:.1f}% {level}"
        )

    else:

        lines.append(
            "折扣：无"
        )

    sizes = product.get("sizes", [])

    focus = [
        x for x in sizes
        if x in FOCUS_SIZES
    ]

    if focus:

        lines.append(
            "尺码："
            + " / ".join(focus)
        )

    else:

        lines.append(
            "尺码：暂无重点尺码数据"
        )

    colors = product.get("colors", [])

    if colors:

        lines.append(
            "颜色："
            + " / ".join(colors[:10])
        )

    lines.append("")

    if product["watchlist"]:
        lines.append("⭐ 重点监控商品")

    lines.append(
        f"🔗 {product['url']}"
    )

    return "\n".join(lines)


# =========================
# 主程序
# =========================

def main():

    print("=" * 60)
    print("REI 户外商品价格监控")
    print("Firecrawl + Telegram")
    print("=" * 60)

    history = load_history()

    # 抓取 REI Arc'teryx 分类页
    print()
    print("正在抓取 REI：")
    print(REI_URL)

    markdown = firecrawl(REI_URL)

    if not markdown:

        print("❌ REI 页面抓取失败")
        return

    print(
        "网页内容长度:",
        len(markdown)
    )

    links = get_product_links(markdown)

    print(
        "发现商品:",
        len(links)
    )

    if not links:
        print("❌ 没找到商品")
        return

    changed_count = 0
    checked_count = 0

    # 先处理前 10 个商品
    for link in links[:10]:

        print()
        print("-" * 60)
        print("商品链接:")
        print(link)

        # 从列表页附近寻找商品信息
        pos = markdown.find(link)

        if pos < 0:
            continue

        text = markdown[pos:pos + 2500]

        name = get_product_name(text)

        price, original = get_prices(text)

        if not price:
            print("❌ 没找到价格")
            continue

        discount = calculate_discount(
            price,
            original
        )

        sizes = get_sizes(text)

        colors = get_colors(text)

        product_id = link

        current = {
            "name": name,
            "url": link,
            "price": price,
            "original": original,
            "discount": discount,
            "sizes": sizes,
            "colors": colors,
            "watchlist": is_watchlist(name),
            "updated": datetime.now(
                timezone.utc
            ).isoformat()
        }

        old = history.get(product_id)

        print("商品:", name)
        print("价格:", price)
        print("原价:", original)
        print("折扣:", discount, "%")
        print("尺码:", sizes)
        print("颜色:", colors)

        if should_notify(old, current):

            message = build_message(
                current
            )

            print("📲 发送 Telegram")

            if send_telegram(message):

                changed_count += 1

        else:

            print(
                "价格及商品信息没有变化，不推送"
            )

        history[product_id] = current

        checked_count += 1

    save_history(history)

    print()
    print("=" * 60)
    print(
        f"检查完成：{checked_count} 个商品"
    )
    print(
        f"发送提醒：{changed_count} 条"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
