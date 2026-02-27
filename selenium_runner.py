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

from typing import Optional
from pathlib import Path
import time

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
) -> None:
    """
    - 이미 상품등록 화면이면 이동 생략
    - 판매가 입력 후:
      1) 옵션 토글 열기
      2) 설정함 선택
      3) 직접 입력하기 선택 (+ 디버그)
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

        click_option_menu_toggle()
        set_option_config_true_and_direct_input()

    if not q and not n and sp is None:
        raise ValueError("query/product_name/sale_price are all empty")