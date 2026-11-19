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
