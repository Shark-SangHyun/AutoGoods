# renderer_kvillage.py (optimized, behavior-preserving)
# 핵심 원칙:
# - UI 폼/실행결과(저장되는 html/png/jpg 내용) 변경 없음
# - 호출부(app.py)는 수정 없이 그대로 동작
# - "의미 있는" 최적화는 결과에 영향을 주지 않는 범위에서만 적용
#
# 적용한 최적화(동작 동일):
# 1) replay_titles가 비어있을 때는 원본 CSS 수집/문자열 조합을 생략 (save_replay가 호출되지 않으므로 결과 동일)
# 2) 정규식/헬퍼의 불필요한 중복 호출을 줄이기 위한 미세 정리(결과 동일)
#
# ✅ 사용자 요청 추가:
# - MD_COMMENT.jpg(= selector 타겟) 영역 글씨를 "조금 작게" 저장
#   -> save_inline에서 slug가 MD_COMMENT일 때만 #capture-root font-size/line-height를 오버라이드
#
# 주의: 렌더 결과를 바꿀 수 있는 최적화(대기시간 변경, 캡처 방식 변경, page 재사용/병렬)는 하지 않음.

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional, Iterable, Tuple, List, Dict, Any

from playwright.sync_api import sync_playwright

ProgressCB = Optional[Callable[[str], None]]

_RE_SPACE = re.compile(r"\s+")


def safe_filename(name: str) -> str:
    name = (name or "").strip()
    name = _RE_SPACE.sub("_", name)
    name = "".join(c for c in name if c.isalnum() or c in ("-", "_"))[:120]
    return name or "file"


def _wait_fonts_and_images(page, timeout_ms: int = 9000) -> None:
    # 폰트 로딩 대기
    try:
        page.wait_for_function("() => document.fonts && document.fonts.status === 'loaded'", timeout=timeout_ms)
    except Exception:
        pass

    # 이미지 로딩 대기(가능한 범위)
    try:
        page.wait_for_function(
            """() => {
              const imgs = Array.from(document.images || []);
              if (imgs.length === 0) return true;
              return imgs.every(img => img.complete && img.naturalWidth > 0);
            }""",
            timeout=timeout_ms,
        )
    except Exception:
        pass


def _extract_with_computed_inline(page, element_handle) -> str:
    """
    - element clone
    - getComputedStyle 전체를 clone에 inline style로 주입
    - lazy 제거
    - wrapper(#capture-root)로 감싼 HTML 반환
    """
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
        element_handle,
    )


def _extract_outerhtml_only(page, element_handle) -> str:
    """replay용: outerHTML만 추출"""
    return page.evaluate("(el) => el ? el.outerHTML : null", element_handle)


