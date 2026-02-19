# scraper_kvillage.py
import re
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup
from typing import Callable, Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ProgressCB = Optional[Callable[[str], None]]


def _pick_code_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1] or "UNKNOWN"


def _normalize_price(text: str):
    m = re.search(r"(\d{1,3}(?:,\d{3})+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _abs_url(base: str, src: str) -> str:
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    return urljoin(base, src)


# -----------------------------
# ✅ 추가: 상품정보제공고시(gvnt-info) 파싱 헬퍼
# -----------------------------

def scrape_kvillage_requests(url: str, progress_cb: ProgressCB = None) -> dict:
    if progress_cb:
        progress_cb("상품 페이지를 불러오고 있습니다.")

    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    if progress_cb:
        progress_cb("필요한 텍스트/이미지 URL을 추출하고 있습니다.")

    code = _pick_code_from_url(url)
    text = soup.get_text("\n", strip=True)
    m_code = re.search(r"\bDM[UP]\d{5,}\w*\b", text)
    if m_code:
        code = m_code.group(0)

    h2 = soup.select_one("div.prd-info-holder h2") or soup.select_one("h2")
    title = h2.get_text(" ", strip=True) if h2 else None

    sale_price = None
    list_price = None
    prd_price = soup.select_one("p.prd-price")
    if prd_price:
        sale_price = _normalize_price(prd_price.get_text(" ", strip=True))
        org = prd_price.select_one(".org-price")
        if org:
            list_price = _normalize_price(org.get_text(" ", strip=True))

    # ✅ pd-photo 이미지 URL만
    pd_photo_urls = []
    pd_photo = soup.select_one("div.detail-con.left-con")
    if pd_photo:
        for img in pd_photo.select("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if not src or src.startswith("data:"):
                continue
            pd_photo_urls.append(_abs_url(url, src))

    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for u in pd_photo_urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)

    # -----------------------------
    # ✅ 추가: 상품정보제공고시에서 제조사/제조연월 추출
    # - a태그 클릭은 필요 없음(요청 HTML에 ul#gvnt-info가 존재하면 파싱 가능)
    # -----------------------------

    return {
        "mode": "requests",
        "source_url": url,
        "code": code,
        "title": title,
        "sale_price": sale_price,
        "list_price": list_price,
        "pd_photo_image_urls": uniq,
    }
