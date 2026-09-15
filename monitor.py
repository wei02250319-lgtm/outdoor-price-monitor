import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# =========================
# 基础配置
# =========================

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

HISTORY_FILE = "data/prices.json"

USD_TO_CNY = 7.15

# 每轮只抓 3 个商品，30 分钟轮询一次
DETAILS_PER_RUN = 3

# 只有降价 >=20% 才推送
MIN_DISCOUNT = 20

# =========================
# 固定监控商品
# =========================

WATCHLIST = [
    {
        "name": "Arc'teryx Gamma MX Hoody - Men's",
        "url": "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens",
        "brand": "Arc'teryx",
    },
    {
        "name": "Arc'teryx Gamma Jacket - Men's",
        "url": "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens",
        "brand": "Arc'teryx",
    },
    {
        "name": "Arc'teryx Gamma Pants - Men's",
        "url": "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens",
        "brand": "Arc'teryx",
    },
    {
        "name": "Patagonia R2 TechFace Jacket - Men's",
        "url": "https://www.rei.com/product/222148/patagonia-r2-techface-jacket-mens",
        "brand": "Patagonia",
    },
    {
        "name": "Patagonia R2 TechFace Hoody - Men's",
        "url": "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
        "brand": "Patagonia",
    },
    {
        "name": "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "url": "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
        "brand": "Patagonia",
    },
    {
        "name": "Arc'teryx Atom Insulated Jacket - Men's",
        "url": "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
        "brand": "Arc'teryx",
    },
    {
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
        "brand": "Arc'teryx",
    },
]

# 刚才错误产生的历史价格
# 如果历史里存在这些异常低价，就自动删除
BAD_BASELINES = {
    "https://www.rei.com/product/235146/arcteryx-gamma-mx-hoody-mens": 30.0,
    "https://www.rei.com/product/C01007/arcteryx-gamma-jacket-mens": 28.0,
    "https://www.rei.com/product/242853/arcteryx-gamma-pants-mens": 20.0,
}

# =========================
# 工具
# =========================

def ensure_history_dir():
    os.makedirs("data", exist_ok=True)


def load_history():
    ensure_history_dir()

    if not os.path.exists(HISTORY_FILE):
        return {}

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history):
    ensure_history_dir()

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def money(value):
    if value is None:
        return None

    try:
        value = str(value)
        value = value.replace(",", "")
        value = value.replace("$", "")
        value = value.strip()

        number = float(value)

        if number <= 0:
            return None

        return round(number, 2)

    except Exception:
        return None


# =========================
# Firecrawl
# =========================

def firecrawl_scrape(url):
    endpoint = "https://api.firecrawl.dev/v2/scrape"

    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "url": url,
        "formats": [
            "markdown",
            "rawHtml"
        ],
        "waitFor": 3000,
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=90,
        )

        print(f"Firecrawl: {response.status_code}")

        if response.status_code != 200:
            print(response.text[:1000])
            return None

        data = response.json()

        return data

    except Exception as e:
        print("Firecrawl错误:", e)
        return None


# =========================
# 精确识别 REI 折扣
# =========================

def parse_compared_to(text):
    """
    重点识别 REI 页面类似：

    $103.83 Compared to $209.00 Save 50%

    或：

    $196.93 Compared to $280.00
    """

    text = clean_text(text)

    patterns = [
        r"\$\s*([\d,]+(?:\.\d+)?)\s+Compared\s+to\s+\$?\s*([\d,]+(?:\.\d+)?)",
        r"\$\s*([\d,]+(?:\.\d+)?)\s+compared\s+to\s+\$?\s*([\d,]+(?:\.\d+)?)",
        r"\$\s*([\d,]+(?:\.\d+)?)\s+Compared\s+to\s+\$?\s*([\d,]+(?:\.\d+)?)",
    ]

    results = []

    for pattern in patterns:

        for match in re.finditer(pattern, text):

            current = money(match.group(1))
            original = money(match.group(2))

            if not current or not original:
                continue

            if current >= original:
                continue

            discount = round(
                (original - current) / original * 100
            )

            # 只接受合理折扣
            if discount < 5:
                continue

            # 极端异常值过滤
            if current < original * 0.15:
                continue

            results.append({
                "current": current,
                "original": original,
                "discount": discount,
                "source": "Compared to",
            })

    return results


# =========================
# Save XX% 识别
# =========================

def parse_save_discount(text):
    """
    例如：

    $103.83 Compared to $209.00 Save 50%

    只在 Save XX% 附近寻找价格。
    不扫描整页所有美元数字。
    """

    text = clean_text(text)

    results = []

    for match in re.finditer(
        r"Save\s+(\d{1,2})\s*%",
        text,
        flags=re.I,
    ):

        discount = int(match.group(1))

        if discount < 5 or discount > 90:
            continue

        start = max(0, match.start() - 250)
        end = min(len(text), match.end() + 100)

        window = text[start:end]

        # 优先找 Compared to
        compared = parse_compared_to(window)

        for item in compared:

            # 如果页面明确写了 Save XX%，
            # 以页面折扣为准
            item["discount"] = discount

            results.append(item)

    return results


