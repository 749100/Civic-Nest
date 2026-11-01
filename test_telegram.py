from dotenv import load_dotenv
import os
import requests

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

print("token set:", bool(token), "| chat id set:", bool(chat_id))

response = requests.post(
    f"https://api.telegram.org/bot{token}/sendMessage",
    json={"chat_id": chat_id, "text": "CivicNest test message"},
    timeout=10,
)

print(response.status_code, response.text)