def render_targets_hybrid(
    url: str,
    accordion_titles: Iterable[str],
    css_selectors: Iterable[Tuple[str, str]],
    out_dir: Path,
    target_w: int = 1100,
    progress_cb: ProgressCB = None,
    replay_titles: Optional[Iterable[str]] = None,  # ✅ 여기 포함된 title만 replay로 저장
) -> List[Dict[str, Any]]:
    """
    Hybrid 저장:
    - 기본: computed-inline 방식 (원본 느낌 최대)
    - replay_titles에 포함된 아코디언 title은: replay 방식(outerHTML + 원본 CSS 로드)로 저장
      -> '상품정보제공고시' 같은 오버랩 문제에 유리
    - selector 타겟(MD COMMENT 등)은 computed-inline로 저장
    """

    def progress(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    replay_set = set([t.strip() for t in (replay_titles or []) if (t or "").strip()])

    results: List[Dict[str, Any]] = []

    renders_dir = out_dir / "renders"
    html_dir = renders_dir / "html"
    png_dir = renders_dir / "png"
    jpg_dir = renders_dir / "jpg"
    html_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)
    jpg_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # ✅ 창 안 뜸
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, device_scale_factor=2)
        page = ctx.new_page()

        progress(f"페이지 로드: {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(900)

        # ✅ (최적화) replay 저장이 하나도 없으면, 원본 CSS 수집/문자열 조합을 생략해도 결과 동일
        # - save_replay가 호출되지 않으므로 links_html/styles_html/base_href는 필요 없음
        base_href = url
        links_html = ""
        styles_html = ""
        if replay_set:
            base_payload = page.evaluate("""() => {
                const styleTags = Array.from(document.querySelectorAll("style"))
                  .map(s => s.textContent || "")
                  .filter(t => t.trim().length > 0);

                const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
                  .map(l => l.href)
                  .filter(Boolean);

                return { styleTags, links, baseHref: location.href };
            }""")

            style_tags = base_payload["styleTags"]
            css_links = base_payload["links"]
            base_href = base_payload["baseHref"]

            links_html = "\n".join([f'<link rel="stylesheet" href="{href}">' for href in css_links])
            styles_html = "\n".join([f"<style>\n{t}\n</style>" for t in style_tags])
        else:
            # inline 저장에서도 base href는 필요하므로 현재 페이지 href를 사용
            try:
                base_href = page.evaluate("() => location.href")
            except Exception:
                base_href = url

        def _scale_root(preview_page):
            preview_page.evaluate(
                """(targetW) => {
                    const root = document.querySelector('#capture-root');
                    if (!root) return;

                    const actual = root.scrollWidth || root.getBoundingClientRect().width;
                    if (!actual) return;

                    const s = Math.min(1.0, targetW / actual);
                    root.style.transformOrigin = 'top left';
                    root.style.transform = `scale(${s})`;

                     // ✅ MD_COMMENT: 폭 스케일에 맞춰 폰트 자동 보정
                    // - base 폰트는 CSS 변수(--md-base-font)로 주고
                    // - 보정값 = base / s (너무 과해지지 않게 clamp)
                    const base = Number(getComputedStyle(root).getPropertyValue('--md-base-font')) || 0;
                    if (base > 0) {
                    const corrected = base / (s || 1);
                    const clamped = Math.max(12, Math.min(16, corrected)); // 필요하면 범위 조절
                    root.style.fontSize = clamped.toFixed(2) + 'px';
                    }

                    const rect = root.getBoundingClientRect();
                    document.documentElement.style.width = Math.ceil(rect.width) + 'px';
                    document.documentElement.style.height = Math.ceil(rect.height) + 'px';
                    document.body.style.width = Math.ceil(rect.width) + 'px';
                    document.body.style.height = Math.ceil(rect.height) + 'px';
                }""",
                target_w,
            )

        def save_inline(name: str, extracted_html: str) -> Dict[str, Any]:
            slug = safe_filename(name)
            html_path = html_dir / f"{slug}.html"
            png_path = png_dir / f"{slug}.png"
            jpg_path = jpg_dir / f"{slug}.jpg"

            # ✅ MD_COMMENT 전용: 글씨 약간 축소 (요청 반영)
            md_comment_css = ""
            if slug.upper() == "MD_COMMENT":
                md_comment_css = """
  /* MD_COMMENT 전용: 글씨 약간 축소 */
  #capture-root { --md-base-font: 11; line-height: 1.55 !important; }
"""

            html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<base href="{base_href}">
<style>
  html, body {{ margin:0; padding:0; background:#fff; }}
  #capture-root {{ line-height: 1.65; }}
{md_comment_css}
</style>
</head>
<body>
{extracted_html}
</body>
</html>"""
            html_path.write_text(html_doc, encoding="utf-8")

            preview = ctx.new_page()
            preview.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
            _wait_fonts_and_images(preview, timeout_ms=9000)
            preview.wait_for_timeout(250)
            preview.wait_for_selector("#capture-root", timeout=10000)

            _scale_root(preview)
            preview.wait_for_timeout(150)

            root = preview.locator("#capture-root")
            root.screenshot(path=str(png_path), type="png")
            root.screenshot(path=str(jpg_path), type="jpeg", quality=98)
            preview.close()

            return {
                "ok": True,
                "title": name,
                "mode": "inline",
                "html": str(html_path),
                "png": str(png_path),
                "jpg": str(jpg_path),
            }

        def save_replay(name: str, outer_html: str) -> Dict[str, Any]:
            # replay_set이 있는 경우에만 호출되므로 links_html/styles_html이 준비되어 있음
            slug = safe_filename(name)
            html_path = html_dir / f"{slug}.html"
            png_path = png_dir / f"{slug}.png"
            jpg_path = jpg_dir / f"{slug}.jpg"

            html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<base href="{base_href}">
{links_html}
{styles_html}
<style>
  html, body {{ margin:0; padding:0; background:#fff; }}

  #capture-root {{
    background:#fff;
    margin:0;
    padding:24px;
    box-sizing:border-box;
    display:block;
  }}

  /* 🔹 상품정보제공고시 가독성 전용 보정 */
  #capture-root {{
    font-size: 15px !important;
    line-height: 1.9 !important;
  }}

  #capture-root strong,
  #capture-root th {{
    font-weight: 600 !important;
    color: #222 !important;
  }}

  #capture-root p,
  #capture-root td {{
    color: #444 !important;
  }}

  #capture-root li {{
    margin-bottom: 10px !important;
  }}

  #capture-root ul {{
    padding-left: 18px !important;
  }}

  /* 렌더링 품질 */
  #capture-root, #capture-root * {{
    -webkit-font-smoothing: antialiased !important;
    text-rendering: geometricPrecision !important;
  }}
</style>
</head>
<body>
  <div id="capture-root">
    {outer_html}
  </div>
</body>
</html>"""
            html_path.write_text(html_doc, encoding="utf-8")

            preview = ctx.new_page()
            preview.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")

            _wait_fonts_and_images(preview, timeout_ms=12000)
            preview.wait_for_timeout(300)
            preview.wait_for_selector("#capture-root", timeout=10000)

            _scale_root(preview)
            preview.wait_for_timeout(150)

            root = preview.locator("#capture-root")
            root.screenshot(path=str(png_path), type="png")
            root.screenshot(path=str(jpg_path), type="jpeg", quality=98)
            preview.close()

            return {
                "ok": True,
                "title": name,
                "mode": "replay",
                "html": str(html_path),
                "png": str(png_path),
                "jpg": str(jpg_path),
            }

        # ---------------------------
        # A) 아코디언 처리
        # ---------------------------
        for title_text in accordion_titles:
            title_text = (title_text or "").strip()
            if not title_text:
                continue

            progress(f"아코디언 처리: {title_text}")

            title = page.locator("div.ac-title a", has_text=title_text).first
            if title.count() == 0:
                results.append({"ok": False, "title": title_text, "error": "accordion title not found"})
                continue

            ac_title = title.locator("xpath=ancestor::div[contains(@class,'ac-title')][1]")
            ac_detail = ac_title.locator("xpath=following-sibling::div[contains(@class,'ac-detail')][1]")
            ac_detail.wait_for(state="attached", timeout=10000)

            # 닫혀있으면 클릭
            if not ac_title.evaluate("el => el.classList.contains('active')"):
                title.click()
                page.wait_for_timeout(350)

            # visible 대기
            page.wait_for_function(
                """(el) => {
                    if (!el) return false;
                    const cs = getComputedStyle(el);
                    return cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
                }""",
                arg=ac_detail.element_handle(),
                timeout=10000,
            )

            # 폰트 대기(원본 페이지에서)
            try:
                page.wait_for_function("() => document.fonts && document.fonts.status === 'loaded'", timeout=7000)
            except Exception:
                pass

            # ✅ title별 저장 방식 선택
            if title_text in replay_set:
                outer_html = _extract_outerhtml_only(page, ac_detail.element_handle())
                if not outer_html:
                    results.append({"ok": False, "title": title_text, "error": "outerHTML extract failed"})
                    continue
                results.append(save_replay(title_text, outer_html))
            else:
                extracted = _extract_with_computed_inline(page, ac_detail.element_handle())
                if not extracted:
                    results.append({"ok": False, "title": title_text, "error": "inline extract failed"})
                    continue
                results.append(save_inline(title_text, extracted))

        # ---------------------------
        # B) selector 타겟 처리(MD COMMENT 등) - inline 고정
        # ---------------------------
        for save_name, selector in css_selectors:
            save_name = (save_name or "").strip()
            selector = (selector or "").strip()
            if not save_name or not selector:
                continue

            progress(f"DIV 처리: {save_name} ({selector})")

            loc = page.locator(selector).first
            if loc.count() == 0:
                results.append({"ok": False, "title": save_name, "error": f"selector not found: {selector}"})
                continue

            try:
                loc.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            extracted = _extract_with_computed_inline(page, loc.element_handle())
            if not extracted:
                results.append({"ok": False, "title": save_name, "error": "inline extract failed"})
                continue

            results.append(save_inline(save_name, extracted))

        browser.close()

    return results
