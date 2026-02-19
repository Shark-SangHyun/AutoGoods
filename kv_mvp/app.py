# app.py
# ✅ UI: 제목 "이미지 수집"
# ✅ 입력: URL이 아니라 "품번"만 입력
# ✅ 고정 URL prefix: https://www.k-village.co.kr/goods/
# ✅ 예) DMU24101CH 입력 -> https://www.k-village.co.kr/goods/DMU24101CH 로 작업 수행
#
# ✅ 기존 기능/결과물 유지:
#   - pd_photo 개별 다운로드
#   - size_table(있을 수도/없을 수도) 캡처 + 합본에 조건부 포함
#   - 아코디언/셀렉터 렌더 저장
#   - pd_photo_merged 생성
#   - product.json 저장
#
# ✅ 추가(요청):
#   - 옵션 “사이즈를 선택하세요.” 클릭 후 나오는 ul[name="size-li"] 항목을 product.json에 저장
#   - label(표시 텍스트) + href + addOrder_args(따옴표 안 값들) 저장
#
# ✅ 추가(요청):
#   - "사이즈 가이드" 아코디언을 열고 내부에서
#     - table#size-guide (테이블형)
#     - div.size-guide-rf (이미지형 조견표)
#     도 캡처 대상으로 포함
#
# ✅ 프리뷰 캡처:
#   - 위 두 개(#size-guide / size-guide-rf)는 "프리뷰 HTML 문자열"로 렌더 후 JPG 캡처
#   - 별도 .html 파일은 만들지 않음(지울 것도 없음)
#
# ✅ 추가(이번 요청):
#   - '상품정보제공고시'가 클릭해야만 DOM이 생기는 케이스 대응
#   - requests 1차에서 제조국/제조연월 못 뽑으면
#     Playwright로 아코디언 클릭 후 ul#gvnt-info를 파싱하여 product.json에 채움
#
# ✅ 최적화(요청: 반복 실행 이유 존중 + 시간 단축):
#   - Playwright 브라우저를 "job 당 1회만" 띄우고,
#   - 옵션 추출/size_table 캡처/gvnt 클릭 파싱은 "페이지를 분리"해서 상태 격리를 유지
#   - (render_targets_hybrid 내부 Playwright는 건드리지 않음)

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse

from renderer_kvillage import render_targets_hybrid
from scraper_kvillage import scrape_kvillage_requests

app = FastAPI()
BASE_OUT = Path("out")
GOODS_PREFIX = "https://www.k-village.co.kr/goods/"

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()


def _set_job(job_id: str, **kwargs):
    with LOCK:
        job = JOBS.get(job_id, {})
        job.update(kwargs)
        JOBS[job_id] = job


def _get_job(job_id: str):
    with LOCK:
        return dict(JOBS.get(job_id, {}))


def safe_filename(name: str) -> str:
    name = (name or "").strip()
    return "".join(c for c in name if c.isalnum() or c in ("-", "_"))[:120] or "file"


def sanitize_goods_code(code: str) -> str:
    c = (code or "").strip()
    c = re.sub(r"\s+", "", c)
    c = re.sub(r"[^A-Za-z0-9_-]", "", c)
    return c


def build_goods_url(code: str) -> str:
    c = sanitize_goods_code(code)
    return GOODS_PREFIX + c


