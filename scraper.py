import json
import re
from datetime import datetime
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"

def get_html(scraper, url):
    try:
        res = scraper.get(url, timeout=20)
        if res.status_code == 200 and "Just a moment" not in res.text and len(res.text) > 500:
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
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3500)
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

def extract_code(title, url):
    text = f"{title} {url}"
    fc2 = re.search(r"FC2[-_\s]*(?:PPV[-_\s]*)?(\d{5,8})", text, re.I)
    if fc2:
        return f"FC2-PPV-{fc2.group(1)}"
    m = re.search(r"\b([A-Za-z]{2,6}|\d[A-Za-z]{1,4})[-_](\d{2,5}[A-Za-z]?)\b", title)
    if m:
        return f"{m.group(1).upper()}-{m.group(2).upper()}"
    return ""

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

        row = a.parent
        while row and row != card and len(row.get_text(" ", strip=True)) < 18:
            row = row.parent
        row_text = row.get_text(" ", strip=True) if row else ""

        paired_dl = ""
        if row:
            for sib in row.find_all("a", href=True):
                shref = sib["href"].strip()
                stxt = sib.get_text(" ", strip=True).lower()
                if not shref.startswith("magnet:") and ("download" in stxt or ".torrent" in shref.lower() or "download" in shref.lower()):
                    paired_dl = urljoin(BASE_URL, shref)
                    used_dl_urls.add(paired_dl)
                    break

        size_m = re.search(r"(\d+(?:\.\d+)?\s*(?:gb|mb))", row_text, re.I)
        date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", row_text)
        nums = re.findall(r"\b\d+\b", re.sub(r"\d+(?:\.\d+)?\s*(?:gb|mb)|\d{1,2}/\d{1,2}/\d{2,4}", "", row_text, flags=re.I))
        seeds = nums[0] if len(nums) >= 1 else ""
        leeches = nums[1] if len(nums) >= 2 else ""

        torrents.append({
            "size": size_m.group(1).lower() if size_m else "일반화질",
            "seeds": seeds,
            "leeches": leeches,
            "date": date_m.group(1) if date_m else "",
            "downloadUrl": paired_dl,
            "magnetUrl": href
        })

    for a in all_links:
        href = a["href"].strip()
        txt = a.get_text(" ", strip=True).lower()
        if href.startswith(("magnet:", "#", "javascript")):
            continue
        if "download" in txt or ".torrent" in href.lower():
            full_dl = urljoin(BASE_URL, href)
            if full_dl in used_dl_urls or full_dl in seen_urls:
                continue
            seen_urls.add(full_dl)
            row = a.parent
            while row and row != card and len(row.get_text(" ", strip=True)) < 15:
                row = row.parent
            row_text = row.get_text(" ", strip=True) if row else ""
            size_m = re.search(r"(\d+(?:\.\d+)?\s*(?:gb|mb))", row_text, re.I)
            date_m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", row_text)
            torrents.append({
                "size": size_m.group(1).lower() if size_m else "토렌트",
                "seeds": "",
                "leeches": "",
                "date": date_m.group(1) if date_m else "",
                "downloadUrl": full_dl,
                "magnetUrl": ""
            })

    return torrents

def parse_page_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen_movies = set()
    ignore_words = {"download", "magnet", "screenshot", "more torrents >>", "more torrents", "suggest an idea", "login", "register"}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5 or title.lower() in ignore_words:
            continue
        if href.startswith(("#", "javascript", "magnet:")):
            continue
        if any(seg in href.lower() for seg in ["/tag/", "/actress/", "/actor/", "/genre/", "/category/", "/search", "?page=", "/download"]):
            continue

        has_code = bool(re.search(r"\b[A-Za-z]{2,6}-\d{2,5}\b", title))
        is_movie_url = "/movie/" in href.lower() or "/video/" in href.lower() or "/post/" in href.lower()
        if not (has_code or is_movie_url):
            continue

        movie_url = urljoin(BASE_URL, href)
        if movie_url in seen_movies:
            continue

        card = a.parent
        best_card = card
        for _ in range(7):
            if not card or card.name in ["body", "html", "main"]:
                break
            has_img = card.find("img") is not None
            has_dl = card.find("a", href=re.compile(r"magnet:|\.torrent|download", re.I)) is not None or "download" in card.get_text(" ", strip=True).lower()
            if has_img and has_dl:
                best_card = card
                break
            card = card.parent

        card_text = best_card.get_text(" ", strip=True)
        date_m = re.search(r"(\d{1,2}/\d{1,2}/20\d{2})|(20\d{2}-\d{1,2}-\d{1,2})", card_text)
        raw_date = date_m.group(0) if date_m else ""
        norm_date = normalize_date(raw_date)

        tags, actress = [], []
        for t_a in best_card.find_all("a", href=True):
            th = t_a["href"].lower()
            tt = t_a.get_text(" ", strip=True)
            if not tt or tt == title or tt.lower() in ignore_words:
                continue
            if "/actress/" in th or "/actor/" in th or "/star/" in th:
                if tt not in actress:
                    actress.append(tt)
            elif "/tag/" in th or "/genre/" in th or "/category/" in th:
                if tt not in tags:
                    tags.append(tt)

        seen_movies.add(movie_url)
        items.append({
            "code": extract_code(title, movie_url),
            "title": title,
            "url": movie_url,
            "date": norm_date,
            "displayDate": raw_date or norm_date,
            "thumb": extract_cover_image(best_card),
            "actress": actress[:4],
            "tags": tags[:8],
            "torrents": extract_torrents_from_card(best_card)
        })

    return items

def main():
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    # 1. 기존 data.json에 저장된 과거 작품 불러오기
    existing_items = []
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            old_data = json.load(f)
            existing_items = old_data.get("items", [])
    except Exception:
        existing_items = []

    # 2. 최신 1~5페이지 새로 수집 (더 많이 원하면 range(1, 11) 등으로 숫자만 변경)
    new_items, seen = [], set()
    for p in range(1, 6):
        url = BASE_URL if p == 1 else f"{BASE_URL}/?page={p}"
        html = get_html(scraper, url)
        if not html:
            continue
        for item in parse_page_items(html):
            if item["url"] not in seen:
                seen.add(item["url"])
                new_items.append(item)

    if len(new_items) == 0:
        raise RuntimeError("수집된 항목이 0건입니다. 사이트 차단 여부를 확인하세요.")

    # 3. 새 작품을 맨 앞에 두고, 중복되지 않는 기존 작품을 뒤에 이어붙여 누적 (최대 1,000개 보관)
    merged_items = list(new_items)
    for old_item in existing_items:
        old_url = old_item.get("url")
        if old_url and old_url not in seen:
            seen.add(old_url)
            merged_items.append(old_item)

    merged_items = merged_items[:1000]

    payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(merged_items),
        "items": merged_items
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"수집 완료: 신규 {len(new_items)}개 포함 총 {len(merged_items)}개 작품 저장됨")

if __name__ == "__main__":
    main()