# =========================
# JSON 数据识别
# =========================

def parse_json_prices(raw_html):
    """
    只从明确的价格字段寻找价格。
    不再把网页中的任意 $数字 当成售价。
    """

    results = []

    if not raw_html:
        return results

    soup = BeautifulSoup(raw_html, "lxml")

    scripts = soup.find_all("script")

    for script in scripts:

        text = script.string or script.get_text()

        if not text:
            continue

        lower = text.lower()

        # 必须包含价格相关字段
        if not any(
            key in lower
            for key in [
                "saleprice",
                "sale_price",
                "currentprice",
                "current_price",
                "regularprice",
                "originalprice",
                "listprice",
            ]
        ):
            continue

        # 当前价
        current_matches = re.findall(
            r'"(?:salePrice|sale_price|currentPrice|current_price)"\s*:\s*"?\$?([\d,.]+)',
            text,
            flags=re.I,
        )

        # 原价
        original_matches = re.findall(
            r'"(?:regularPrice|regular_price|originalPrice|original_price|listPrice|list_price)"\s*:\s*"?\$?([\d,.]+)',
            text,
            flags=re.I,
        )

        currents = [
            money(x)
            for x in current_matches
            if money(x)
        ]

        originals = [
            money(x)
            for x in original_matches
            if money(x)
        ]

        for current in currents:

            for original in originals:

                if current >= original:
                    continue

                discount = round(
                    (original - current) / original * 100
                )

                if discount < 5:
                    continue

                # 极端异常价格直接忽略
                if current < original * 0.15:
                    continue

                results.append({
                    "current": current,
                    "original": original,
                    "discount": discount,
                    "source": "JSON",
                })

    return results


# =========================
# 商品名称
# =========================

def parse_product_name(data, fallback):

    try:
        markdown = data.get("data", {}).get("markdown", "")

        text = clean_text(markdown)

        patterns = [
            r"Arc'teryx\s+.+?-\s+Men's",
            r"Patagonia\s+.+?-\s+Men's",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                flags=re.I,
            )

            if match:
                name = match.group(0).strip()

                if len(name) < 120:
                    return name

    except Exception:
        pass

    return fallback


# =========================
# 提取价格
# =========================

def parse_product(data, watch):

    markdown = data.get("data", {}).get(
        "markdown",
        ""
    )

    raw_html = data.get("data", {}).get(
        "rawHtml",
        ""
    )

    markdown = clean_text(markdown)

    product_name = parse_product_name(
        data,
        watch["name"],
    )

    candidates = []

    # 1. 最可靠：Compared to
    candidates.extend(
        parse_compared_to(markdown)
    )

    candidates.extend(
        parse_compared_to(raw_html)
    )

    # 2. Save XX%
    candidates.extend(
        parse_save_discount(markdown)
    )

    # 3. JSON
    candidates.extend(
        parse_json_prices(raw_html)
    )

    # 去重
    unique = {}

    for item in candidates:

        current = item["current"]
        original = item["original"]

        key = (
            round(current, 2),
            round(original, 2),
        )

        if key not in unique:
            unique[key] = item

    candidates = list(unique.values())

    # =========================
    # 最终安全过滤
    # =========================

    safe = []

    for item in candidates:

        current = item["current"]
        original = item["original"]

        if not current or not original:
            continue

        if current >= original:
            continue

        discount = round(
            (original - current) / original * 100
        )

        # 用户要求至少20%才关注
        if discount < MIN_DISCOUNT:
            continue

        # 防止网页数字污染
        if current < original * 0.15:
            print(
                f"忽略异常价格: ${original:.2f} -> ${current:.2f}"
            )
            continue

        item["discount"] = discount

        safe.append(item)

    # 从高折扣开始
    safe.sort(
        key=lambda x: x["discount"],
        reverse=True,
    )

    return {
        "name": product_name,
        "url": watch["url"],
        "brand": watch["brand"],
        "discounts": safe,
    }


# =========================
# Telegram
# =========================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("没有 TELEGRAM_BOT_TOKEN")
        return False

    if not TELEGRAM_CHAT_ID:
        print("没有 TELEGRAM_CHAT_ID")
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

        response = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        print(
            "Telegram:",
            response.status_code,
        )

        return response.status_code == 200

    except Exception as e:

        print(
            "Telegram错误:",
            e,
        )

        return False


# =========================
# 生成推送
# =========================

