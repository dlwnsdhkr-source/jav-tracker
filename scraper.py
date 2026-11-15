import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin, quote
import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://projectjav.com"
AVDBS_BASE = "https://www.avdbs.com"

def get_html(scraper, url, headers=None):
    try:
        res = scraper.get(url, headers=headers, timeout=25)
        if res.status_code == 200 and "Just a moment" not in res.text and len(res.text) > 300:
            return res.text
    except Exception as e:
        print(f"[cloudscraper 실패] {url}: {e}")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="ko-KR"
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

def search_avdbs_actor(scraper, actor_name):
    """AVDBS(avdbs.com)에서 배우 이름을 검색하여 프로필 이미지, 한글명, 상세 페이지 주소를 반환"""
    parts = actor_name.strip().split()
    queries = [actor_name.strip()]
    if len(parts) == 2:
        # 'Hana Himesaki' -> 'Himesaki Hana' 역순 검색어 추가
        queries.append(f"{parts[1]} {parts[0]}")

    headers = {
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.avdbs.com/menu/actor_list.php"
    }

    for q in queries:
        search_urls = [
            f"https://www.avdbs.com/menu/search.php?kwd={quote(q)}",
            f"https://www.avdbs.com/menu/actor_list.php?kwd={quote(q)}&_s=1"
        ]
        for s_url in search_urls:
            try:
                res = scraper.get(s_url, headers=headers, timeout=15)
                if res.status_code != 200:
                    continue
                soup = BeautifulSoup(res.text, "html.parser")

                # 배우 상세 링크(/menu/actor.php?actor_idx=...) 블록 탐색
                actor_links = soup.select('a[href*="actor.php?actor_idx="]')
                for a in actor_links:
                    card = a.parent
                    for _ in range(4):
                        if not card:
                            break
                        if card.find("img"):
                            break
                        card = card.parent
                    if not card:
                        card = a

                    img = card.find("img")
                    if not img:
                        continue
                    img_src = img.get("data-src") or img.get("src") or ""
                    if not img_src or "logo" in img_src.lower() or "blank" in img_src.lower():
                        continue

                    full_img = urljoin(AVDBS_BASE, img_src)
                    full_profile = urljoin(AVDBS_BASE, a["href"])
                    card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))

                    # 한글 이름 추출
                    kor_m = re.search(r"[가-힣]{2,10}(?:\s+[가-힣]{1,10})?", card_text)
                    kor_name = kor_m.group(0) if kor_m else ""

                    return {
                        "name": actor_name,
                        "korName": kor_name,
                        "photo": full_img,
                        "profileUrl": full_profile,
                        "desc": card_text[:100]
                    }
            except Exception as e:
                print(f"[AVDBS 검색 오류] {q}: {e}")
    return None

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
            if val.startswith("data:") or any(x in low for x in ["logo", "icon", "blank", "spinner", "avatar", "flag"]):
                continue
            return urljoin(BASE_URL, val)
    for tag in card.find_all(style=True):
        m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", tag["style"])
        if m:
            return urljoin(BASE_URL, m.group(1))
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
        is_movie_url = any(p in href.lower() for p in ["/movie/", "/video/", "/post/"])
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
            if any(k in th for k in ["/actress/", "/actor/", "/star/", "/cast/"]):
                if tt not in actress:
                    actress.append(tt)
            elif any(k in th for k in ["/tag/", "/genre/", "/category/"]):
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

    for p in [1, 2, 3]:
        url = BASE_URL if p == 1 else f"{BASE_URL}/?page={p}"
        html = get_html(scraper, url)
        if not html:
            continue
        for item in parse_page_items(html):
            if item["url"] not in seen:
                seen.add(item["url"])
                all_items.append(item)

    # 등장한 배우들의 프로필 이미지를 avdbs.com에서 자동 검색하여 매핑
    unique_actors = []
    for item in all_items:
        for act in item.get("actress", []):
            if act not in unique_actors:
                unique_actors.append(act)

    actors_map = {}
    for act_name in unique_actors[:45]:
        info = search_avdbs_actor(scraper, act_name)
        if info:
            actors_map[act_name] = info
            print(f"[AVDBS 매칭 성공] {act_name} -> {info.get('korName')} ({info.get('photo')})")
        time.sleep(0.25)

    payload = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(all_items),
        "actors": actors_map,
        "items": all_items
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"수집 완료: 작품 {len(all_items)}개, AVDBS 배우 프로필 {len(actors_map)}명 저장됨")

if __name__ == "__main__":
    main()
