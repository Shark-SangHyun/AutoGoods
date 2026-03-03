"""
Selenium automation for Naver SmartStore.

- Category selection: existing 방식 유지
- Product name typing: input[name="product.name"]
- Sale price typing: #prd_price2
- No API bypass: all actions are UI interactions

+ Debug helpers added for "직접 입력하기" failure diagnosis:
  - debug_direct_input_state()
  - set_option_config_true_and_direct_input() now prints debug before/after direct click failure
"""

from typing import Optional,Any
from pathlib import Path
import time
import detail_editor
import os
import re
import json

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.action_chains import ActionChains

SMARTSTORE_URL = "https://sell.smartstore.naver.com/#/home/about"
_driver: Optional[webdriver.Chrome] = None


def _new_driver() -> webdriver.Chrome:
    opts = Options()

    # ✅ 로그인 세션 유지용 프로필(있으면 사용)
    base_dir = Path(__file__).resolve().parent
    profile_dir = base_dir / "chrome_profile_shared"
    if profile_dir.exists():
        opts.add_argument(f"--user-data-dir={profile_dir}")
    else:
        opts.add_argument("--incognito")

    opts.add_argument("--start-maximized")

    prefs = {"profile.default_content_setting_values.notifications": 2}
    opts.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=opts)


def get_driver() -> webdriver.Chrome:
    global _driver
    if _driver is None:
        _driver = _new_driver()
    return _driver


def open_smartstore() -> None:
    d = get_driver()
    d.get(SMARTSTORE_URL)


def _safe_click(d: webdriver.Chrome, el) -> None:
    """기본 클릭 + intercept 시 JS click 폴백"""
    try:
        el.click()
    except ElementClickInterceptedException:
        d.execute_script("arguments[0].click();", el)


def _scroll_center(d: webdriver.Chrome, el) -> None:
    try:
        d.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
    except Exception:
        pass


def _dispatch_mouse_click(d: webdriver.Chrome, el) -> None:
    """mousedown→mouseup→click 시퀀스를 강제로 발생"""
    d.execute_script(
        """
        const el = arguments[0];
        const opts = {bubbles:true, cancelable:true, view:window};
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        """,
        el,
    )


# =========================================================
# DEBUG: Direct input ("직접 입력하기") diagnosis
# =========================================================
def debug_snapshot(tag: str) -> None:
    """실패 지점에서 무조건 남기는 스냅샷(콘솔+스크린샷)"""
    d = get_driver()
    ts = int(time.time())
    fn = f"debug_{tag}_{ts}.png".replace(" ", "_")

    print("\n=== SNAPSHOT ===")
    print("tag:", tag)
    try:
        print("url:", d.current_url)
    except Exception as e:
        print("url read fail:", e)

    scope_sel = "div.col-lg-11.col-sm-10.col-xs-8.input-content"
    try:
        scopes = d.find_elements(By.CSS_SELECTOR, scope_sel)
        vis = [s for s in scopes if s.is_displayed()]
        print("scope count:", len(scopes), "visible:", len(vis))
    except Exception as e:
        print("scope scan fail:", e)

    try:
        cnt_direct = len(d.find_elements(By.XPATH, "//input[@type='radio' and @value='direct']"))
        print("direct radio count (page-wide):", cnt_direct)
    except Exception as e:
        print("direct count fail:", e)

    try:
        d.save_screenshot(fn)
        print("screenshot saved:", fn)
    except Exception as e:
        print("screenshot failed:", e)

    print("=== END SNAPSHOT ===\n")


# =========================================================
# Option toggle + set config/direct input
# =========================================================
def click_option_menu_toggle() -> None:
    """
    '설정안함 메뉴토글' 영역에서 토글을 확실히 열기.
    성공 조건: target 내부 a.btn.btn-default에 'active' 클래스 포함
    """
    d = get_driver()
    wait = WebDriverWait(d, 25)

    scope_sel = "div.col-lg-11.col-sm-10.col-xs-8.input-content"
    div_sel = scope_sel + " div.set-option.no-set"
    a_rel = "a.btn.btn-default"

    def _has_active(div_el) -> bool:
        try:
            a = div_el.find_element(By.CSS_SELECTOR, a_rel)
            cls = (a.get_attribute("class") or "")
            return "active" in cls.split()
        except Exception:
            return False

    def _scroll_center_local(el) -> None:
        try:
            d.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
        except Exception:
            pass

    def _dispatch_mouse(el) -> None:
        d.execute_script(
            """
            const el = arguments[0];
            const opts = {bubbles:true, cancelable:true, view:window};
            el.dispatchEvent(new MouseEvent('mousedown', opts));
            el.dispatchEvent(new MouseEvent('mouseup', opts));
            el.dispatchEvent(new MouseEvent('click', opts));
            """,
            el,
        )

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, div_sel)))

    divs = [e for e in d.find_elements(By.CSS_SELECTOR, div_sel) if e.is_displayed()]
    if not divs:
        raise RuntimeError("no visible div.set-option.no-set found")

    # 화면 아래쪽(현재 작업 섹션) 우선
    try:
        divs.sort(key=lambda e: e.rect.get("y", -1), reverse=True)
    except Exception:
        pass

    target = divs[0]
    _scroll_center_local(target)
    time.sleep(0.15)

    a = target.find_element(By.CSS_SELECTOR, a_rel)
    _scroll_center_local(a)
    time.sleep(0.10)

    if _has_active(target):
        return

    last_err = None

    for _ in range(6):
        try:
            # 1) ActionChains
            try:
                ActionChains(d).move_to_element(a).pause(0.05).click().perform()
            except Exception as e:
                last_err = e

            time.sleep(0.15)
            if _has_active(target):
                return

            # 2) Selenium click
            try:
                a.click()
            except Exception as e:
                last_err = e

            time.sleep(0.15)
            if _has_active(target):
                return

            # 3) JS dispatch mouse
            try:
                _dispatch_mouse(a)
            except Exception as e:
                last_err = e

            time.sleep(0.15)
            if _has_active(target):
                return

            # 4) JS click
            try:
                d.execute_script("arguments[0].click();", a)
            except Exception as e:
                last_err = e

            time.sleep(0.15)
            if _has_active(target):
                return

            # 5) ENTER 키
            try:
                a.send_keys(Keys.ENTER)
            except Exception as e:
                last_err = e

            time.sleep(0.15)
            if _has_active(target):
                return

        except StaleElementReferenceException as e:
            last_err = e
            target = [e for e in d.find_elements(By.CSS_SELECTOR, div_sel) if e.is_displayed()][0]
            a = target.find_element(By.CSS_SELECTOR, a_rel)
            _scroll_center_local(a)
            time.sleep(0.2)

    raise RuntimeError(
        f"option menu toggle did not open (active not set). last_err={type(last_err).__name__}: {last_err}"
    )


