import os
import json
import re
from datetime import datetime
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"
# 한 번 실행할 때 긁어올 페이지 수 (1페이지당 48개 -> 10페이지면 약 480개 신규 스캔)
# 더 많이 원하시면 15나 20으로 늘리셔도 됩니다.
MAX_PAGES = 10
# data.json에 누적 보관할 최대 작품 수 (너무 커져서 앱이 느려지는 것 방지)
MAX_KEEP_ITEMS = 3000

def get_html(scraper, url):
    try:
        res = scraper.get(url, timeout=25)
        if res.status_code == 200 and "Just a moment" not in res.text and len(res.text) > 300:
            return res.text
    except Exception as e:
        print(f"[cloudscraper 실패] {url}: {e}")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[Playwright 실패] {url}: {e}")
    return ""

def normalize_date(raw_date):
    if not raw_date:
        return datetime.now().strftime("%Y-%m-%d")
    m1 = re.search(r"(\d{1,2})/(\d{1,2})/(20\d{2}|\d{2})", raw_date)
    if m1:
        d, m, y = m1.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{int(m):02d}-{int(d):02d}"
    m2 = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", raw_date)
    if m2:
        y, m, d = m2.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return raw_date

def extract_cover_image(card):
    for img in card.find_all("img"):
        for attr in ["data-src", "data-original", "data-lazy-src", "srcset", "src"]:
            val = img.get(attr, "").strip()
            if not val:
                continue
            if attr == "srcset":
                val = val.split(",")[0].strip().split(" ")[0]
            low = val.lower()
            if val.startswith("data:") or ".php" in low or any(x in low for x in ["logo", "icon", "blank", "spinner", "avatar", "flag"]):
                continue
            return urljoin(BASE_URL, val)
    return ""

def extract_torrents_from_card(card):
    torrents = []
    seen_urls = set()
    all_links = card.find_all("a", href=True)
    used_dl_urls = set()

    for a in all_links:
        href = a["href"].strip()
        if not href.startswith("magnet:") or href in seen_urls:
            continue
        seen_urls.add(href)

        row = a