def download_images(image_urls, out_dir: Path, prefix: str = "pd"):
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(image_urls or [], start=1):
        try:
            r = requests.get(url, timeout=30, stream=True)
            r.raise_for_status()

            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"

            fname = out_dir / f"{prefix}_{i:03d}{ext}"
            with open(fname, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            saved.append(str(fname))
        except Exception:
            continue
    return saved


def merge_images_vertical_jpg(image_paths, out_path: Path):
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow가 필요합니다. `pip install pillow` 후 다시 시도하세요.") from e

    imgs = []
    for p in image_paths or []:
        try:
            im = Image.open(p).convert("RGB")
            imgs.append(im)
        except Exception:
            continue

    if not imgs:
        return None

    max_w = max(im.width for im in imgs)
    resized = []
    total_h = 0

    for im in imgs:
        if im.width != max_w:
            new_h = int(im.height * (max_w / im.width))
            im = im.resize((max_w, new_h))
        resized.append(im)
        total_h += im.height

    merged = Image.new("RGB", (max_w, total_h), (255, 255, 255))
    y = 0
    for im in resized:
        merged.paste(im, (0, y))
        y += im.height

    out_path.parent.mkdir(parents=True, exist_ok=True)
    MAX_WIDTH = 1400   # ⭐ 1200~1600 추천

    if merged.width > MAX_WIDTH:
        scale = MAX_WIDTH / merged.width
        new_w = MAX_WIDTH
        new_h = int(merged.height * scale)

        merged = merged.resize((new_w, new_h), Image.LANCZOS)

        print("RESIZED SIZE:", merged.width, merged.height)
        print("RESIZED PIXELS:", merged.width * merged.height)
    merged.save(out_path, format="JPEG", quality=85, optimize=True)
    return str(out_path)


# -----------------------------
# size_table 캡처 (기존 안정화 로직 유지 + size-guide 추가)
# -----------------------------
def capture_size_table_jpg(url: str, out_jpg: Path, progress_cb=None, *, browser=None) -> str | None:
    """
    ✅ size_table이 있을 때만 images/size_table.jpg 생성
    ✅ 없으면 None 유지

    ✅ 추가:
      - "사이즈 가이드" 아코디언 내부에서
        - table#size-guide
        - div.size-guide-rf (이미지형 조견표)
        도 탐색
      - 위 두 개는 "프리뷰(HTML 문자열) 캡처" 방식으로 저장(파일 생성 없음)

    ✅ 최적화 포인트:
      - browser가 주어지면(=job에서 1회만 launch), 새 context/page만 만들어 사용 후 닫음
      - browser가 없으면 기존처럼 내부에서 sync_playwright + launch
    """

    def progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    def _impl(page):
        def wait_visible(locator, timeout=6000):
            try:
                locator.wait_for(state="attached", timeout=timeout)
            except Exception:
                return False
            try:
                page.wait_for_function(
                    """(el) => {
                        if (!el) return false;
                        const cs = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        return cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0'
                               && r.width > 5 && r.height > 5;
                    }""",
                    arg=locator.element_handle(),
                    timeout=timeout,
                )
                return True
            except Exception:
                return False

        def shot_live(locator):
            out_jpg.parent.mkdir(parents=True, exist_ok=True)
            locator.screenshot(path=str(out_jpg), type="jpeg", quality=98)
            return str(out_jpg)

        def _wait_fonts_and_images(preview_page, timeout_ms: int = 12000):
            try:
                preview_page.wait_for_function(
                    "() => !document.fonts || document.fonts.status === 'loaded'",
                    timeout=timeout_ms,
                )
            except Exception:
                pass
            try:
                preview_page.wait_for_function(
                    """() => {
                        const imgs = Array.from(document.images || []);
                        if (imgs.length === 0) return true;
                        return imgs.every(img => img.complete && img.naturalWidth > 0);
                    }""",
                    timeout=timeout_ms,
                )
            except Exception:
                pass

        def _extract_with_computed_inline(el_handle) -> str | None:
            try:
                return page.evaluate(
                    """(el) => {
                        if (!el) return null;

                        const clone = el.cloneNode(true);

                        function* walk(node) {
                          const tw = document.createTreeWalker(node, NodeFilter.SHOW_ELEMENT, null);
                          let cur = tw.currentNode;
                          while (cur) { yield cur; cur = tw.nextNode(); }
                        }

                        const origList = Array.from(walk(el));
                        const cloneList = Array.from(walk(clone));

                        for (let i = 0; i < cloneList.length; i++) {
                          const o = origList[i];
                          const c = cloneList[i];
                          const cs = window.getComputedStyle(o);

                          let styleText = "";
                          for (const prop of cs) {
                            styleText += prop + ":" + cs.getPropertyValue(prop) + ";";
                          }
                          c.setAttribute("style", styleText);
                        }

                        clone.querySelectorAll("img[loading='lazy']").forEach(img => img.removeAttribute("loading"));
                        clone.querySelectorAll("source[loading='lazy']").forEach(s => s.removeAttribute("loading"));

                        const wrapper = document.createElement("div");
                        wrapper.id = "capture-root";
                        wrapper.style.cssText = "display:inline-block;background:#fff;margin:0;padding:16px;box-sizing:border-box;";
                        wrapper.appendChild(clone);
                        return wrapper.outerHTML;
                    }""",
                    el_handle,
                )
            except Exception:
                return None

        def shot_preview(locator, *, base_href: str) -> str | None:
            out_jpg.parent.mkdir(parents=True, exist_ok=True)

            try:
                el = locator.element_handle()
            except Exception:
                el = None
            if not el:
                return None

            extracted = _extract_with_computed_inline(el)
            if not extracted:
                return None

            html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<base href="{base_href}">
<style>
  html, body {{ margin:0; padding:0; background:#fff; }}
  #capture-root, #capture-root * {{
    -webkit-font-smoothing: antialiased !important;
    text-rendering: geometricPrecision !important;
  }}
</style>
</head>
<body>
{extracted}
</body>
</html>"""

            preview = page.context.new_page()
            try:
                preview.set_content(html_doc, wait_until="domcontentloaded")
                _wait_fonts_and_images(preview, timeout_ms=12000)
                preview.wait_for_selector("#capture-root", timeout=10000)
                preview.wait_for_timeout(200)
                preview.locator("#capture-root").screenshot(path=str(out_jpg), type="jpeg", quality=98)
                return str(out_jpg)
            finally:
                try:
                    preview.close()
                except Exception:
                    pass

        def is_text_size_like(text: str) -> bool:
            t = (text or "").strip()
            if len(t) < 60:
                return False
            nums = re.findall(r"\d+", t)
            if len(nums) < 6:
                return False
            if t.count("\n") < 2:
                return False
            bad_words = ["오차", "측정", "참고", "방법에 따라", "개인차"]
            bad_hits = sum(1 for w in bad_words if w in t)
            if bad_hits >= 2 and len(nums) < 10:
                return False
            return True

        progress("사이즈 테이블을 확인 중입니다.")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(500)

        opened_detail = None
        for kw in ["사이즈 가이드", "사이즈", "SIZE GUIDE", "SIZE", "Size"]:
            a = page.locator("div.ac-title a", has_text=kw).first
            if a.count() == 0:
                continue

            ac_title = a.locator("xpath=ancestor::div[contains(@class,'ac-title')][1]")
            ac_detail = ac_title.locator("xpath=following-sibling::div[contains(@class,'ac-detail')][1]")

            try:
                is_active = ac_title.evaluate("el => el.classList.contains('active')")
            except Exception:
                is_active = False

            if not is_active:
                try:
                    a.click(timeout=1500)
                    page.wait_for_timeout(250)
                except Exception:
                    pass

            if ac_detail.count() > 0:
                opened_detail = ac_detail
            break

        root = opened_detail if (opened_detail is not None and opened_detail.count() > 0) else page.locator("div.detail-con.left-con").first
        if root.count() == 0:
            return None

        try:
            root.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(150)

        # ✅ size-guide(테이블/이미지 조견표) 탐색 (프리뷰 캡처)
        loc = root.locator("table#size-guide").first
        if loc.count() > 0 and wait_visible(loc, timeout=4000):
            try:
                txt = (loc.inner_text(timeout=800) or "").strip()
            except Exception:
                txt = ""
            if len(txt) >= 20:
                p = shot_preview(loc, base_href=url)
                if p:
                    return p

        rf = root.locator("div.size-guide-rf").first
        if rf.count() > 0 and wait_visible(rf, timeout=4000):
            try:
                page.wait_for_function(
                    """(el) => {
                        const img = el.querySelector('img');
                        if (!img) return true;
                        return img.complete && img.naturalWidth > 0;
                    }""",
                    arg=rf.element_handle(),
                    timeout=6000,
                )
            except Exception:
                pass

            p = shot_preview(rf, base_href=url)
            if p:
                return p

        # 기존 로직(그대로): 라이브 캡처
        loc = root.locator("table#actl-size").first
        if loc.count() > 0 and wait_visible(loc, timeout=4000):
            return shot_live(loc)

        loc = root.locator("table", has=root.locator("th", has_text="사이즈")).first
        if loc.count() > 0 and wait_visible(loc, timeout=4000):
            return shot_live(loc)

        candidates = [
            "div.detail-table:has-text('사이즈')",
            "div.detail-table:has-text('SIZE')",
            "p:has-text('사이즈')",
            "li:has-text('사이즈')",
            "div:has-text('사이즈')",
        ]
        for sel in candidates:
            blk = root.locator(sel).first
            if blk.count() == 0:
                continue
            if not wait_visible(blk, timeout=2500):
                continue
            try:
                txt = blk.inner_text(timeout=1200)
            except Exception:
                txt = ""
            if not is_text_size_like(txt):
                continue
            return shot_live(blk)

        return None

    if browser is not None:
        try:
            ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
            page = ctx.new_page()
            try:
                return _impl(page)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception:
            return None

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                ctx = b.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
                page = ctx.new_page()
                try:
                    return _impl(page)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
            finally:
                try:
                    b.close()
                except Exception:
                    pass
    except Exception:
        return None


# -----------------------------
# size 옵션 추출(JSON 추가)
# -----------------------------
def _parse_addorder_args(href: str) -> list[str]:
    """
    href 예: javascript:addOrder('M', '199,000', 'Black', '1', '04','35','36', '10');
    -> 따옴표 안의 값들만 순서대로 추출
    """
    if not href:
        return []
    m = re.search(r"addOrder\s*\((.*)\)", href)
    if not m:
        return []
    inside = m.group(1)
    tokens = re.findall(r"'([^']*)'|\"([^\"]*)\"", inside)
    out: list[str] = []
    for a, b in tokens:
        out.append(a if a != "" else b)
    return out


def extract_size_options(url: str, progress_cb=None, *, browser=None) -> list[dict]:
    """
    ✅ 옵션 “사이즈를 선택하세요.” 클릭 후 나오는 ul[name="size-li"] 항목을 추출해서 JSON에 저장
    ✅ 실패/미존재 시 [] 반환 (기존 기능 영향 없음)
    """

    def progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    def _impl(page) -> list[dict]:
        progress("사이즈 옵션 목록을 확인 중입니다.")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(500)

        trigger = page.locator("a.select-option", has_text="사이즈").first
        if trigger.count() == 0:
            trigger = page.locator("a.select-option", has_text="선택").first

        if trigger.count() > 0:
            try:
                trigger.click(timeout=2000)
            except Exception:
                pass

        ul = page.locator("ul[name='size-li']").first
        try:
            ul.wait_for(state="attached", timeout=2000)
        except Exception:
            return []

        page.wait_for_timeout(100)

        links = page.locator("ul[name='size-li'] li a")
        cnt = links.count()
        if cnt == 0:
            return []

        out: list[dict] = []
        for i in range(cnt):
            a = links.nth(i)
            try:
                label = (a.text_content() or "").strip()
            except Exception:
                label = ""
            if not label:
                continue

            try:
                href = a.get_attribute("href") or ""
            except Exception:
                href = ""

            out.append(
                {
                    "label": label,
                    "href": href,
                    "addOrder_args": _parse_addorder_args(href),
                }
            )

        return out

    if browser is not None:
        try:
            ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
            page = ctx.new_page()
            try:
                return _impl(page)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception:
            return []

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                ctx = b.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
                page = ctx.new_page()
                try:
                    return _impl(page)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
            finally:
                try:
                    b.close()
                except Exception:
                    pass
    except Exception:
        return []


# -----------------------------
# ✅ 추가: gvnt-info(상품정보제공고시) 클릭 후 추출 (2차 fallback)
# -----------------------------
def extract_gvnt_info_click(url: str, progress_cb=None, *, browser=None) -> dict:
    """
    ✅ '상품정보제공고시' 아코디언을 클릭해서 열린 DOM에서 ul#gvnt-info를 dict로 추출
    ✅ 실패/미존재 시 {} 반환
    ✅ browser가 주어지면(job당 1회 launch) 재사용
    """

    def progress(msg: str):
        if progress_cb:
            progress_cb(msg)

    def _pick_first(d: dict, keys: list[str]) -> str | None:
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            v = str(v).strip()
            if v:
                return v
        return None

    def _impl(page) -> dict:
        progress("상품정보제공고시(클릭) 정보를 확인 중입니다.")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(700)

        title = page.locator("div.ac-title a", has_text="상품정보제공고시").first
        if title.count() == 0:
            return {}

        ac_title = title.locator("xpath=ancestor::div[contains(@class,'ac-title')][1]")
        ac_detail = ac_title.locator("xpath=following-sibling::div[contains(@class,'ac-detail')][1]")

        try:
            ac_detail.wait_for(state="attached", timeout=8000)
        except Exception:
            return {}

        try:
            is_active = ac_title.evaluate("el => el.classList.contains('active')")
        except Exception:
            is_active = False

        if not is_active:
            try:
                title.click(timeout=2500)
                page.wait_for_timeout(250)
            except Exception:
                pass

        try:
            page.wait_for_function(
                """(el) => {
                    if (!el) return false;
                    const cs = getComputedStyle(el);
                    return cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
                }""",
                arg=ac_detail.element_handle(),
                timeout=8000,
            )
        except Exception:
            pass

        ul = ac_detail.locator("ul#gvnt-info, #gvnt-info").first
        try:
            ul.wait_for(state="attached", timeout=5000)
        except Exception:
            return {}

        try:
            gvnt_info = ul.evaluate(
                """(root) => {
                    const out = {};
                    if (!root) return out;
                    const lis = Array.from(root.querySelectorAll("li"));
                    for (const li of lis) {
                        const k = li.querySelector("strong");
                        const v = li.querySelector("p");
                        const key = (k?.innerText || "").trim();
                        const val = (v?.innerText || "").trim();
                        if (key) out[key] = val;
                    }
                    return out;
                }"""
            ) or {}
        except Exception:
            gvnt_info = {}

        manufacturer = _pick_first(
            gvnt_info,
            ["제조사", "제조자", "제조원", "제조사/수입자", "제조자/수입자"],
        )
        manufacturing_ym = _pick_first(
            gvnt_info,
            [        "제조연월(수입연월)", "제조연월", "제조년월",],
        )
        made_in = _pick_first(
            gvnt_info,
            ["제조국", "원산지", "제조국/원산지", "원산지(제조국)"],
        )

        return {
            "gvnt_info": gvnt_info,
            "제조사": manufacturer,
            "제조연월(수입연월)": manufacturing_ym,
            "제조국": made_in,
            "mode_gvnt": "playwright_click",
        }

    if browser is not None:
        try:
            ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
            page = ctx.new_page()
            try:
                return _impl(page)
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception:
            return {}

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {}

    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                ctx = b.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
                page = ctx.new_page()
                try:
                    return _impl(page)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
            finally:
                try:
                    b.close()
                except Exception:
                    pass
    except Exception:
        return {}


# -----------------------------
# 렌더 타겟(기존 유지)
# -----------------------------
DEFAULT_ACCORDIONS = [
    "상품정보제공고시",
    "소재 및 관리방법",
]

DEFAULT_SELECTORS = [
    ("MD_COMMENT", "div.prd-detail-box.on"),
]

REPLAY_TITLES = ["상품정보제공고시"]


def run_job(job_id: str, code: str):
    try:
        started = datetime.now().isoformat(timespec="seconds")

        def progress(msg: str):
            _set_job(job_id, status=msg)

        goods_code = sanitize_goods_code(code)
        if not goods_code:
            raise ValueError("품번이 비어있습니다.")

        url = build_goods_url(goods_code)

        progress(f"데이터를 수집하고 있습니다. (URL: {url})")
        data = scrape_kvillage_requests(url, progress_cb=progress)

        code_safe = safe_filename(data.get("code") or goods_code or "UNKNOWN")
        out_dir = BASE_OUT / code_safe
        out_dir.mkdir(parents=True, exist_ok=True)

        img_dir = out_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        browser = None
        pw = None
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
        except Exception:
            browser = None
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass
                pw = None

        try:
            # 1) 사이즈 옵션
            size_options = extract_size_options(url, progress_cb=progress, browser=browser)

            # 2) 사이즈 테이블(또는 size-guide)
            size_table_path = capture_size_table_jpg(
                url,
                img_dir / "size_table.jpg",
                progress_cb=progress,
                browser=browser,
            )

            # 3) ✅ 2차 fallback: 제조국/제조연월이 비었으면 클릭 기반으로 채움
            need_gvnt = not (str(data.get("제조연월(수입연월)") or "").strip()) or not (str(data.get("제조국") or "").strip())
            if need_gvnt:
                gv = extract_gvnt_info_click(url, progress_cb=progress, browser=browser)
                if gv:
                    if not data.get("gvnt_info"):
                        data["gvnt_info"] = gv.get("gvnt_info") or {}
                    if not (str(data.get("제조사") or "").strip()):
                        data["제조사"] = gv.get("제조사")
                    if not (str(data.get("제조연월(수입연월)") or "").strip()):
                        data["제조연월(수입연월)"] = gv.get("제조연월(수입연월)")
                    if not (str(data.get("제조국") or "").strip()):
                        data["제조국"] = gv.get("제조국")
                    data["mode_gvnt"] = gv.get("mode_gvnt", "playwright_click")

        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass

        progress("pd-photo 이미지를 다운로드하고 있습니다.")
        downloaded = download_images(data.get("pd_photo_image_urls", []), img_dir, prefix="pd")

        progress("아코디언/영역을 렌더링하여 이미지로 저장 중입니다. (페이지는 표시되지 않음)")
        try:
            accordion_results = render_targets_hybrid(
                url=url,
                accordion_titles=DEFAULT_ACCORDIONS,
                css_selectors=DEFAULT_SELECTORS,
                out_dir=out_dir,
                target_w=1100,
                progress_cb=progress,
                replay_titles=REPLAY_TITLES,
            )
        except Exception as e:
            accordion_results = [{"ok": False, "error": f"renderer failed: {e}"}]

        progress("pd-photo 합본 이미지를 생성하고 있습니다.")
        merge_list = [Path(p) for p in downloaded]
        if data.get("saved_size_table_jpg") or size_table_path:
            # 이전 값이 있으면 우선
            st = data.get("saved_size_table_jpg") or size_table_path
            if st:
                merge_list.append(Path(st))
        merged_path = merge_images_vertical_jpg(merge_list, img_dir / "pd_photo_merged.jpg")

        data["source_url"] = url
        data["input_code"] = goods_code

        data["saved_images_each"] = downloaded
        data["saved_images_merged"] = merged_path
        data["saved_size_table_jpg"] = size_table_path
        data["saved_accordion_renders"] = accordion_results

        data["size_options"] = size_options
        data["saved_at"] = started

        with open(out_dir / "product.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        progress("완료되었습니다.")
        _set_job(
            job_id,
            done=True,
            error=None,
            result_summary={
                "url": url,
                "code": code_safe,
                "title": data.get("title"),
                "sale_price": data.get("sale_price"),
                "list_price": data.get("list_price"),
                "saved_json": str(out_dir / "product.json"),
                "saved_images_each": downloaded,
                "saved_images_merged": merged_path,
                "saved_size_table_jpg": size_table_path,
                "renders_html_dir": f"out/{code_safe}/renders/html",
                "renders_png_dir": f"out/{code_safe}/renders/png",
                "renders_jpg_dir": f"out/{code_safe}/renders/jpg",
                "saved_accordion_renders": accordion_results,
                "size_options_count": len(size_options),
                "mode_gvnt": data.get("mode_gvnt"),
                "제조국": data.get("제조국"),
                "제조연월": data.get("제조연월(수입연월)"),
            },
        )

    except Exception as e:
        _set_job(job_id, done=True, error=str(e), status="오류가 발생했습니다.")


# ---------------- UI ----------------
@app.get("/", response_class=HTMLResponse)
def home():
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>이미지 수집</title>
  <style>
    body{{font-family:system-ui,Segoe UI,Arial;max-width:900px;margin:40px auto;padding:0 16px}}
    input{{width:100%;padding:12px;font-size:16px}}
    button{{padding:10px 14px;font-size:16px;cursor:pointer;margin-top:10px}}
    .card{{border:1px solid #ddd;border-radius:10px;padding:16px;margin-top:16px}}
    .status{{margin-top:14px;padding:12px;border:1px dashed #aaa;border-radius:10px;min-height:48px;display:flex;align-items:center}}
    .muted{{color:#666}}
    .prefix{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#444;margin:8px 0 6px 0}}
  </style>
</head>
<body>
  <h2>이미지 수집</h2>

  <div class="card">
    <form id="f">
      <div class="muted">상품 URL</div>
      <div class="prefix"><code>{GOODS_PREFIX}</code></div>
      <input name="code" placeholder="품번과색상을 입력하세요" autocomplete="off" required />
      <button type="submit">실행</button>
    </form>
    <div class="status" id="status" style="display:none;">대기중</div>
  </div>

<script>
const f = document.getElementById("f");
const statusBox = document.getElementById("status");

f.addEventListener("submit", async (e) => {{
  e.preventDefault();
  statusBox.style.display = "flex";
  statusBox.textContent = "요청을 시작하고 있습니다.";

  const body = new FormData(f);
  const res = await fetch("/run_async", {{ method: "POST", body }});
  const js = await res.json();

  if (!js.job_id) {{
    statusBox.textContent = "작업을 시작하지 못했습니다.";
    return;
  }}
  location.href = "/progress/" + js.job_id;
}});
</script>
</body>
</html>
"""


@app.post("/run_async")
def run_async(code: str = Form(...)):
    job_id = uuid.uuid4().hex
    _set_job(job_id, status="작업을 준비하고 있습니다.", done=False, error=None, result_summary=None)
    t = threading.Thread(target=run_job, args=(job_id, code), daemon=True)
    t.start()
    return JSONResponse({"job_id": job_id})


@app.get("/progress/{job_id}", response_class=HTMLResponse)
def progress_page(job_id: str):
    html = """
<!doctype html>
<html>
<head><meta charset="utf-8"/><title>Progress</title></head>
<body style="font-family:system-ui,Segoe UI,Arial;max-width:900px;margin:40px auto;padding:0 16px">
  <h2>진행중</h2>
  <p><a href="http://127.0.0.1:8000/collector/">← 홈</a></p>
  <div id="status" style="border:1px dashed #aaa;border-radius:10px;padding:12px;min-height:48px;display:flex;align-items:center">상태 확인중...</div>

<script>
const statusEl = document.getElementById("status");
const jobId = "__JOB_ID__";

async function tick() {
  try {
    const res = await fetch("/status/" + jobId);
    const js = await res.json();

    if (js.status) statusEl.textContent = js.status;

    if (js.done) {
      if (js.error) statusEl.textContent = "오류: " + js.error;
      else location.href = "/result/" + jobId;
    }
  } catch(e) {
    statusEl.textContent = "상태 확인 실패: " + e;
  }
}

setInterval(tick, 500);
tick();
</script>
</body>
</html>
"""
    return html.replace("__JOB_ID__", job_id)


@app.get("/status/{job_id}")
def status(job_id: str):
    job = _get_job(job_id)
    if not job:
        return JSONResponse({"status": "job not found", "done": True, "error": "job not found"})
    return JSONResponse({"status": job.get("status"), "done": job.get("done", False), "error": job.get("error")})


@app.get("/result/{job_id}", response_class=HTMLResponse)
def result(job_id: str):
    job = _get_job(job_id)
    if not job:
        return f"<p>job not found: {job_id}</p>"

    if job.get("error"):
        return f"<p><b>오류:</b> {job.get('error')}</p><p><a href='http://127.0.0.1:8000/collector/'>← 홈</a></p>"

    r = job.get("result_summary") or {}
    saved_each = r.get("saved_images_each") or []

    def li(x):
        return f"<li><code>{x}</code></li>"

    each_list = "".join(li(p) for p in saved_each[:50])
    if len(saved_each) > 50:
        each_list += f"<li>... (+{len(saved_each)-50} more)</li>"

    return f"""
<!doctype html>
<html>
<head><meta charset='utf-8'/><title>Result</title></head>
<body style='font-family:system-ui,Segoe UI,Arial;max-width:1000px;margin:40px auto;padding:0 16px'>
  <h2>완료</h2>
  <p><a href='http://127.0.0.1:8000/collector/'>← 홈</a></p>

  <h3>요약</h3>
  <ul>
    <li><b>URL</b>: <code>{r.get('url')}</code></li>
    <li><b>코드</b>: <code>{r.get('code')}</code></li>
    <li><b>상품명</b>: {r.get('title')}</li>
    <li><b>판매가</b>: {r.get('sale_price')}</li>
    <li><b>정가</b>: {r.get('list_price')}</li>
    <li><b>사이즈 옵션 수</b>: {r.get('size_options_count')}</li>
    <li><b>GVNT 모드</b>: {r.get('mode_gvnt')}</li>
    <li><b>제조국</b>: {r.get('제조국')}</li>
    <li><b>제조연월(수입연월)</b>: {r.get('제조연월(수입연월)')}</li>
    <li><b>product.json</b>: <code>{r.get('saved_json')}</code></li>
  </ul>

  <h3>저장된 이미지</h3>
  <ul>
    <li><b>pd-photo 최종 합본</b>: <code>{r.get('saved_images_merged')}</code></li>
    <li><b>사이즈 표 JPG (없을 수 있음)</b>: <code>{r.get('saved_size_table_jpg')}</code></li>
  </ul>

  <h3>pd-photo 개별 이미지(최대 50개 표시)</h3>
  <ul>{each_list}</ul>

  <h3>렌더 결과 폴더</h3>
  <ul>
    <li>HTML: <code>{r.get('renders_html_dir')}</code></li>
    <li>PNG: <code>{r.get('renders_png_dir')}</code></li>
    <li>JPG: <code>{r.get('renders_jpg_dir')}</code></li>
  </ul>
</body>
</html>
"""