def set_option_config_true_and_direct_input() -> None:
    """
    토글이 열린 뒤,
    1) '설정함' (#option_choice_type_true) 선택
    2) '직접 입력하기' (input[type=radio][value=direct]) 선택

    ✅ input-content 같은 특정 wrapper에 의존하지 않고
    ✅ opt_true와 direct를 동시에 포함하는 "가장 가까운 공통 조상"을 찾아 scope로 사용
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    def _scroll_center(el) -> None:
        try:
            d.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", el)
        except Exception:
            pass

    def _dispatch_mouse(el) -> None:
        d.execute_script(
            """
            const el = arguments[0];
            const opts = {bubbles:true, cancelable:true, view:window};
            el.dispatchEvent(new MouseEvent('mousedown', opts));
            el.dispatchEvent(new MouseEvent('mouseup', opts));
            el.dispatchEvent(new MouseEvent('click', opts));
            """,
            el,
        )

    def _human_click(el) -> None:
        _scroll_center(el)
        time.sleep(0.05)
        try:
            ActionChains(d).move_to_element(el).pause(0.05).click().perform()
            return
        except Exception:
            pass
        try:
            el.click()
            return
        except Exception:
            pass
        try:
            _dispatch_mouse(el)
            return
        except Exception:
            pass
        d.execute_script("arguments[0].click();", el)

    def _snapshot(tag: str) -> None:
        ts = int(time.time())
        fn = f"debug_{tag}_{ts}.png"
        print("\n=== SNAPSHOT ===")
        print("tag:", tag)
        print("url:", d.current_url)
        try:
            print("opt_true exists:", len(d.find_elements(By.CSS_SELECTOR, "input#option_choice_type_true")))
            print("direct exists:", len(d.find_elements(By.CSS_SELECTOR, "input[type='radio'][value='direct']")))
        except Exception as e:
            print("counts fail:", e)
        try:
            d.save_screenshot(fn)
            print("screenshot saved:", fn)
        except Exception as e:
            print("screenshot failed:", e)
        print("=== END SNAPSHOT ===\n")

    print("[DIRECT] step0: wait opt_true + direct (page-wide)")
    try:
        opt_true = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input#option_choice_type_true")))
        direct = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='radio'][value='direct']")))
    except TimeoutException:
        _snapshot("timeout_pagewide_opt_true_or_direct")
        raise

    # ✅ 공통 조상(scope) 찾기: opt_true 조상을 위로 올라가며, 그 안에 direct가 있으면 그게 scope
    scope = d.execute_script(
        """
        const opt = arguments[0];
        const direct = arguments[1];

        function isDisplayed(el){
          if(!el) return false;
          const r = el.getBoundingClientRect();
          return (r.width > 0 && r.height > 0);
        }

        // direct가 특정 ancestor 안에 포함되는지
        function containsDirect(ancestor){
          try { return ancestor && ancestor.contains(direct); }
          catch(e){ return false; }
        }

        let cur = opt;
        // opt부터 document까지 올라가며 가장 가까운 공통 조상을 찾음
        while (cur) {
          if (containsDirect(cur) && isDisplayed(cur)) return cur;
          cur = cur.parentElement;
        }
        return null;
        """,
        opt_true,
        direct,
    )

    if not scope:
        _snapshot("scope_common_ancestor_not_found")
        raise RuntimeError("common scope (containing opt_true and direct) not found")

    print("[DIRECT] step1: click '설정함'")
    # label 우선 (없으면 input 클릭)
    try:
        lbl_true = scope.find_element(By.CSS_SELECTOR, "label[for='option_choice_type_true']")
    except Exception:
        lbl_true = opt_true

    for _ in range(6):
        try:
            if opt_true.is_selected():
                break
        except StaleElementReferenceException:
            opt_true = d.find_element(By.CSS_SELECTOR, "input#option_choice_type_true")
        _human_click(lbl_true)
        time.sleep(0.12)

    if not opt_true.is_selected():
        d.execute_script(
            """
            const i = arguments[0];
            i.checked = true;
            i.dispatchEvent(new Event('input', {bubbles:true}));
            i.dispatchEvent(new Event('change', {bubbles:true}));
            i.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            """,
            opt_true,
        )
        time.sleep(0.2)

    if not opt_true.is_selected():
        _snapshot("failed_select_opt_true")
        raise RuntimeError("'설정함' 선택 실패")

    print("[DIRECT] step2: click '직접 입력하기'")
    # scope 안에서 direct를 다시 잡아서(DOM 변화 대비)
    try:
        direct2 = scope.find_element(By.CSS_SELECTOR, "input[type='radio'][value='direct']")
    except Exception:
        # 폴백: page-wide
        direct2 = d.find_element(By.CSS_SELECTOR, "input[type='radio'][value='direct']")

    # label 우선(없으면 input 클릭)
    try:
        lbl_direct = scope.find_element(By.XPATH, ".//label[.//input[@type='radio' and @value='direct']]")
    except Exception:
        lbl_direct = direct2

    for _ in range(6):
        if direct2.is_selected():
            break
        _human_click(lbl_direct)
        time.sleep(0.12)

    if not direct2.is_selected():
        d.execute_script(
            """
            const i = arguments[0];
            i.checked = true;
            i.dispatchEvent(new Event('input', {bubbles:true}));
            i.dispatchEvent(new Event('change', {bubbles:true}));
            i.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
            """,
            direct2,
        )
        time.sleep(0.2)

    if not direct2.is_selected():
        _snapshot("failed_select_direct")
        raise RuntimeError("'직접 입력하기' 선택 실패")

    print("[DIRECT] done")


# =========================================================
# Option group name (e.g., 색상) input
# =========================================================
def set_option_group_name(color_value: str) -> None:
    # ✅ 옵션 그룹명은 항상 고정
    v = "색상 / 사이즈"

    d = get_driver()
    wait = WebDriverWait(d, 15)
    try:
        inp = wait.until(EC.presence_of_element_located((By.ID, "choice_option_name0")))
    except TimeoutException as e:
        debug_snapshot("choice_option_name0_not_found")
        raise RuntimeError("input#choice_option_name0 not found") from e

    _scroll_center(d, inp)
    time.sleep(0.05)

    d.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        inp,
        v,
    )

    try:
        cur = (inp.get_attribute("value") or "").strip()
        if cur != v:
            print(f"[WARN] option group name not matched. expected='{v}', got='{cur}'")
    except Exception:
        pass

def set_option_values(size_values: str) -> None:
    """
    옵션 값 input#choice_option_value0 에 사이즈 값 입력
    예: "S, M, L, XL"
    """
    v = (size_values or "").strip()
    if not v:
        return

    d = get_driver()
    wait = WebDriverWait(d, 15)

    try:
        inp = wait.until(EC.presence_of_element_located((By.ID, "choice_option_value0")))
    except TimeoutException as e:
        debug_snapshot("choice_option_value0_not_found")
        raise RuntimeError("input#choice_option_value0 not found") from e

    _scroll_center(d, inp)
    time.sleep(0.05)

    # Angular 반영 안정화
    d.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        inp,
        v,
    )

    try:
        cur = (inp.get_attribute("value") or "").strip()
        if cur != v:
            print(f"[WARN] option values not matched. expected='{v}', got='{cur}'")
    except Exception:
        pass
def click_apply_option_list() -> None:
    """
    '옵션목록으로 적용' 버튼 클릭
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    try:
        # 1️⃣ 버튼 DOM 생성 대기
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//a[contains(@class,'btn-primary') "
                    "and contains(normalize-space(),'옵션목록으로 적용')]",
                )
            )
        )

        # 2️⃣ 클릭 가능 상태 대기
        btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(@class,'btn-primary') "
                    "and contains(normalize-space(),'옵션목록으로 적용')]",
                )
            )
        )

    except TimeoutException as e:
        debug_snapshot("apply_option_button_not_found")
        raise RuntimeError("'옵션목록으로 적용' 버튼을 찾지 못함") from e

    _scroll_center(d, btn)
    time.sleep(0.15)

    try:
        btn.click()
    except Exception:
        d.execute_script("arguments[0].click();", btn)

    print("[OK] 옵션목록으로 적용 버튼 클릭 완료")

    # 3️⃣ 클릭 후 약간 대기 (Grid 생성 안정화)
    time.sleep(0.5)
