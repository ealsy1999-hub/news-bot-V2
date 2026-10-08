import os
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates")
data = r.json()

for update in data.get("result", []):
    msg = update.get("message", {})
    chat = msg.get("chat", {})
    print(f"Chat ID: {chat.get('id')} | Name: {chat.get('first_name')} {chat.get('last_name','')}")
