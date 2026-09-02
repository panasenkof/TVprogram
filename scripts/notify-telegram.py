#!/usr/bin/env python3
"""Send a Telegram message. Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from env."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not token or not chat_id:
    print("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы — уведомление пропущено", file=sys.stderr)
    sys.exit(1)

text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
text = text.strip()
if not text:
    print("пустой текст уведомления", file=sys.stderr)
    sys.exit(1)

url = "https://api.telegram.org/bot" + token + "/sendMessage"
body = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": text,
    "disable_web_page_preview": "true",
}).encode()
req = urllib.request.Request(url, data=body, method="POST")

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
except urllib.error.HTTPError as exc:
    print("telegram: HTTP", exc.code, file=sys.stderr)
    sys.exit(1)
except Exception:
    print("telegram: request failed", file=sys.stderr)
    sys.exit(1)

if payload.get("ok"):
    print("telegram: ok")
    sys.exit(0)

print("telegram: api error", file=sys.stderr)
sys.exit(1)