def click_add_image_button() -> None:
    """
    '이미지 등록' 클릭 → 업로드 모달 열림 대기
    (주의: '내 사진' 버튼은 클릭하지 않는다. OS 파일창 뜸)
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    # 1) 이미지 등록 버튼 클릭
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn-add-img")))
    _scroll_center(d, btn)
    d.execute_script("arguments[0].click();", btn)
    print("[OK] 이미지 등록 버튼 클릭")

    # 2) 모달 열림 확인: '내 사진' 버튼 또는 file input이 나타나면 OK
    try:
        wait.until(
            lambda _d: (
                len(_d.find_elements(By.XPATH, "//button[normalize-space()='내 사진']")) > 0
                or len(_d.find_elements(By.CSS_SELECTOR, "input[type='file']")) > 0
            )
        )
    except TimeoutException as e:
        debug_snapshot("upload_modal_not_opened")
        raise RuntimeError("업로드 모달이 열리지 않음") from e

    print("[OK] 업로드 모달 열림 확인")

def click_upload_from_device_button() -> None:
    """
    업로드 모달 내부 '내 사진' 버튼 클릭
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    try:
        # 모달 내부에서 버튼 찾기 (텍스트 기준이 가장 안전)
        btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(@class,'btn-default') "
                    "and normalize-space()='내 사진']",
                )
            )
        )
    except TimeoutException as e:
        debug_snapshot("upload_from_device_button_not_found")
        raise RuntimeError("'내 사진' 버튼을 찾지 못함") from e

    _scroll_center(d, btn)
    time.sleep(0.1)

    try:
        btn.click()
    except Exception:
        d.execute_script("arguments[0].click();", btn)

    print("[OK] '내 사진' 버튼 클릭 완료")

    # 파일 input 생성 대기
    wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
    )

    print("[OK] file input 생성 확인")

