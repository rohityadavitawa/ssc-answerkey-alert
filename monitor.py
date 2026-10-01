import os
import json
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup


BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

SEEN_FILE = "seen_notices.json"
DIGIALM_FILE = "tracked_digialm_urls.json"

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    )
}


# Main SSC pages
SOURCES = [
    ("SSC Home", "https://ssc.gov.in/"),
    ("SSC Answer Key", "https://ssc.gov.in/home/answer-key"),
]


# Secondary source only for discovering official links
SECONDARY_SOURCES = [
    ("Selection Post Tracker", "https://ezssc.in/selection-post/index.php"),
]


TARGET_TERMS = [
    "selection post",
    "selection posts",
    "phase xiv",
    "phase-xiv",
    "phase 14",
    "phase-14",
]


ANSWER_TERMS = [
    "answer key",
    "answer-key",
    "response sheet",
    "response-sheet",
    "tentative answer",
    "final answer",
    "candidate response",
    "question paper",
    "challenge",
]


DIGIALM_HOSTS = {
    "ssc.digialm.com",
    "cdn.digialm.com",
}


GENERIC_TITLES = {
    "click here",
    "click here to view",
    "view",
    "pdf",
    "download",
    "notice",
    "here",
    "link",
}


session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def make_absolute(base, href):
    if not href:
        return None

    url = urljoin(base, href)
    url, _ = urldefrag(url)

    return url


def is_relevant(text):
    text = clean(text).lower()

    has_target = any(term in text for term in TARGET_TERMS)
    has_answer = any(term in text for term in ANSWER_TERMS)

    return has_target and has_answer


def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def page(url):
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"ERROR: {url} -> {e}")
        return None


def get_title(link):
    title = clean(link.get_text(" ", strip=True))

    if title and title.lower() not in GENERIC_TITLES and len(title) >= 12:
        return title

    for tag in ["h1", "h2", "h3", "h4", "strong", "b"]:
        previous = link.find_previous(tag)

        if previous:
            text = clean(previous.get_text(" ", strip=True))

            if len(text) >= 12:
                return text

    parent = link.find_parent(["li", "article", "tr"])

    if parent:
        text = clean(parent.get_text(" ", strip=True))

        if len(text) >= 12:
            return text[:500]

    return title or "SSC Selection Post Phase XIV notice"


def make_id(title, url):
    value = clean(title).lower() + "|" + url.lower()

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def send_telegram(title, url, source):
    message = (
        "🚨 SSC PHASE XIV ANSWER KEY ALERT\n\n"
        f"{title}\n\n"
        f"🔗 Direct Link:\n{url}\n\n"
        f"Source: {source}"
    )

    r = session.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=TIMEOUT,
    )

    r.raise_for_status()

    print("Telegram alert sent:", title)


def extract_digialm_urls(html):
    urls = set()

    pattern = re.compile(
        r'https?://(?:ssc\.digialm\.com|cdn\.digialm\.com)[^"\'<>\s]+',
        re.IGNORECASE,
    )

    for match in pattern.findall(html):
        url = match.rstrip(".,);")

        if url:
            urls.add(url)

    return urls


def scan_page(source_name, url):
    results = []
    digialm_urls = set()

    r = page(url)

    if not r:
        return results, digialm_urls

    soup = BeautifulSoup(r.text, "html.parser")

    # Find DigiALM URLs appearing anywhere in the page source
    for durl in extract_digialm_urls(r.text):
        if is_relevant(r.text):
            digialm_urls.add(durl)

    # Find normal links
    for link in soup.find_all("a", href=True):

        href = make_absolute(r.url, link.get("href"))

        if not href:
            continue

        title = get_title(link)

        # Text around the link
        parent = link.find_parent(["li", "article", "div", "tr"])

        surrounding = title

        if parent:
            surrounding += " " + clean(
                parent.get_text(" ", strip=True)
            )

        # DigiALM link
        host = urlparse(href).netloc.lower()

        if host in DIGIALM_HOSTS:

            if is_relevant(surrounding):
                digialm_urls.add(href)

            continue

        # Normal SSC/secondary notice
        if not is_relevant(surrounding):
            continue

        results.append(
            {
                "title": title,
                "url": href,
                "source": source_name,
            }
        )

    return results, digialm_urls


def scan_digialm(url):
    results = []

    r = page(url)

    if not r:
        return results

    soup = BeautifulSoup(r.text, "html.parser")

    page_text = clean(soup.get_text(" ", strip=True))

    # The DigiALM page itself may contain the useful title
    if is_relevant(page_text):

        title = None

        for tag in soup.find_all(
            ["h1", "h2", "h3", "h4", "strong", "b", "title"]
        ):

            text = clean(tag.get_text(" ", strip=True))

            if is_relevant(text):
                title = text
                break

        if not title:
            title = "SSC Selection Post Phase XIV Answer Key / Response Sheet"

        results.append(
            {
                "title": title,
                "url": url,
                "source": "DigiALM",
            }
        )

    return results


def main():

    seen = load_json(SEEN_FILE, {})
    tracked_digialm = set(
        load_json(DIGIALM_FILE, [])
    )

    all_notices = []

    # 1. SSC official pages
    for source_name, url in SOURCES:

        notices, digialm = scan_page(
            source_name,
            url
        )

        all_notices.extend(notices)

        tracked_digialm.update(digialm)

    # 2. Secondary source
    for source_name, url in SECONDARY_SOURCES:

        notices, digialm = scan_page(
            source_name,
            url
        )

        all_notices.extend(notices)

        tracked_digialm.update(digialm)

    # 3. Previously discovered DigiALM pages
    for url in sorted(tracked_digialm):

        notices = scan_digialm(url)

        all_notices.extend(notices)

    # Save discovered DigiALM pages
    save_json(
        DIGIALM_FILE,
        sorted(tracked_digialm)
    )

    new_count = 0

    for notice in all_notices:

        title = clean(notice["title"])
        url = notice["url"]
        source = notice["source"]

        if not title or not url:
            continue

        unique_id = make_id(title, url)

        if unique_id in seen:
            continue

        # Send Telegram alert first
        try:

            send_telegram(
                title,
                url,
                source
            )

            # Remember only after successful Telegram delivery
            seen[unique_id] = {
                "title": title,
                "url": url,
                "source": source,
                "first_seen": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

            new_count += 1

        except Exception as e:

            print(
                f"Telegram failed for {title}: {e}"
            )

    save_json(
        SEEN_FILE,
        seen
    )

    print(
        f"Finished. New alerts: {new_count}"
    )


if __name__ == "__main__":
    main()
