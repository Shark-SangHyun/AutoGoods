"""
Selenium automation for Naver SmartStore.

- Category selection: existing 방식 유지
- Product name typing: input[name="product.name"]
- Sale price typing: #prd_price2
- No API bypass: all actions are UI interactions
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
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
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
    try:
        el.click()
    except ElementClickInterceptedException:
        d.execute_script("arguments[0].click();", el)


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
    """
    좌측 메뉴: 상품관리 → 상품 등록(#/products/create) 이동 후
    카테고리 섹션이 조작 가능한 상태까지 대기
    """
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
    # ✅ 이미 상품등록 화면이면 이동하지 않음 (리다이렉트/경고 alert 방지)
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

    if not q and not n and sp is None:
        raise ValueError("query/product_name/sale_price are all empty")