def upload_representative_image_by_code(code: str) -> None:
    """
    kv_mvp/out/<code>/images/pd_001.jpg 자동 업로드
    - OS 파일선택창(열기) 절대 사용 안함
    - 업로드 모달이 열린 상태에서 input[type=file]에 send_keys로 주입
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    c = (code or "").strip()
    if not c:
        raise ValueError("code is empty (품번이 비어있음)")

    base_dir = Path(__file__).resolve().parent
    image_path = base_dir / "kv_mvp" / "out" / c / "images" / "pd_001.jpg"
    if not image_path.exists():
        raise FileNotFoundError(f"이미지 파일 없음: {image_path}")

    # 업로드 모달이 이미 열려있다는 전제(열려있지 않으면 찾기 실패할 수 있음)
    # file input은 여러 개가 있을 수 있으니 '표시되는 것' 중 마지막을 우선 사용
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    except TimeoutException as e:
        debug_snapshot("file_input_not_found_in_modal")
        raise RuntimeError("업로드 모달에서 input[type=file]을 찾지 못함") from e

    inputs = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
    vis = [x for x in inputs if x.is_displayed()]
    file_input = vis[-1] if vis else inputs[-1]

    file_input.send_keys(str(image_path))
    print(f"[OK] 대표 이미지 업로드 send_keys 완료: {image_path}")

    # 업로드 UI 반영 대기 (SmartStore UI가 비동기)
    time.sleep(2.0)

def click_additional_image_button() -> None:
    """
    추가이미지(image.add) 영역의 '이미지 등록' 버튼 클릭
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    btn = wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a.btn-add-img[data-nclicks-code='image.add']")
        )
    )

    _scroll_center(d, btn)
    d.execute_script("arguments[0].click();", btn)

    print("[OK] 추가 이미지 등록 버튼 클릭")

    # 모달 생성 대기
    wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
    )

    print("[OK] 추가 이미지 업로드 모달 열림")

def upload_additional_images_by_code(code: str) -> None:
    """
    kv_mvp/out/<code>/images/pd_002.jpg ~ pd_010.jpg 업로드
    """
    d = get_driver()
    wait = WebDriverWait(d, 15)

    c = (code or "").strip()
    if not c:
        raise ValueError("code is empty")

    base_dir = Path(__file__).resolve().parent
    img_dir = base_dir / "kv_mvp" / "out" / c / "images"

    files = []
    for i in range(2, 11):  # 002 ~ 010
        p = img_dir / f"pd_{i:03d}.jpg"
        if p.exists():
            files.append(str(p))

    if not files:
        raise FileNotFoundError(f"추가 이미지 없음: {img_dir}")

    # file input 찾기
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    inputs = d.find_elements(By.CSS_SELECTOR, "input[type='file']")
    vis = [x for x in inputs if x.is_displayed()]
    file_input = vis[-1] if vis else inputs[-1]

    # 여러 파일 업로드
    file_input.send_keys("\n".join(files))

    print(f"[OK] 추가 이미지 업로드 완료: {len(files)}장")

    time.sleep(3)  # UI 반영 대기

def click_html_editor_button(code: Optional[str] = None) -> None:
    """
    ✅ 기존 호출부를 최대한 유지하면서도(code를 넘길 수 있게),
    SmartEditor ONE 새창 열기 + (추후 업로드) 흐름으로 확장할 수 있게 만든다.
    """
    c = (code or "").strip()
    if not c:
        raise ValueError("code is empty (품번이 비어있음)")

    d = get_driver()

    # 1) SmartEditor ONE 새창 열기 + 전환
    original, _new = detail_editor.open_editor_one_new_window(d, timeout=20)

    # 2) 여기서 업로드 호출(예: MD_COMMENT 1장)
    image_paths = build_editor_image_paths(code)

    detail_editor.upload_images_in_editor_one(
    d,
    image_paths,
    timeout=50)
    detail_editor.submit_editor_and_return(d, original, timeout=40)

    print("[DBG] handles:", d.window_handles)
    print("[DBG] current:", d.current_window_handle)
    print("[DBG] url:", d.current_url)

    # 3) 닫고 복귀
    #print("[HOLD] editor window open for inspection")
    #time.sleep(9999)

def build_editor_image_paths(code: str) -> list[str]:
    """
    SmartEditor 업로드 이미지 순서 고정
    (AutoGoods 폴더 기준 kv_mvp 경로 자동 계산)
    """

    project_root = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(project_root, "kv_mvp")

    paths = [
        os.path.join(base_dir, "img", "nav1.jpg"),
        os.path.join(base_dir, "img", "nav2.png"),
        os.path.join(base_dir, "out", code, "renders", "jpg", "MD_COMMENT.jpg"),
        os.path.join(base_dir, "out", code, "images", "pd_photo_merged.jpg"),
        os.path.join(base_dir, "out", code, "renders", "jpg", "소재_및_관리방법.jpg"),
        os.path.join(base_dir, "out", code, "renders", "jpg", "상품정보제공고시.jpg"),
        os.path.join(base_dir, "img", "nav3.png"),
    ]

    for p in paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"[상세 업로드 파일 없음] {p}")

    return paths

