import json
import re
from datetime import datetime
from urllib.parse import urljoin, quote
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"
AVDBS_BASE = "https://www.avdbs.com"

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
            page.wait_for_timeout(3500)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"[Playwright 실패] {url}: {e}")
    return ""

def extract_real_img_from_avdbs_html(html):
    """AVDBS 웹페이지(HTML) 안에서 실제 배우 프로필 .jpg 이미지 주소만 정확히 추출"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # 1순위: og:image 메타 태그 확인
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        og_url = og["content"].strip()
        if any(ext in og_url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]) and "logo" not in og_url.lower():
            return urljoin(AVDBS_BASE, og_url)

    # 2순위: 배우 사진 전용 경로(/actor/ 또는 profile 이미지)를 가진 img 태그 탐색
    for img in soup.find_all("img"):
        src = (img.get("data-src") or img.get("src") or "").strip()
        if not src:
            continue
        low = src.lower()
        if any(bad in low for bad in ["logo", "icon", "banner", "btn", "blank", "flag", "svg"]):
            continue
        if any(ext in low for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return urljoin(AVDBS_BASE, src)

    return ""

def fetch_avdbs_actor_image(scraper, actor_name, cache_dict):
    """AVDBS에서 배우 이름으로 검색하여 고유 actor_idx 페이지 또는 목록의 실제 이미지 URL 반환"""
    if not actor_name:
        return ""
    if actor_name in cache_dict:
        return cache_dict[actor_name]

    # 혹시 이미 actor.php?actor_idx=... 링크가 들어온 경우 해당 페이지에서 실제 .jpg 추출
    if "avdbs.com/menu/actor.php" in actor_name:
        html = get_html(scraper, actor_name)
        real_img = extract_real_img_from_avdbs_html(html)
        cache_dict[actor_name] = real_img
        return real_img

    # AVDBS 통합 검색 및 배우 목록 검색 URL 순차 시도
    search_urls = [
        f"https://www.avdbs.com/menu/search.php?kwd={quote(actor_name)}",
        f"https://www.avdbs.com/menu/actor_list.php?kwd={quote(actor_name)}",
        f"https://www.avdbs.com/menu/actor.php?kwd={quote(actor_name)}"
    ]

    for s_url in search_urls:
        html = get_html(scraper, s_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")

        # 검색 결과에 배우 카드(actor.php?actor_idx=...)가 있는지 확인
        actor_link = soup.find("a", href=re.compile(r"actor\.php\?actor_idx=\d+", re.I))
        if actor_link:
            # 1) 링크 주변/자식 태그에 바로 썸네일 이미지(.jpg)가 있으면 즉시 추출
            card_parent = actor_link.parent
            for _ in range(3):
                if card_parent:
                    img_url = extract_real_img_from_avdbs_html(str(card_parent))
                    if img_url:
                        cache_dict[actor_name] = img_url
                        return img_url
                    card_parent = card_parent.parent

            # 2) 목록에 이미지가 없으면 찾은 actor.php?actor_idx=번호 상세 페이지로 들어가서 추출
            detail_url = urljoin(AVDBS_BASE, actor_link["href"])
            detail_html = get_html(scraper, detail_url)
            img_url = extract_real_img_from_avdbs_html(detail_html)
            if img_url:
                cache_dict[actor_name] = img_url
                return img_url

        # 링크 구조가 다를 경우 페이지 내 첫 번째 유효 배우 이미지 추출
        fallback_img = extract_real_img_from_avdbs_html(html)
        if fallback_img:
            cache_dict[actor_name] = fallback_img
            return fallback_img

    cache_dict[actor_name] = ""
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
            # actor.php 같은 웹페이지 주소가 이미지로 잘못 들어가는 현상 차단
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

def parse_page_items(html, scraper, actor_cache):
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

        # 각 배우의 AVDBS 실제 프로필 이미지(.jpg) 매핑
        actress_images = {}
        for act_name in actress[:3]:
            img_url = fetch_avdbs_actor_image(scraper, act_name, actor_cache)
            if img_url:
                actress_images[act_name] = img_url

        seen_movies.add(movie_url)
        items.append({
            "title": title,
            "url": movie_url,
            "date": norm_date,
            "displayDate": raw_date or norm_date,
            "thumb": thumb,
            "actress": actress[:4],
            "actressImages": actress_images,
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
    actor_cache = {}

    for p in [1, 2, 3]:
        url = BASE_URL if p == 1 else f"{BASE_URL}/?page={p}"
        html = get_html(scraper, url)
        if not html:
            continue
        page_items = parse_page_items(html, scraper, actor_cache)
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
    print(f"수집 완료: 총 {len(all_items)}개 작품 저장됨")

if __name__ == "__main__":
    main()
