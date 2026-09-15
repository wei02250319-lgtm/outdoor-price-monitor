import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

print("开始测试 Telegram")

if not TOKEN:
    print("错误：TELEGRAM_BOT_TOKEN 没有读取到")
    raise SystemExit(1)

if not CHAT_ID:
    print("错误：TELEGRAM_CHAT_ID 没有读取到")
    raise SystemExit(1)

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

data = {
    "chat_id": CHAT_ID,
    "text": "✅ REI户外价格监控：Telegram 推送测试成功！"
}

try:
    r = requests.post(
        url,
        json=data,
        timeout=15
    )

    print("Telegram HTTP状态码：", r.status_code)
    print("Telegram返回：", r.text)

    if r.status_code != 200:
        raise SystemExit(1)

    print("Telegram测试成功！")

except Exception as e:
    print("Telegram测试失败：", type(e).__name__, e)
    raise SystemExit(1)
