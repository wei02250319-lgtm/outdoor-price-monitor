好，给你。这是完整测试版 monitor.py，先只测试 REI 始祖鸟 + Crawlbase + Telegram，确认整个链路跑通后，再扩展到巴塔哥尼亚、北面和各国官网。
把下面全部复制到你刚才已经清空的 monitor.py：
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# =========================
# 配置
# =========================

CRAWLBASE_TOKEN = os.getenv("CRAWLBASE_JS_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DATA_FILE = "data/prices.json"

# 当前阶段：只测试 REI 始祖鸟
REI_URL = "https://www.rei.com/b/arcteryx/c/all"

# 第一次只测试 5 个商品
MAX_PRODUCTS = 5


# =========================
# Telegram 推送
# =========================

def send_telegram(text):
    print("正在测试 Telegram...")

    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("❌ Telegram 配置不完整")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True
            },
            timeout=20
        )

        print("Telegram 状态:", response.status_code)

        if response.status_code == 200:
            print("✅ Telegram 推送成功")
            return True

        print("Telegram 返回:", response.text[:500])
        return False

    except Exception as e:
        print("❌ Telegram 发送失败:", type(e).__name__, e)
        return False


# =========================
# Crawlbase 获取网页
# =========================

def fetch_page(url):
    print("开始请求 Crawlbase...")
    print("目标网页:", url)

    if not CRAWLBASE_TOKEN:
        print("❌ 没有读取到 CRAWLBASE_JS_TOKEN")
        return None

    api_url = "https://api.crawlbase.com/"

    params = {
        "token": CRAWLBASE_TOKEN,
        "url": url,
        "javascript": "true",
        "page_wait": "3000"
    }

    try:
        response = requests.get(
            api_url,
            params=params,
            timeout=90
        )

        print("Crawlbase 状态:", response.status_code)
        print("页面长度:", len(response.text))

        if response.status_code != 200:
            print("Crawlbase 返回:")
            print(response.text[:500])
            return None

        print("✅ Crawlbase 获取网页成功")
        return response.text

    except Exception as e:
        print(
            "❌ Crawlbase 获取失败:",
            type(e).__name__,
            e
        )
        return None


# =========================
# 价格转换
# =========================

def price_to_number(value):
    if not value:
        return None

    value = str(value)

    value = re.sub(r"[^\d.,]", "", value)

    if not value:
        return None

    if "," in value and "." in value:
        value = value.replace(",", "")

    elif "," in value:
        parts = value.split(",")

        if len(parts[-1]) == 2:
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")

    try:
        return float(value)

    except Exception:
        return None


# =========================
# JSON-LD 商品解析
# =========================

def extract_jsonld_products(soup):

    products = []

    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    print("发现 JSON-LD 标签:", len(scripts))

    for script in scripts:

        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)

        except Exception:
            continue

        items = []

        if isinstance(data, list):

            items = data

        elif isinstance(data, dict):

            if "@graph" in data:
                items = data["@graph"]

            else:
                items = [data]

        for item in items:

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")

            if isinstance(item_type, list):

                is_product = "Product" in item_type

            else:

                is_product = item_type == "Product"

            if not is_product:
                continue

            name = item.get("name")

            if not name:
                continue

            offers = item.get("offers")

            if isinstance(offers, list):

                offers = offers[0] if offers else {}

            if not isinstance(offers, dict):

                offers = {}

            price = offers.get("price")

            currency = offers.get("priceCurrency")

            url = item.get("url")

            if not url:
                url = offers.get("url")

            image = item.get("image")

            if isinstance(image, list):

                image = image[0] if image else None

            product = {
                "name": str(name).strip(),
                "price": price_to_number(price),
                "currency": currency or "USD",
                "url": url,
                "image": image
            }

            products.append(product)

    return products


# =========================
# 从页面链接寻找商品
# =========================

def extract_product_links(soup):

    results = []

    for a in soup.find_all("a", href=True):

        href = a.get("href")

        if not href:
            continue

        text = a.get_text(" ", strip=True)

        if not text:
            continue

        full_url = urljoin(
            "https://www.rei.com",
            href
        )

        if "/product/" not in full_url:
            continue

        results.append({
            "name": text,
            "url": full_url
        })

    return results


# =========================
# 去重
# =========================

def deduplicate_products(products):

    result = []
    seen = set()

    for product in products:

        url = product.get("url")

        if not url:
            continue

        if url in seen:
            continue

        seen.add(url)
        result.append(product)

    return result


