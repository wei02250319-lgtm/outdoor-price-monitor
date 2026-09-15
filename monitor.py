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

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print("读取历史记录失败:", e)

        return {}


def save_history(data):

    os.makedirs(
        "data",
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
# Telegram
# =========================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:

        print("❌ Telegram 配置不存在")

        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

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

        print(
            "Telegram:",
            r.status_code
        )

        if r.status_code != 200:

            print(r.text[:500])

        return r.status_code == 200

    except Exception as e:

        print(
            "Telegram 错误:",
            e
        )

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

        print(
            "Firecrawl:",
            r.status_code
        )

        if r.status_code != 200:

            print(r.text[:500])

            return ""

        result = r.json()

        data = result.get(
            "data",
            {}
        )

        return data.get(
            "markdown",
            ""
        )

    except Exception as e:

        print(
            "Firecrawl 错误:",
            e
        )

        return ""


# =========================
# 商品链接
# =========================

def get_product_links(markdown):

    links = re.findall(
        r'https://www\.rei\.com/product/\d+/[^\s\)\]]+',
        markdown
    )

    # 去重
    links = list(
        dict.fromkeys(links)
    )

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

        match = re.search(
            pattern,
            text
        )

        if match:

            name = match.group(1).strip()

            # 避免把价格一起带进商品名
            name = name.split("$")[0].strip()

            return name

    return "Arc'teryx 商品"


# =========================
# 价格 / 多优惠解析
# =========================

def get_offers(text):

    """
    返回多个优惠。

    每个优惠格式：

    {
        "price": 199.83,
        "original": 400.00,
        "discount": 50.0
    }

    如果只找到一个价格：

    {
        "price": 199.83,
        "original": None,
        "discount": 0
    }
    """

    offers = []

    # -------------------------------------------------
    # 第一种：
    # $199.83 - $400.00
    # -------------------------------------------------

    range_pattern = (
        r'\$\s?(\d+(?:\.\d{2})?)'
        r'\s*[-–—]\s*'
        r'\$\s?(\d+(?:\.\d{2})?)'
    )

    ranges = re.findall(
        range_pattern,
        text
    )

    for sale_str, original_str in ranges:

        sale = float(sale_str)
        original = float(original_str)

        # 正常情况下前面是低价，后面是高价
        if original > sale:

            discount = calculate_discount(
                sale,
                original
            )

            offers.append({
                "price": sale,
                "original": original,
                "discount": discount
            })

        else:

            # 防止网页顺序反过来
            discount = calculate_discount(
                original,
                sale
            )

            offers.append({
                "price": original,
                "original": sale,
                "discount": discount
            })

    # -------------------------------------------------
    # 第二种：
    # 页面里可能出现多个独立价格
    # -------------------------------------------------

    if not offers:

        prices = re.findall(
            r'\$\s?(\d+(?:\.\d{2})?)',
            text
        )

        prices = [
            float(x)
            for x in prices
        ]

        # 去重
        prices = list(
            dict.fromkeys(prices)
        )

        if not prices:

            return []

        if len(prices) == 1:

            return [{
                "price": prices[0],
                "original": None,
                "discount": 0
            }]

        # 如果没有明确的价格范围，
        # 不再简单丢掉其他价格。
        #
        # 将每一个价格都保留下来。
        for price in prices:

            offers.append({
                "price": price,
                "original": None,
                "discount": 0
            })

    # -------------------------------------------------
    # 去掉重复优惠
    # -------------------------------------------------

    unique = []

    seen = set()

    for offer in offers:

        key = (
            offer.get("price"),
            offer.get("original"),
            offer.get("discount")
        )

        if key in seen:
            continue

        seen.add(key)

        unique.append(offer)

    # -------------------------------------------------
    # 按当前价格从低到高排列
    # -------------------------------------------------

    unique.sort(
        key=lambda x: x.get(
            "price",
            999999
        )
    )

    return unique


# =========================
# 折扣
# =========================

def calculate_discount(
    sale,
    original
):

    if sale is None or original is None:
        return 0

    if original <= sale:
        return 0

    discount = (
        1 - sale / original
    ) * 100

    return round(
        discount,
        1
    )


# =========================
# 人民币
# =========================

def usd_to_rmb(usd):

    # 暂时使用固定汇率。
    # 后面再接实时汇率。
    rate = 7.2

    return round(
        usd * rate,
        2
    )


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

        if re.search(
            pattern,
            text
        ):

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

    return list(
        dict.fromkeys(colors)
    )


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
# 兼容旧历史记录
# =========================

def normalize_old_offers(old):

    if not old:
        return []

    # 新格式
    if isinstance(
        old.get("offers"),
        list
    ):

        return old.get(
            "offers",
            []
        )

    # 兼容以前的旧格式
    old_price = old.get("price")
    old_original = old.get("original")
    old_discount = old.get(
        "discount",
        0
    )

    if old_price is None:

        return []

    return [{
        "price": old_price,
        "original": old_original,
        "discount": old_discount
    }]


# =========================
# 比较多个优惠
# =========================

def offers_changed(
    old_offers,
    new_offers
):

    def normalize(offers):

        result = []

        for offer in offers:

            result.append((
                round(
                    float(
                        offer.get(
                            "price",
                            0
                        )
                    ),
                    2
                ),

                round(
                    float(
                        offer.get(
                            "original",
                            0
                        ) or 0
                    ),
                    2
                ),

                round(
                    float(
                        offer.get(
                            "discount",
                            0
                        ) or 0
                    ),
                    1
                )
            ))

        return sorted(result)

    return (
        normalize(old_offers)
        != normalize(new_offers)
    )


# =========================
# 是否应该推送
# =========================

def should_notify(
    old,
    current
):

    # 第一次发现商品
    if not old:

        # 有任何折扣就提醒
        for offer in current.get(
            "offers",
            []
        ):

            if offer.get(
                "discount",
                0
            ) > 0:

                return True

        return False

    old_offers = normalize_old_offers(
        old
    )

    new_offers = current.get(
        "offers",
        []
    )

    # -------------------------
    # 多优惠变化
    # -------------------------

    if offers_changed(
        old_offers,
        new_offers
    ):

        return True

    # -------------------------
    # 尺码变化
    # -------------------------

    old_sizes = old.get(
        "sizes",
        []
    )

    new_sizes = current.get(
        "sizes",
        []
    )

    old_focus = [
        x for x in old_sizes
        if x in FOCUS_SIZES
    ]

    new_focus = [
        x for x in new_sizes
        if x in FOCUS_SIZES
    ]

    if old_focus != new_focus:

        return True

    # -------------------------
    # 颜色变化
    # -------------------------

    if old.get(
        "colors",
        []
    ) != current.get(
        "colors",
        []
    ):

        return True

    # -------------------------
    # 重点商品价格变化
    # -------------------------

    if current.get(
        "watchlist",
        False
    ):

        if offers_changed(
            old_offers,
            new_offers
        ):

            return True

    return False


# =========================
# 优惠等级
# =========================

def get_discount_level(
    discount
):

    if discount >= 50:

        return "🔥🔥🔥 超级优惠"

    elif discount >= 30:

        return "🔥🔥 大促"

    elif discount >= 20:

        return "🔥 优惠"

    elif discount > 0:

        return "🏷️ 促销"

    return ""


# =========================
# Telegram 消息
# =========================

def build_message(product):

    name = product["name"]

    offers = product.get(
        "offers",
        []
    )

    lines = []

    lines.append(
        f"🏔️ {name}"
    )

    lines.append("")

    # -------------------------
    # 多个优惠
    # -------------------------

    if offers:

        lines.append(
            f"💰 当前发现 {len(offers)} 个价格/优惠"
        )

        lines.append("")

        for index, offer in enumerate(
            offers,
            start=1
        ):

            price = offer.get(
                "price"
            )

            original = offer.get(
                "original"
            )

            discount = offer.get(
                "discount",
                0
            )

            rmb = usd_to_rmb(
                price
            )

            level = get_discount_level(
                discount
            )

            lines.append(
                f"🎯 优惠 {index}"
            )

            lines.append(
                f"🇺🇸 现价：${price:.2f}"
            )

            lines.append(
                f"🇨🇳 人民币：¥{rmb:.2f}"
            )

            if (
                original
                and original > price
            ):

                lines.append(
                    f"原价：${original:.2f}"
                )

                lines.append(
                    f"折扣：{discount:.1f}%"
                    + (
                        f" {level}"
                        if level
                        else ""
                    )
                )

            else:

                lines.append(
                    "折扣：无明确原价"
                )

            lines.append("")

    else:

        lines.append(
            "价格：暂无"
        )

    # -------------------------
    # 尺码
    # -------------------------

    sizes = product.get(
        "sizes",
        []
    )

    focus = [
        x for x in sizes
        if x in FOCUS_SIZES
    ]

    if focus:

        lines.append(
            "📏 重点尺码："
            + " / ".join(focus)
        )

    else:

        lines.append(
            "📏 重点尺码：暂无数据"
        )

    # -------------------------
    # 颜色
    # -------------------------

    colors = product.get(
        "colors",
        []
    )

    if colors:

        lines.append(
            "🎨 颜色："
            + " / ".join(colors[:10])
        )

    # -------------------------
    # 重点商品
    # -------------------------

    lines.append("")

    if product.get(
        "watchlist",
        False
    ):

        lines.append(
            "⭐ 重点监控商品"
        )

    # -------------------------
    # 链接
    # -------------------------

    lines.append(
        f"🔗 {product['url']}"
    )

    return "\n".join(lines)


# =========================
# 主程序
# =========================

def main():

    print("=" * 60)

    print(
        "REI 户外商品价格监控"
    )

    print(
        "Firecrawl + Telegram"
    )

    print(
        "多优惠价格版本"
    )

    print("=" * 60)

    history = load_history()

    # -------------------------
    # 抓取 REI
    # -------------------------

    print()

    print(
        "正在抓取 REI："
    )

    print(
        REI_URL
    )

    markdown = firecrawl(
        REI_URL
    )

    if not markdown:

        print(
            "❌ REI 页面抓取失败"
        )

        return

    print(
        "网页内容长度:",
        len(markdown)
    )

    # -------------------------
    # 商品链接
    # -------------------------

    links = get_product_links(
        markdown
    )

    print(
        "发现商品:",
        len(links)
    )

    if not links:

        print(
            "❌ 没找到商品"
        )

        return

    changed_count = 0

    checked_count = 0

    # -------------------------
    # 目前仍先检查前 10 个
    # -------------------------

    for link in links[:10]:

        print()

        print(
            "-" * 60
        )

        print(
            "商品链接:"
        )

        print(
            link
        )

        # -------------------------
        # 找商品附近内容
        # -------------------------

        pos = markdown.find(
            link
        )

        if pos < 0:

            continue

        text = markdown[
            pos:pos + 2500
        ]

        # -------------------------
        # 商品名称
        # -------------------------

        name = get_product_name(
            text
        )

        # -------------------------
        # 多优惠价格
        # -------------------------

        offers = get_offers(
            text
        )

        if not offers:

            print(
                "❌ 没找到价格"
            )

            continue

        # -------------------------
        # 尺码
        # -------------------------

        sizes = get_sizes(
            text
        )

        # -------------------------
        # 颜色
        # -------------------------

        colors = get_colors(
            text
        )

        # -------------------------
        # 商品 ID
        # -------------------------

        product_id = link

        current = {

            "name": name,

            "url": link,

            "offers": offers,

            "sizes": sizes,

            "colors": colors,

            "watchlist": is_watchlist(
                name
            ),

            "updated": datetime.now(
                timezone.utc
            ).isoformat()
        }

        old = history.get(
            product_id
        )

        # -------------------------
        # 调试输出
        # -------------------------

        print(
            "商品:",
            name
        )

        print(
            "发现优惠数量:",
            len(offers)
        )

        for index, offer in enumerate(
            offers,
            start=1
        ):

            print(
                f"优惠 {index}:",
                offer
            )

        print(
            "尺码:",
            sizes
        )

        print(
            "颜色:",
            colors
        )

        # -------------------------
        # 判断是否推送
        # -------------------------

        if should_notify(
            old,
            current
        ):

            message = build_message(
                current
            )

            print(
                "📲 发送 Telegram"
            )

            if send_telegram(
                message
            ):

                changed_count += 1

        else:

            print(
                "价格及商品信息没有变化，不推送"
            )

        # -------------------------
        # 保存历史
        # -------------------------

        history[
            product_id
        ] = current

        checked_count += 1

    # -------------------------
    # 保存
    # -------------------------

    save_history(
        history
    )

    print()

    print(
        "=" * 60
    )

    print(
        f"检查完成：{checked_count} 个商品"
    )

    print(
        f"发送提醒：{changed_count} 条"
    )

    print(
        "=" * 60
    )


# =========================
# 启动
# =========================

if __name__ == "__main__":

    main()
