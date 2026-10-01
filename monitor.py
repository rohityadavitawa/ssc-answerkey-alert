import requests
import os
import json
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SSC_URL = "https://ssc.gov.in/home/answer-key"

KEYWORDS = [
    "selection post",
    "phase xiv",
    "phase-xiv",
    "phase 14",
    "answer key",
    "response sheet"
]

SEEN_FILE = "seen_notices.json"


def send_telegram(message):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=30
    )


def load_seen():
    try:
        with open(SEEN_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def save_seen(data):
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f)


def get_notices():
    notices = []

    try:
        r = requests.get(SSC_URL, timeout=30)

        soup = BeautifulSoup(r.text, "html.parser")

        links = soup.find_all("a")

        for link in links:

            title = link.get_text(" ", strip=True)

            href = link.get("href")

            if not title:
                continue

            title_lower = title.lower()

            if (
                "selection post" in title_lower
                or "phase xiv" in title_lower
                or "phase 14" in title_lower
                or "answer key" in title_lower
                or "response sheet" in title_lower
            ):

                if href:

                    if href.startswith("/"):
                        href = "https://ssc.gov.in" + href

                    notices.append({
                        "title": title,
                        "url": href
                    })

    except Exception as e:
        print(e)

    return notices


seen = load_seen()

new_seen = seen.copy()

notices = get_notices()

for notice in notices:

    unique_id = notice["title"]

    if unique_id not in seen:

        message = (
            "🚨 SSC ALERT\n\n"
            f"{notice['title']}\n\n"
            f"{notice['url']}"
        )

        send_telegram(message)

        new_seen
