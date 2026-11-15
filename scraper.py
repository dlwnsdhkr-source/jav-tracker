import json
import re
from datetime import datetime
from urllib.parse import urljoin
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"

def get_html(scraper, url):
    try:
        res = scraper.get(url, timeout=25)
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
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(4000)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[Playwright 실패] {url}: {e}")
    return ""

def normalize_date(raw_date):
    if not raw_date:
        return datetime.now().strftime("%Y-%m-%d")
    # DD/MM/YYYY 또는 DD/MM/YY 형태를 YYYY-MM-DD로 통일
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
            if val.startswith("data:") or any(x in low for x in ["logo", "icon", "blank", "spinner", "avatar", "flag"]):
                continue
            return urljoin(BASE_URL, val)
    # style background-image 체크
    for tag in card.find_all(style=True):
        m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", tag["style"])
        if m:
            return urljoin(BASE_URL, m.group(1))
    return ""

def extract_torrents_from_card(card):
    """카드 내부의 Download(.torrent)와 Magnet 링크를 행(용량/시드/날짜) 단위로 묶어 추출"""
    torrents = []
    seen_urls = set()

    # 1. Magnet 링크 기준으로 주변(같은 줄/블록)에서 짝꿍 Download 링크와 용량(GB/MB) 찾기
    all_links = card.find_all("a", href=True)
    used_dl_urls = set()

    for a in all_links:
        href = a["href"].strip()
        if not href.startswith("magnet:"):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        # 마그넷 링크가 속한 한 줄(row) 컨테이너 찾기
        row = a.parent
        while row and row != card and len(row.get_text(" ", strip=True)) < 18:
            row = row.parent
        row_text = row.get_text(" ", strip=True) if row else ""

        # 같은 줄에 있는 .torrent 다운로드 링크 찾기
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
        # 시드(S), 리처(L) 숫자 추출
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

    # 2. 만약 마그넷 없이 단독 Download(.torrent) 링크만 있는 경우 추가
    for a in all_links:
        href = a["href"].strip()
        txt = a.get_text(" ", strip=True).lower()
        if href.startswith("magnet:") or href.startswith("#") or href.startswith("javascript"):
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

    # 작품 제목 링크 탐색 (Download, Magnet, 태그, 배우 링크는 제외하고 실제 작품 링크만 골라냄)
    ignore_words = {"download", "magnet", "screenshot", "more torrents >>", "more torrents", "suggest an idea", "login", "register"}

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        if title.lower() in ignore_words:
            continue
        if href.startswith(("#", "javascript", "magnet:")):
            continue
        if any(seg in href.lower() for seg in ["/tag/", "/actress/", "/actor/", "/genre/", "/category/", "/search", "?page=", "/download"]):
            continue

        # 품번 형태(예: Muka-011, ATYA-048 등)가 들어있거나 /movie/ 경로인 링크를 작품 제목으로 확정
        has_code = bool(re.search(r"\b[A-Za-z]{2,6}-\d{2,5}\b", title))
        is_movie_url = "/movie/" in href.lower() or "/video/" in href.lower() or "/post/" in href.lower()
        if not (has_code or is_movie_url):
            continue

        movie_url = urljoin(BASE_URL, href)
        if movie_url in seen_movies:
            continue

        # 이 작품 제목을 감싸고 있는 전체 카드(부모 컨테이너: 이미지 + 다운로드 목록을 모두 포함한 블록) 찾기
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

        # 카드 내 게시 날짜 추출 (예: 17/11/2026)
        date_m = re.search(r"(\d{1,2}/\d{1,2}/20\d{2})|(20\d{2}-\d{1,2}-\d{1,2})", card_text)
        raw_date = date_m.group(0) if date_m else ""
        norm_date = normalize_date(raw_date)

        # 배우 및 태그 추출
        tags = []
        actress = []
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

        thumb = extract_cover_image(best_card)
        torrents = extract_torrents_from_card(best_card)

        seen_movies.add(movie_url)
        items.append({
            "title": title,
            "url": movie_url,
            "date": norm_date,
            "displayDate": raw_date or norm_date,
            "thumb": thumb,
            "actress": actress[:4],
            "tags": tags[:8],
            "torrents": torrents
        })

    return items

def main():
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    all_items = []
    seen = set()

    # 최신 1~3페이지 수집
    for p in [1, 2, 3]:
        url = BASE_URL if p == 1 else f"{BASE_URL}/?page={p}"
        html = get_html(scraper, url)
        if not html:
            continue
        page_items = parse_page_items(html)
        for item in page_items:
            if item["url"] not in seen:
                seen.add(item["url"])
                all_items.append(item)

    payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_items),
        "items": all_items
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"수집 완료: 총 {len(all_items)}개 작품 카드 저장됨")

if __name__ == "__main__":
    main()
