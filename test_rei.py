import os
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("=" * 50)
print("Telegram 推送测试")
print("=" * 50)

if not TOKEN:
    print("❌ 没找到 TELEGRAM_BOT_TOKEN")
    raise SystemExit

if not CHAT_ID:
    print("❌ 没找到 TELEGRAM_CHAT_ID")
    raise SystemExit

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

data = {
    "chat_id": CHAT_ID,
    "text": "✅ REI价格监控测试成功！\n\nTelegram 推送已经正常连接。"
}

r = requests.post(url, data=data, timeout=30)

print("Telegram 状态:", r.status_code)
print("返回:", r.text[:500])

if r.status_code == 200:
    print("✅ Telegram 推送成功")
else:
    print("❌ Telegram 推送失败")

print("=" * 50)