def click_register_button():
    d = get_driver()

    # 페이지 로딩 안정화
    WebDriverWait(d, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(0.8)

    # 저장 완료 대기 (기존 spinner 방식 + 보조)
    end = time.time() + 40
    while time.time() < end:
        # spinner가 사라지면 종료 (있을 때만)
        sp = d.find_elements(By.CSS_SELECTOR, "button .progress-inner")
        if not sp or (sp and not sp[0].is_displayed()):
            return

        # URL이 create를 벗어나면 성공 가능성이 큼
        try:
            if "#/products/create" not in (d.current_url or ""):
                return
        except Exception:
            pass

        time.sleep(0.25)

    raise TimeoutException("Save/Register click done but completion not detected (timeout).")

def open_product_maininfo_menu():
    d = get_driver()
    wait = WebDriverWait(d, 20)

    # 1) '상품 주요정보' 영역 찾기
    title_xpath = "//div[contains(@class,'title-line') and .//label[contains(normalize-space(.),'상품 주요정보')]]"
    title_line = wait.until(EC.presence_of_element_located((By.XPATH, title_xpath)))
    _scroll_center(d, title_line)

    # 영역 클릭 (접혀있을 가능성 대비)
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, title_xpath))).click()
    except Exception:
        d.execute_script("arguments[0].click();", title_line)

    # 2) 메뉴토글 버튼 찾기
    toggle_xpath = title_xpath + "//a[contains(@class,'btn-default')]"
    toggle = wait.until(EC.presence_of_element_located((By.XPATH, toggle_xpath)))
    _scroll_center(d, toggle)

    # 이미 열려있지 않은 경우만 클릭
    if "active" not in toggle.get_attribute("class"):
        try:
            wait.until(EC.element_to_be_clickable((By.XPATH, toggle_xpath))).click()
        except Exception:
            d.execute_script("arguments[0].click();", toggle)

        # active class 반영될 때까지 대기
        wait.until(
            lambda drv: "active" in drv.find_element(By.XPATH, toggle_xpath).get_attribute("class")
        )

def set_manufacture_define_no(code: str):
    """
    상품 주요정보 영역이 열린 상태에서
    품번(input#prd-mdn)에 값을 입력한다.
    """
    if not code:
        raise ValueError("code is empty")

    d = get_driver()
    wait = WebDriverWait(d, 20)

    input_xpath = "//input[@id='prd-mdn' and @name='product.detailAttribute.manufactureDefineNo']"

    # 1) 입력창 활성화 대기
    inp = wait.until(EC.presence_of_element_located((By.XPATH, input_xpath)))
    wait.until(EC.element_to_be_clickable((By.XPATH, input_xpath)))

    _scroll_center(d, inp)

    # 2) 값 초기화
    try:
        inp.click()
    except Exception:
        d.execute_script("arguments[0].click();", inp)

    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)

    # 3) 값 입력
    inp.send_keys(code)

    # 4) Angular 반영 강제 트리거 (중요)
    d.execute_script("""
        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
    """, inp)

def set_brand_name_select_first(brand: str):
    """
    브랜드 입력(Selectize/자동완성) 후, 드롭다운에서 '첫 번째 추천 항목'을 클릭해 선택 확정.
    - Enter만 치면 선택이 안 되거나 '직접입력'으로 남는 케이스를 방지
    """
    if not brand:
        raise ValueError("brand is empty")

    d = get_driver()
    wait = WebDriverWait(d, 20)

    # 브랜드 입력창 (placeholder는 그대로 두고, 여러개일 수 있으니 '보이는/클릭가능' 기준으로 잡음)
    brand_inp_xpath = "//input[@placeholder='브랜드를 입력해주세요.']"
    inp = wait.until(EC.element_to_be_clickable((By.XPATH, brand_inp_xpath)))
    _scroll_center(d, inp)

    # 1) 포커스 + 초기화
    try:
        inp.click()
    except Exception:
        d.execute_script("arguments[0].click();", inp)

    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)

    # 2) 브랜드 입력
    inp.send_keys(brand)

    # 3) 드롭다운(Selectize) 뜰 때까지 대기
    #    - 보이는 dropdown 중 첫 번째 option을 고른다.
    dropdown_xpath = (
        "//div[contains(@class,'selectize-dropdown') and contains(@style,'display: block')]"
        "//div[contains(@class,'selectize-dropdown-content')]"
    )
    wait.until(EC.presence_of_element_located((By.XPATH, dropdown_xpath)))

    # 4) 첫 번째 selectable option 클릭
    #    - '직접입력:아이더' 같은 줄도 option일 수 있으니, selectable 이면서 option 인 첫 항목을 잡는다.
    first_option_xpath = (
        dropdown_xpath
        + "//div[contains(@class,'option') and @data-selectable][1]"
    )

    opt = wait.until(EC.element_to_be_clickable((By.XPATH, first_option_xpath)))
    _scroll_center(d, opt)

    try:
        opt.click()
    except Exception:
        d.execute_script("arguments[0].click();", opt)

    # 5) 선택 확정 확인(드롭다운이 닫히거나, input 값이 바뀌거나 둘 중 하나)
    wait.until(
        lambda drv: len(drv.find_elements(By.XPATH,
            "//div[contains(@class,'selectize-dropdown') and contains(@style,'display: block')]"
        )) == 0
        or drv.find_element(By.XPATH, brand_inp_xpath).get_attribute("value").strip() != ""
    )
