import os
import re
import json
import time
import html
import requests
from datetime import datetime, timezone

FIRECRAWL_API_KEY = os.environ["FIRECRAWL_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"

USD_TO_CNY = 7.15

DETAIL_DELAY = 9
DETAILS_PER_RUN = 3

HISTORY_FILE = "data/prices.json"


WATCHLIST = [
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
        "name": "Patagonia R2 TechFace Hoody - Men's",
        "url": "https://www.rei.com/product/240424/patagonia-r2-techface-hoody-mens",
    },
    {
        "name": "Patagonia Capilene Cool Daily Graphic Hoody - Men's",
        "url": "https://www.rei.com/product/C00900/patagonia-capilene-cool-daily-graphic-hoody-mens",
    },
    {
        "name": "Arc'teryx Atom Insulated Jacket - Men's",
        "url": "https://www.rei.com/product/243256/arcteryx-atom-insulated-jacket-mens",
    },
    {
        "name": "Arc'teryx Atom Insulated Hoody - Men's",
        "url": "https://www.rei.com/product/243175/arcteryx-atom-insulated-hoody-mens",
    },
]


def firecrawl(url):
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
        "onlyMainContent": False,
    }

    try:
        r = requests.post(
            FIRECRAWL_URL,
            headers=headers,
            json=payload,
            timeout=90,
        )

        print("Firecrawl:", r.status_code, url)

        if r.status_code != 200:
            print(r.text[:1000])
            return {}

        data = r.json()

        if data.get("success") is False:
            print(data)
            return {}

        return data.get("data", data)

    except Exception as e:
        print("Firecrawl异常:", e)
        return {}


