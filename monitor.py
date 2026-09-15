import os
import requests
from bs4 import BeautifulSoup

TOKEN = os.getenv("CRAWLBASE_JS_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

REI_URL = "https://www.rei.com/b/arcteryx/c/all"


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    r = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text
        },
        timeout=15
    )

    print("Telegram:", r.status_code)


def main():

    print("================================")
    print("REI + Crawlbase 测试")
    print("================================")

    if not TOKEN:
        print("❌ 没有读取到 Crawlbase Token")
        return

    print("正在通过 Crawlbase 访问 REI...")

    api_url = "https://api.crawlbase.com/"

    params = {
        "token": TOKEN,
        "url": REI_URL,
        "javascript": "true"
    }

    try:
        r = requests.get(
            api_url,
            params=params,
            timeout=60
        )

        print("Crawlbase HTTP:", r.status_code)
        print("返回数据长度:", len(r.text))

        if r.status_code != 200:
            print("❌ Crawlbase 请求失败")
            print(r.text[:500])
            return

        soup = BeautifulSoup(r.text, "lxml")

        title = soup.title.get_text(strip=True) if soup.title else "未找到网页标题"

        print("网页标题:", title)

        message = (
            "🧪 REI监控测试\n\n"
            "品牌：Arc'teryx\n"
            "方式：Crawlbase\n"
            f"HTTP：{r.status_code}\n"
            f"页面长度：{len(r.text)}\n\n"
            "✅ REI 页面获取成功！"
        )

        send_telegram(message)

        print("✅ 测试完成，Telegram 已发送")

    except Exception as e:
        print("❌ 测试失败")
        print(type(e).__name__, e)


if __name__ == "__main__":
    main()