def _load_product_json_by_code(code: str) -> Optional[dict]:
    """
    kv_mvp/out/{code}/product.json 로드 (없으면 None)
    """
    if not code:
        return None

    path = os.path.join("kv_mvp", "out", code, "product.json")
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _get_gvnt_manufacture_ym(product: Optional[dict]) -> Optional[str]:
    """
    product.json -> gvnt_info -> 제조연월(수입연월) 추출 (없으면 None)
    """
    if not product:
        return None
    gvnt = product.get("gvnt_info") or {}
    v = gvnt.get("제조연월(수입연월)")
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _normalize_manufacture_ym(s: Optional[str]) -> Optional[str]:
    """
    다양한 입력을 'YYYY.MM.01' 또는 'YYYY.MM.DD'로 정규화.
    예:
      - '2024년 08' -> '2024.08.01'
      - '2025년10월' -> '2025.10.01'
      - '2025.10' -> '2025.10.01'
      - '2025.10.15' -> '2025.10.15'
      - '2025-10-15' -> '2025.10.15'
    """
    if not s:
        return None
    t = str(s).strip()

    # YYYY.MM.DD / YYYY-MM-DD / YYYY/MM/DD
    m = re.search(r"(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}.{mo:02d}.{d:02d}"
        return None

    # YYYY년 MM(월)
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*(?:월)?", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}.{mo:02d}.01"
        return None

    # YYYY.MM / YYYY-MM / YYYY/MM
    m = re.search(r"(\d{4})[.\-\/](\d{1,2})", t)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}.{mo:02d}.01"
        return None

    return None


def set_manufacture_date_optional(raw_value: Optional[str]) -> bool:
    """
    제조연월(수입연월)이 있으면 제조일자(manufactureDate) 입력.
    - raw_value -> _normalize_manufacture_ym() -> 'YYYY.MM.DD' (보통 DD=01)
    - SmartStore 제조일자는 AngularJS ngModel 기반이라, 달력 클릭이 안 먹는 케이스가 있어
      1) 달력 클릭 시도
      2) 안 바뀌면 Angular ngModel($setViewValue)로 강제 반영 (최종 확정)
    - 값이 없으면 스킵(True)
    - 성공/스킵 True, 실패 False
    """
    norm = _normalize_manufacture_ym(raw_value)
    if not norm:
        return True

    ty, tm, td = map(int, norm.split("."))
    expected_clean = f"{ty:04d}.{tm:02d}.{td:02d}"

    print("[DBG] manufacture raw:", raw_value)
    print("[DBG] manufacture norm:", norm)

    dvr = get_driver()
    wait = WebDriverWait(dvr, 20)

    def clean(v: str) -> str:
        return (v or "").strip().rstrip(".")

    # 0) manufactureDate input (페이지에 1개라는 로그 확인됨. 그래도 안전하게 "보이는 것" 우선)
    def pick_input():
        els = dvr.find_elements(By.NAME, "product.detailAttribute.manufactureDate")
        if not els:
            return None
        visible = [e for e in els if e.is_displayed()]
        cand = visible if visible else els
        cand.sort(key=lambda e: (e.rect.get("y", 0), e.rect.get("x", 0)))
        return cand[-1]

    inp = wait.until(lambda drv: pick_input())
    _scroll_center(dvr, inp)

    # 1) 다른 달력 닫기(토글/오염 방지)
    try:
        dvr.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass

    # 2) input 클릭(달력 열기 시도)
    try:
        inp.click()
    except Exception:
        dvr.execute_script("arguments[0].click();", inp)

    # 3) (선택) 달력 클릭으로 반영 시도
    #    - 달력이 떠있다면 nearest picker를 잡아 목표 월/일 클릭
    try:
        def get_nearest_picker():
            return dvr.execute_script(
                """
                const inp = arguments[0];
                const ir = inp.getBoundingClientRect();
                const pickers = Array.from(document.querySelectorAll('div.datetimepicker'))
                  .filter(p => p.offsetParent !== null && !p.classList.contains('ng-hide'));
                if (!pickers.length) return null;

                let best = null;
                let bestScore = Infinity;
                for (const p of pickers) {
                  const r = p.getBoundingClientRect();
                  const dy = Math.abs(r.top - ir.bottom);
                  const dx = Math.abs((r.left+r.right)/2 - (ir.left+ir.right)/2);
                  const score = dy*10 + dx;
                  if (score < bestScore) { bestScore = score; best = p; }
                }
                return best;
                """,
                inp,
            )

        picker = WebDriverWait(dvr, 3).until(lambda drv: get_nearest_picker())

        def read_ym_from(pk) -> tuple[int, int]:
            title = pk.find_element(By.CSS_SELECTOR, "button.title")
            txt = (title.text or "").strip()  # 예: 2026.03
            m = re.search(r"(\d{4})\.(\d{1,2})", txt)
            if not m:
                raise ValueError(f"cannot read title: {txt!r}")
            return int(m.group(1)), int(m.group(2))

        def click_prev_month(pk):
            btns = pk.find_elements(By.CSS_SELECTOR, "span.prev button.left")
            for b in btns:
                ng = (b.get_attribute("data-ng-click") or "") + (b.get_attribute("ng-click") or "")
                if "data.leftDate" in ng:
                    dvr.execute_script("arguments[0].click();", b)
                    return
            raise ValueError("prev month not found")

        def click_next_month(pk):
            btns = pk.find_elements(By.CSS_SELECTOR, "span.next button.right")
            for b in btns:
                ng = (b.get_attribute("data-ng-click") or "") + (b.get_attribute("ng-click") or "")
                if "data.rightDate" in ng:
                    dvr.execute_script("arguments[0].click();", b)
                    return
            raise ValueError("next month not found")

        cy, cm = read_ym_from(picker)
        diff = (ty - cy) * 12 + (tm - cm)
        if abs(diff) <= 600:
            for _ in range(abs(diff)):
                before = read_ym_from(picker)
                if diff > 0:
                    click_next_month(picker)
                else:
                    click_prev_month(picker)
                WebDriverWait(dvr, 5).until(lambda drv: read_ym_from(picker) != before)

            # 날짜 클릭 (현재월만: past/future 제외)
            day_xpath = (
                f".//td[contains(@class,'day') and not(contains(@class,'disabled')) "
                f"and not(contains(@class,'past')) and not(contains(@class,'future'))]"
                f"//span[normalize-space(text())='{td}']"
            )
            day = picker.find_element(By.XPATH, day_xpath)
            dvr.execute_script("arguments[0].click();", day)
    except Exception:
        # 달력 클릭 시도는 best-effort, 실패해도 아래 Angular 강제 반영으로 진행
        pass

    # 4) 값이 이미 반영됐으면 종료
    if clean(inp.get_attribute("value")) == expected_clean:
        print("[DBG] manufacture applied (by picker):", clean(inp.get_attribute("value")))
        return True

    # 5) 최종 해결: AngularJS ngModel로 강제 반영 (너 케이스의 핵심)
    try:
        dvr.execute_script(
            """
            const el = arguments[0];
            const y = arguments[1], m = arguments[2], d = arguments[3];

            function fire(el){
              el.dispatchEvent(new Event('input', {bubbles:true}));
              el.dispatchEvent(new Event('change', {bubbles:true}));
              el.dispatchEvent(new Event('blur', {bubbles:true}));
            }

            // 값 표시 포맷은 시스템이 맡기되, 모델은 Date로 넣는게 가장 안전
            const dt = new Date(Date.UTC(y, m-1, d, 0, 0, 0));

            if (window.angular) {
              const ngEl = angular.element(el);
              const scope = ngEl.scope() || ngEl.isolateScope();
              const ngModel = ngEl.controller('ngModel');

              if (scope && scope.$apply && ngModel && ngModel.$setViewValue) {
                scope.$apply(function(){
                  ngModel.$setViewValue(dt);
                  if (ngModel.$render) ngModel.$render();
                });
                fire(el);
                return;
              }

              // fallback: scope에 vm/dateModel이 있으면 직접 세팅
              if (scope && scope.$apply) {
                scope.$apply(function(){
                  if (scope.vm && typeof scope.vm === "object" && "dateModel" in scope.vm) {
                    scope.vm.dateModel = dt;
                  } else if ("vm" in scope && scope.vm && "dateModel" in scope.vm) {
                    scope.vm.dateModel = dt;
                  }
                });
                fire(el);
                return;
              }
            }

            // angular 접근이 안 되면(드뭄) value만이라도 세팅 (하지만 Invalid date 가능)
            el.value = `${String(y).padStart(4,'0')}.${String(m).padStart(2,'0')}.${String(d).padStart(2,'0')}.`;
            fire(el);
            """,
            inp, ty, tm, td
        )
    except Exception:
        return False

    # 6) 최종 검증 (끝점 제거 비교)
    try:
        wait.until(lambda drv: clean(inp.get_attribute("value")) == expected_clean)
        print("[DBG] manufacture applied (by ngModel):", clean(inp.get_attribute("value")))
        return True
    except Exception:
        print("[DBG] manufacture FAILED. current:", clean(inp.get_attribute("value")))
        return False
    