def make_message(
    product,
    discount,
    old_price=None,
):

    current = discount["current"]
    original = discount["original"]
    percent = discount["discount"]

    cny = round(
        current * USD_TO_CNY,
        2,
    )

    if percent >= 50:
        icon = "🚨"
    elif percent >= 30:
        icon = "🔥"
    else:
        icon = "🏷️"

    message = (
        f"{icon} {percent}% OFF｜"
        f"{product['name']}\n"
        f"🏷️ 原价 ${original:.2f} "
        f"≈ ¥{original * USD_TO_CNY:.0f}\n"
        f"💰 现价 ${current:.2f} "
        f"≈ ¥{cny:.0f}\n"
    )

    if old_price is not None:
        message += (
            f"📉 上次价格 ${old_price:.2f} "
            f"→ ${current:.2f}\n"
        )

    message += (
        "\n"
        f"{product['url']}"
    )

    return message


# =========================
# 主程序
# =========================

def main():

    if not FIRECRAWL_API_KEY:
        print("❌ 没有 FIRECRAWL_API_KEY")
        return

    history = load_history()

    # =========================
    # 清理刚才产生的错误历史价格
    # =========================

    for url, bad_price in BAD_BASELINES.items():

        if url in history:

            try:
                old = float(history[url])

                if old <= bad_price:
                    print(
                        f"清除错误历史价格: "
                        f"{url} -> ${old:.2f}"
                    )

                    del history[url]

            except Exception:
                del history[url]

    save_history(history)

    # =========================
    # 轮询
    # =========================

    state_file = "data/rotation.json"

    rotation = 0

    if os.path.exists(state_file):

        try:

            with open(
                state_file,
                "r",
                encoding="utf-8",
            ) as f:

                obj = json.load(f)

                rotation = int(
                    obj.get("position", 0)
                )

        except Exception:
            rotation = 0

    total = len(WATCHLIST)

    start = rotation % total

    selected = []

    for i in range(
        min(DETAILS_PER_RUN, total)
    ):

        index = (
            start + i
        ) % total

        selected.append(
            WATCHLIST[index]
        )

    next_position = (
        start + len(selected)
    ) % total

    print(
        f"轮询位置: "
        f"{start} -> {next_position}"
    )

    print(
        f"本轮抓取详情: "
        f"{len(selected)}"
    )

    os.makedirs(
        "data",
        exist_ok=True,
    )

    with open(
        state_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "position": next_position
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # =========================
    # 抓取
    # =========================

    for index, watch in enumerate(
        selected,
        start=1,
    ):

        print()
        print(
            f"[{index}/{len(selected)}] "
            f"{watch['name']}"
        )

        data = firecrawl_scrape(
            watch["url"]
        )

        if not data:

            print("抓取失败")

            continue

        product = parse_product(
            data,
            watch,
        )

        print(
            f"商品名称: "
            f"{product['name']}"
        )

        discounts = product[
            "discounts"
        ]

        if not discounts:

            print(
                "没有发现可靠折扣"
            )

            # 9秒后再抓下一页
            if index < len(selected):
                time.sleep(9)

            continue

        print(
            f"发现可靠折扣层级: "
            f"{len(discounts)}"
        )

        # 目前用最低可靠售价作为商品历史基准
        current_price = min(
            x["current"]
            for x in discounts
        )

        print(
            f"最低可靠售价: "
            f"${current_price:.2f}"
        )

        old_price = history.get(
            watch["url"]
        )

        if old_price is not None:

            try:
                old_price = float(
                    old_price
                )
            except Exception:
                old_price = None

        # =========================
        # 第一次发现
        # =========================

        if old_price is None:

            print(
                "第一次记录价格，"
                "建立基准，不推送"
            )

            history[
                watch["url"]
            ] = current_price

            save_history(history)

        # =========================
        # 降价
        # =========================

        elif current_price < old_price:

            drop = (
                old_price
                - current_price
            )

            drop_percent = (
                drop / old_price * 100
            )

            print(
                f"价格下降: "
                f"${old_price:.2f}"
                f" -> "
                f"${current_price:.2f}"
                f" "
                f"({drop_percent:.1f}%)"
            )

            # 只推送降价
            # 这里不要求降价本身20%，
            # 因为商品本身只要是20%+折扣，
            # 且价格确实下降，就推送
            for discount in discounts:

                if (
                    discount["discount"]
                    >= MIN_DISCOUNT
                ):

                    message = make_message(
                        product,
                        discount,
                        old_price,
                    )

                    print(
                        "发送 Telegram..."
                    )

                    send_telegram(
                        message
                    )

            history[
                watch["url"]
            ] = current_price

            save_history(history)

        # =========================
        # 价格不变
        # =========================

        elif current_price == old_price:

            print(
                f"价格没有下降："
                f"${current_price:.2f}"
                f" -> "
                f"${old_price:.2f}"
            )

        # =========================
        # 涨价
        # =========================

        else:

            print(
                f"价格上涨："
                f"${old_price:.2f}"
                f" -> "
                f"${current_price:.2f}"
            )

            # 用户要求：
            # 涨价不推送
            #
            # 但更新基准
            history[
                watch["url"]
            ] = current_price

            save_history(history)

        # 防止 Firecrawl 请求过快
        if index < len(selected):

            print(
                "等待 9 秒..."
            )

            time.sleep(9)

    print()
    print("本轮完成")


if __name__ == "__main__":
    main()