def clean_text(s):
    if not s:
        return ""

    s = html.unescape(s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\s+", " ", s)

    return s.strip()


def money_values(text):
    if not text:
        return []

    values = []

    for m in re.findall(r"\$\s*([0-9]{1,5}(?:\.[0-9]{1,2})?)", text):
        try:
            v = float(m)
            if 1 <= v <= 5000:
                values.append(v)
        except:
            pass

    return values


def percent_values(text):
    if not text:
        return []

    values = []

    for m in re.findall(r"([0-9]{1,3})\s*%", text):
        try:
            p = int(m)
            if 1 <= p <= 95:
                values.append(p)
        except:
            pass

    return values


def recursive_objects(obj):
    if isinstance(obj, dict):
        yield obj

        for v in obj.values():
            yield from recursive_objects(v)

    elif isinstance(obj, list):
        for v in obj:
            yield from recursive_objects(v)


def find_price_fields(obj):
    """
    从 REI 嵌入 JSON 中寻找各种价格字段。
    """

    candidates = []

    for item in recursive_objects(obj):

        if not isinstance(item, dict):
            continue

        keys = {
            str(k).lower(): v
            for k, v in item.items()
        }

        current = None
        original = None

        current_keys = [
            "saleprice",
            "sale_price",
            "currentprice",
            "current_price",
            "sellingprice",
            "selling_price",
            "offerprice",
            "offer_price",
            "finalprice",
            "final_price",
        ]

        original_keys = [
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
        ]

        for k in current_keys:
            if k in keys:
                try:
                    current = float(
                        str(keys[k]).replace("$", "").replace(",", "")
                    )
                    break
                except:
                    pass

        for k in original_keys:
            if k in keys:
                try:
                    original = float(
                        str(keys[k]).replace("$", "").replace(",", "")
                    )
                    break
                except:
                    pass

        if current and original and original > current:
            candidates.append(
                {
                    "current": current,
                    "original": original,
                }
            )

    return candidates


def extract_json_scripts(raw_html):
    results = []

    if not raw_html:
        return results

    patterns = [
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        r'<script[^>]*>(.*?)</script>',
    ]

    for pattern in patterns:
        for m in re.findall(
            pattern,
            raw_html,
            flags=re.I | re.S,
        ):
            text = html.unescape(m).strip()

            if not text:
                continue

            if len(text) > 500000:
                continue

            try:
                obj = json.loads(text)
                results.append(obj)
            except:
                continue

    return results


def parse_prices(markdown, raw_html):
    candidates = []

    # ------------------------------------------------
    # 1. JSON / 页面脚本
    # ------------------------------------------------

    for obj in extract_json_scripts(raw_html):

        candidates.extend(
            find_price_fields(obj)
        )

    # ------------------------------------------------
    # 2. JSON-LD
    # ------------------------------------------------

    for obj in extract_json_scripts(raw_html):

        for item in recursive_objects(obj):

            if not isinstance(item, dict):
                continue

            offers = item.get("offers")

            if not offers:
                continue

            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                continue

            for offer in offers:

                if not isinstance(offer, dict):
                    continue

                price = offer.get("price")

                if price is None:
                    continue

                try:
                    current = float(
                        str(price)
                        .replace("$", "")
                        .replace(",", "")
                    )
                except:
                    continue

                if current > 0:
                    candidates.append(
                        {
                            "current": current,
                            "original": None,
                        }
                    )

    # ------------------------------------------------
    # 3. Markdown 文字
    # ------------------------------------------------

    text = clean_text(markdown)

    # Compared to $xxx
    compared = re.findall(
        r"(?:Compared\s+to|Was|Regular(?:ly)?)\s*\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        text,
        flags=re.I,
    )

    # Save xx%
    discounts = percent_values(text)

    # 所有美元价格
    prices = money_values(text)

    for m in compared:
        try:
            original = float(m.replace(",", ""))

            for current in prices:
                if current < original:
                    candidates.append(
                        {
                            "current": current,
                            "original": original,
                        }
                    )
        except:
            pass

    # ------------------------------------------------
    # 4. 如果页面明确写 Save xx%，反推折后价格
    # ------------------------------------------------

    if discounts and prices:

        for discount in discounts:

            for original in prices:

                if original <= 0:
                    continue

                current = round(
                    original * (1 - discount / 100),
                    2,
                )

                for actual in prices:

                    if abs(actual - current) <= 2:

                        candidates.append(
                            {
                                "current": actual,
                                "original": original,
                            }
                        )

    # ------------------------------------------------
    # 5. 去重
    # ------------------------------------------------

    unique = {}

    for x in candidates:

        current = x.get("current")
        original = x.get("original")

        if not current:
            continue

        if current <= 0:
            continue

        if original is None:
            continue

        if original <= current:
            continue

        key = (
            round(current, 2),
            round(original, 2),
        )

        unique[key] = {
            "current": round(current, 2),
            "original": round(original, 2),
        }

    return list(unique.values())


def calculate_discount(original, current):

    if not original or not current:
        return 0

    if original <= current:
        return 0

    return round(
        (original - current) / original * 100
    )


def extract_product_name(markdown):

    text = clean_text(markdown)

    patterns = [
        r"#\s*(Arc['’]teryx.*?Men['’]s)",
        r"#\s*(Patagonia.*?Men['’]s)",
        r"#\s*(The North Face.*?Men['’]s)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if m:
            return clean_text(m.group(1))

    return ""


def extract_variants(markdown, raw_html):

    """
    尝试提取颜色/尺码。
    即使当前 REI 页面没有完整 variant JSON，
    也不会把所有颜色错误复制给所有价格层级。
    """

    variants = []

    text = clean_text(markdown)

    colors = []

    color_patterns = [
        r"Color\s*[:：]\s*([A-Za-z0-9 /&'_-]{2,40})",
        r"Colour\s*[:：]\s*([A-Za-z0-9 /&'_-]{2,40})",
    ]

    for pattern in color_patterns:

        for m in re.findall(
            pattern,
            text,
            flags=re.I,
        ):

            value = clean_text(m)

            if value and value not in colors:
                colors.append(value)

    sizes = []

    for size in re.findall(
        r"\b(XXS|XS|S|M|L|XL|XXL|XXXL)\b",
        text,
        flags=re.I,
    ):

        size = size.upper()

        if size not in sizes:
            sizes.append(size)

    if colors:

        for color in colors:

            variants.append(
                {
                    "color": color,
                    "sizes": sizes,
                }
            )

    return variants


def build_message(product, price_info, variants):

    current = price_info["current"]
    original = price_info["original"]

    discount = calculate_discount(
        original,
        current,
    )

    current_cny = round(
        current * USD_TO_CNY,
        2,
    )

    original_cny = round(
        original * USD_TO_CNY,
        2,
    )

    lines = []

    lines.append(
        f"🔥 {discount}% OFF｜{product['name']}"
    )

    lines.append(
        f"🏷️ 原价 ${original:.2f} / ¥{original_cny:.0f}"
    )

    lines.append(
        f"💰 现价 ${current:.2f} / ¥{current_cny:.0f}"
    )

    if variants:

        lines.append("")

        color_line = "颜色       "
        size_line = "尺码       "

        for v in variants:

            color = v.get("color", "")

            color_line += f"{color:<10}"

            sizes = v.get("sizes", [])

            if sizes:
                size_text = " ".join(sizes)
            else:
                size_text = "未知"

            size_line += f"{size_text:<10}"

        lines.append(color_line)
        lines.append(size_line)

    lines.append("")
    lines.append(product["url"])

    return "\n".join(lines)


def send_telegram(text):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }

    try:

        r = requests.post(
            url,
            json=payload,
            timeout=30,
        )

        print(
            "Telegram:",
            r.status_code,
            r.text[:500],
        )

        return r.status_code == 200

    except Exception as e:

        print("Telegram异常:", e)
        return False


def load_history():

    if not os.path.exists(HISTORY_FILE):
        return {}

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(f)

    except:

        return {}


def save_history(history):

    os.makedirs(
        os.path.dirname(HISTORY_FILE),
        exist_ok=True,
    )

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2,
        )