def apply_manufacture_date_from_product_json(code: str) -> bool:
    """
    code로 product.json 읽어서 제조연월(수입연월) 있으면 세팅, 없으면 스킵.
    반환:
      - True: 스킵(없음) 또는 세팅 성공
      - False: 값은 있었는데 세팅 실패
    """
    product = _load_product_json_by_code(code)
    raw = _get_gvnt_manufacture_ym(product)
    return set_manufacture_date_optional(raw)



# =========================================================
# Existing flows
# =========================================================
def _wait_ready_for_category_search(wait: WebDriverWait) -> None:
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "label[for='r_1_1']")))


def ensure_category_panel_open() -> None:
    d = get_driver()
    wait = WebDriverWait(d, 25)

    _wait_ready_for_category_search(wait)

    def _toggle_el():
        return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn.btn-default.btn-hide")))

    toggle = _toggle_el()
    if "active" in (toggle.get_attribute("class") or ""):
        return

    try:
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn.btn-default.btn-hide")))
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", toggle)
        _safe_click(d, toggle)
    except Exception:
        ActionChains(d).move_to_element(toggle).click().perform()

    wait.until(lambda _d: "active" in (_toggle_el().get_attribute("class") or ""))


def go_product_register() -> None:
    """좌측 메뉴: 상품관리 → 상품 등록(#/products/create) 이동 후 카테고리 섹션 준비 대기"""
    d = get_driver()
    wait = WebDriverWait(d, 25)

    wait.until(EC.presence_of_element_located((By.XPATH, "//*[normalize-space()='상품관리']")))

    product_manage = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//div[@id='seller-lnb']//a[normalize-space()='상품관리']"))
    )
    _safe_click(d, product_manage)

    product_register = wait.until(
        EC.element_to_be_clickable(
            (By.XPATH, "//div[@id='seller-lnb']//a[@href='#/products/create' and normalize-space()='상품 등록']")
        )
    )
    _safe_click(d, product_register)

    _wait_ready_for_category_search(wait)
    ensure_category_panel_open()