# =========================
# 读取历史价格
# =========================

def load_data():

    if not os.path.exists(DATA_FILE):

        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {
            "products": {},
            "exchange_rates": {},
            "last_update": None
        }


# =========================
# 保存历史价格
# =========================

def save_data(data):

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
# 主程序
# =========================

def main():

    print("================================")
    print("🏔️ REI 始祖鸟价格监控")
    print("================================")

    print("Python 程序已经正常启动")

    # 检查环境变量
    print("--------------------------------")
    print("检查配置...")

    if TELEGRAM_TOKEN:
        print("✅ TELEGRAM_BOT_TOKEN 已读取")

    else:
        print("❌ TELEGRAM_BOT_TOKEN 未读取")

    if CHAT_ID:
        print("✅ TELEGRAM_CHAT_ID 已读取")

    else:
        print("❌ TELEGRAM_CHAT_ID 未读取")

    if CRAWLBASE_TOKEN:
        print("✅ CRAWLBASE_JS_TOKEN 已读取")

    else:
        print("❌ CRAWLBASE_JS_TOKEN 未读取")

    print("--------------------------------")

    # 获取 REI 页面
    html = fetch_page(REI_URL)

    if not html:

        print("❌ 没有获取到 REI 页面")

        send_telegram(
            "⚠️ REI 始祖鸟监控测试\n\n"
            "Crawlbase 没有成功获取 REI 页面。\n"
            "请检查 Crawlbase 配置。"
        )

        return

    # 解析网页
    print("开始解析 REI 页面...")

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    title = (
        soup.title.get_text(strip=True)
        if soup.title
        else "未找到网页标题"
    )

    print("网页标题:", title)

    # JSON-LD 商品
    products = extract_jsonld_products(soup)

    print(
        "JSON-LD 商品数量:",
        len(products)
    )

    # 如果 JSON-LD 没有商品
    if not products:

        print("JSON-LD 没找到商品")
        print("尝试从页面链接寻找商品...")

        products = extract_product_links(soup)

        print(
            "商品链接数量:",
            len(products)
        )

    # 去重
    products = deduplicate_products(products)

    # 只取前 5 个
    products = products[:MAX_PRODUCTS]

    print("--------------------------------")

    # 没找到商品
    if not products:

        print("❌ 没有解析到商品")

        send_telegram(
            "⚠️ REI 始祖鸟监控测试\n\n"
            "网页可以访问，但是目前没有成功解析出商品。\n\n"
            "下一步需要调整 REI 商品解析方式。"
        )

        return

    # 读取历史数据
    data = load_data()

    if "products" not in data:

        data["products"] = {}

    # Telegram 消息
    telegram_lines = [
        "🏔️ REI 始祖鸟价格监控测试",
        "",
        f"本次发现商品：{len(products)} 个",
        ""
    ]

    # 输出商品
    for index, product in enumerate(
        products,
        start=1
    ):

        name = product.get(
            "name",
            "未知商品"
        )

        price = product.get("price")

        currency = product.get(
            "currency",
            "USD"
        )

        url = product.get("url")

        print(
            f"[{index}] {name}"
        )

        print(
            "价格:",
            price
        )

        print(
            "币种:",
            currency
        )

        print(
            "链接:",
            url
        )

        print()

        # Telegram
        telegram_lines.append(
            f"{index}. {name}"
        )

        if price is not None:

            telegram_lines.append(
                f"价格：{currency} {price:.2f}"
            )

        else:

            telegram_lines.append(
                "价格：暂未解析到"
            )

        if url:

            telegram_lines.append(
                f"链接：{url}"
            )

        telegram_lines.append("")

        # 保存历史
        if url:

            old = data["products"].get(
                url,
                {}
            )

            data["products"][url] = {
                "name": name,
                "price": price,
                "currency": currency,
                "last_price": old.get("price"),
                "url": url
            }

    # 保存
    save_data(data)

    print("✅ 商品历史数据已经保存")

    telegram_lines.append(
        "✅ Crawlbase + GitHub Actions 测试完成"
    )

    # Telegram
    send_telegram(
        "\n".join(telegram_lines)
    )

    print("================================")
    print("✅ 本次监控完成")
    print("================================")


# =========================
# 启动程序
# =========================

if __name__ == "__main__":

    main()