def get_rotation():

    history = load_history()

    value = history.get(
        "_rotation_position",
        0,
    )

    try:
        return int(value)
    except:
        return 0


def set_rotation(value):

    history = load_history()

    history["_rotation_position"] = value

    save_history(history)


def process_product(product, history):

    print(product["url"])

    data = firecrawl(
        product["url"]
    )

    if not data:
        print("抓取失败")
        return

    markdown = data.get(
        "markdown",
        "",
    )

    raw_html = data.get(
        "rawHtml",
        "",
    )

    name = extract_product_name(
        markdown
    )

    if not name:
        name = product["name"]

    print(
        "商品名称:",
        name,
    )

    prices = parse_prices(
        markdown,
        raw_html,
    )

    print(
        "发现折扣价格层级:",
        len(prices),
    )

    if not prices:

        print(
            "⚠️ 页面抓取成功，但价格解析器没有识别到折扣。"
        )

        return

    variants = extract_variants(
        markdown,
        raw_html,
    )

    # 最低价格
    prices.sort(
        key=lambda x: x["current"]
    )

    lowest = prices[0]

    current = lowest["current"]
    original = lowest["original"]

    discount = calculate_discount(
        original,
        current,
    )

    print(
        f"原价 ${original:.2f}"
        f" -> 现价 ${current:.2f}"
        f" ({discount}%)"
    )

    key = product["url"]

    old = history.get(key)

    # 第一次建立基准，不推送
    if old is None:

        history[key] = {
            "price": current,
            "original": original,
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        print(
            "首次发现，建立价格基准。"
        )

        return

    old_price = float(
        old.get(
            "price",
            current,
        )
    )

    # 只有降价才推送
    if current < old_price:

        print(
            f"🔥 发现降价："
            f"${old_price:.2f}"
            f" -> "
            f"${current:.2f}"
        )

        if discount >= 20:

            message = build_message(
                {
                    **product,
                    "name": name,
                },
                lowest,
                variants,
            )

            send_telegram(
                message
            )

        else:

            print(
                f"降价了，但折扣只有 {discount}%，"
                f"低于20%，不推送。"
            )

    else:

        print(
            f"价格没有下降："
            f"${old_price:.2f}"
            f" -> ${current:.2f}"
        )

    history[key] = {
        "price": current,
        "original": original,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


def main():

    print("")
    print("======================================")
    print("REI Outdoor Price Monitor")
    print("8个重点商品｜轮询｜只推送降价")
    print("======================================")
    print("")

    history = load_history()

    # 删除旧的 C1 历史记录
    for key in list(history.keys()):

        if "c1" in key.lower():

            del history[key]

    position = get_rotation()

    total = len(WATCHLIST)

    start = position % total

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
        f"轮询位置: {start} -> {next_position}"
    )

    print(
        f"本轮抓取详情: {len(selected)}"
    )

    print("")

    for i, product in enumerate(
        selected,
        1,
    ):

        print(
            f"[{i}/{len(selected)}]"
        )

        process_product(
            product,
            history,
        )

        if i < len(selected):

            print(
                f"等待 {DETAIL_DELAY} 秒..."
            )

            time.sleep(
                DETAIL_DELAY
            )

    history["_rotation_position"] = (
        next_position
    )

    save_history(history)

    print("")
    print(
        "本轮价格历史已保存。"
    )

    print("======================================")
    print("运行完成")
    print("======================================")


if __name__ == "__main__":
    main()
