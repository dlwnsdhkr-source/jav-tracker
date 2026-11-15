import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"

def get_html(scraper, url):
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code == 200 and "Just a moment" not in res.text:
            return res.text
    except Exception as e:
        print(f"[cloudscraper 실패] {url}: {e}")

    # Cloudscraper가 막히면 실제 헤드리스 크롬(Playwright)으로 우회
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[Playwright 실패] {url}: {e}")
    return ""

def extract_date(text):
    patterns = [
        r"(20\d{2}[-./]\d{1,2}[-./]\d{1,2})",
        r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s*20\d{2}\b)",
        r"(\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d{2}\b)"
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return datetime.now().strftime("%Y-%m-%d")

def extract_image(node):
    if not node:
        return ""
    for img in node.find_all("img"):
        for attr in ["data-src", "data-original", "data-lazy-src", "src"]:
            val = img.get(attr, "").strip()
            if val and not val.startswith("data:") and "logo" not in val.lower():
                return urljoin(BASE_URL, val)
    return ""

def extract_attachments(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    files = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        full_url = href if href.startswith("magnet:") else urljoin(page_url, href)

        is_dl = (
            href.startswith("magnet:")
            or re.search(r"\.(torrent|zip|rar|7z|mp4|mkv|srt|ass)(\?|$)", href, re.I)
            or re.search(r"(download|torrent|magnet|attachment)", href + " " + text + " " + " ".join(a.get("class", [])), re.I)
        )
        if is_dl and full_url not in seen and not href.startswith("#") and not href.startswith("javascript"):
            seen.add(full_url)
            label = text if len(text) > 1 else ("Magnet Link" if full_url.startswith("magnet:") else full_url.split("/")[-1])
            files.append({"label": label[:80], "url": full_url})

    # 본문 텍스트 내 마그넷 정규식 추출
    for m in re.findall(r"magnet:\?xt=urn:btih:[a-zA-Z0-9%&=\-._]+", html):
        if m not in seen:
            seen.add(m)
            files.append({"label": "마그넷(Magnet) 링크", "url": m})

    # 대표 이미지 추출
    og_img = soup.find("meta", property="og:image")
    main_img = urljoin(page_url, og_img["content"]) if og_img and og_img.get("content") else extract_image(soup.body)

    return files, main_img

def main():
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    items = []
    seen_urls = set()

    # 1~2페이지 스캔
    for page_num in [1, 2]:
        target_url = BASE_URL if page_num == 1 else f"{BASE_URL}/?page={page_num}"
        html = get_html(scraper, target_url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        containers = soup.select("tr, article, .card, .post, .item, .movie-item, .video-item, .col-md-3, .col-sm-6, li")

        for el in containers:
            links = el.find_all("a", href=True)
            if not links:
                continue

            main_link = None
            for a in links:
                href = a["href"].strip()
                txt = (a.get_text(" ", strip=True) or a.get("title", "")).strip()
                if len(txt) >= 3 and not href.startswith(("#", "javascript", "magnet:")):
                    main_link = a
                    break
            if not main_link:
                continue

            full_url = urljoin(BASE_URL, main_link["href"].strip())
            if full_url in seen_urls or full_url.rstrip("/") == BASE_URL.rstrip("/"):
                continue

            title = (main_link.get_text(" ", strip=True) or main_link.get("title", "")).strip()
            if len(title) < 3:
                continue

            date_str = extract_date(el.get_text(" ", strip=True))
            thumb = extract_image(el)

            # 목록에 바로 노출된 다운로드 링크 수집
            direct_files = []
            for a in links:
                h = a["href"].strip()
                if h.startswith("magnet:") or re.search(r"\.(torrent|zip|rar|7z)(\?|$)|download|torrent", h, re.I):
                    direct_files.append({
                        "label": a.get_text(" ", strip=True) or "첨부파일 다운로드",
                        "url": h if h.startswith("magnet:") else urljoin(BASE_URL, h)
                    })

            seen_urls.add(full_url)
            items.append({
                "title": title,
                "url": full_url,
                "date": date_str,
                "thumb": thumb,
                "files": direct_files
            })

    # 상위 25개 항목은 상세 페이지까지 들어가서 첨부파일과 썸네일 완벽 추출
    for idx, item in enumerate(items[:25]):
        if not item["files"] or not item["thumb"]:
            detail_html = get_html(scraper, item["url"])
            if detail_html:
                files, detail_img = extract_attachments(detail_html, item["url"])
                if files:
                    item["files"] = files
                if not item["thumb"] and detail_img:
                    item["thumb"] = detail_img
            time.sleep(0.5)

    payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(items),
        "items": items
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"총 {len(items)}건 data.json 저장 완료")

if __name__ == "__main__":
    main()