def check_logged_in() -> bool:
    d = get_driver()
    try:
        WebDriverWait(d, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.login-id")))
        return True
    except TimeoutException:
        return False


def set_category_by_query(query: str) -> None:
    d = get_driver()
    wait = WebDriverWait(d, 25)

    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")

    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#_prod-category-section")))
    except TimeoutException:
        raise RuntimeError(
            "카테고리 섹션(#_prod-category-section)을 찾지 못함. 상품등록 페이지가 아닌 상태이거나 로딩 전일 수 있음."
        )

    ensure_category_panel_open()

    label = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#_prod-category-section label[for='r_1_1']")))
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", label)
    _safe_click(d, label)

    box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#_prod-category-section .selectize-input")))
    box.click()

    # 기존 선택 제거
    for _ in range(5):
        rms = d.find_elements(By.CSS_SELECTOR, "#_prod-category-section .selectize-input a.remove")
        if rms:
            _safe_click(d, rms[0])
            continue

        items = d.find_elements(By.CSS_SELECTOR, "#_prod-category-section .selectize-input .item")
        if items:
            try:
                d.switch_to.active_element.send_keys(Keys.BACKSPACE)
                continue
            except Exception:
                pass
        break

    inp = wait.until(
        EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#_prod-category-section .selectize-input input[placeholder='카테고리명 입력']")
        )
    )
    inp.click()
    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)
    inp.send_keys(q)

    option = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//*[@id='_prod-category-section']"
                "//div[contains(@class,'selectize-dropdown-content')]"
                f"//div[contains(@class,'option') and @data-selectable and contains(normalize-space(), {repr(q)})]",
            )
        )
    )
    _safe_click(d, option)

    wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                f"//*[@id='_prod-category-section']//div[contains(@class,'selectize-input')]"
                f"//div[contains(@class,'item') and contains(normalize-space(), {repr(q)})]",
            )
        )
    )


def set_product_name(product_name: str) -> None:
    d = get_driver()
    wait = WebDriverWait(d, 25)

    name = (product_name or "").strip()
    if not name:
        raise ValueError("product_name is empty")

    inp = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='product.name']")))
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)

    try:
        inp.click()
    except Exception:
        ActionChains(d).move_to_element(inp).click().perform()

    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)
    inp.send_keys(name)
    inp.send_keys(Keys.TAB)

    try:
        wait.until(lambda _d: (inp.get_attribute("value") or "").strip() == name)
    except Exception:
        pass


def set_sale_price(price: int) -> None:
    d = get_driver()
    wait = WebDriverWait(d, 25)

    if price is None:
        raise ValueError("sale_price is None")

    s = str(price).strip()
    if not s.isdigit():
        raise ValueError(f"sale_price must be digits: {price}")

    inp = wait.until(EC.element_to_be_clickable((By.ID, "prd_price2")))
    d.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)

    try:
        inp.click()
    except Exception:
        ActionChains(d).move_to_element(inp).click().perform()

    inp.send_keys(Keys.CONTROL, "a")
    inp.send_keys(Keys.BACKSPACE)

    for ch in s:
        inp.send_keys(ch)
        time.sleep(0.02)

    inp.send_keys(Keys.TAB)

    try:
        wait.until(lambda _d: (inp.get_attribute("value") or "").replace(",", "").strip() == s)
    except Exception:
        pass


def go_register_and_set_category(query: str) -> None:
    go_product_register()
    set_category_by_query(query)


def _is_on_product_register() -> bool:
    d = get_driver()
    url = (d.current_url or "")
    if "#/products/create" not in url:
        return False
    try:
        WebDriverWait(d, 3).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#_prod-category-section")))
        return True
    except Exception:
        return False


def go_register_and_apply(
    query: Optional[str] = None,
    product_name: Optional[str] = None,
    sale_price: Optional[int] = None,
    color_value: Optional[str] = None,
    size_values: Optional[str] = None,   # ✅ 추가
    code: Optional[str] = None,
) -> None:
    """
    - 이미 상품등록 화면이면 이동 생략
    - 판매가 입력 후:
      1) 옵션 토글 열기
      2) 설정함 선택
      3) 직접 입력하기 선택 (+ 디버그)
      4) (추가) 옵션 그룹명(#choice_option_name0)에 색상 값 입력
    """
    if not _is_on_product_register():
        go_product_register()

    q = (query or "").strip()
    n = (product_name or "").strip()
    sp = sale_price if sale_price is not None else None

    if q:
        set_category_by_query(q)
    if n:
        set_product_name(n)
    if sp is not None:
        set_sale_price(sp)

    # 옵션 섹션은 판매가 이후에도 쓰이지만,
    # 색상(옵션명)만 입력하는 경우에도 필요할 수 있어 sp/color 중 하나라도 있으면 진행
    cv = (color_value or "").strip()
    sv = (size_values or "").strip()

    if sp is not None or cv or sv:
        click_option_menu_toggle()
        set_option_config_true_and_direct_input()

        if cv:
            set_option_group_name(cv)
        if sv:
            set_option_values(sv)
        # ✅ 옵션목록으로 적용 클릭
        click_apply_option_list()

        click_add_image_button()
        upload_representative_image_by_code(code)

        # 🔽 여기 추가
        click_additional_image_button()
        upload_additional_images_by_code(code)

        click_html_editor_button(code)
        click_register_button()

        open_product_maininfo_menu()
        set_manufacture_define_no(code)
        set_brand_name_select_first("아이더")
        apply_manufacture_date_from_product_json(code)

    if not q and not n and sp is None and not cv and not sv:
        raise ValueError("query/product_name/sale_price/color/size are all empty")