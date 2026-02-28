# detail_editor.py
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _scroll_center(driver, el) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)


def open_smarteditor_one_window(driver, timeout: int = 15) -> Tuple[str, str]:
    """
    SmartStore 상세설명 영역의 '스마트 에디터 ONE으로 작성' 버튼 클릭 후
    새 창(탭/팝업)으로 전환.
    return: (original_handle, new_handle)
    """
    wait = WebDriverWait(driver, timeout)

    original = driver.current_window_handle
    before = set(driver.window_handles)

    # 가장 안정적인 셀렉터: ng-click
    btn = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//button[@ng-click=\"vm.func.openEditor($event, false)\"]")
    ))
    _scroll_center(driver, btn)
    time.sleep(0.1)

    try:
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@ng-click=\"vm.func.openEditor($event, false)\"]")
        ))
        btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", btn)

    # 새 창 전환
    wait.until(lambda d: len(set(d.window_handles) - before) > 0)
    new_handle = list(set(driver.window_handles) - before)[0]
    driver.switch_to.window(new_handle)
    return original, new_handle


def _find_file_input_in_frames(driver, timeout: int = 8):
    """
    에디터 새창에서 input[type=file]를 찾는다.
    - 기본 문서에서 먼저 찾고
    - 없으면 iframe들을 순회하며 찾음
    return: (file_input_element, in_frame: bool)
    """
    wait = WebDriverWait(driver, timeout)

    # 1) top document
    try:
        el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
        return el, False
    except Exception:
        pass

    # 2) iframes scan
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for fr in frames:
        try:
            driver.switch_to.frame(fr)
            el = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
            )
            return el, True
        except Exception:
            driver.switch_to.default_content()

    driver.switch_to.default_content()
    return None, False


def upload_images_via_file_input(driver, paths: List[str], timeout: int = 20) -> None:
    """
    에디터 새창에서 로컬 이미지 업로드.
    - 가능하면 여러 파일을 한 번에 send_keys(개행 구분) 시도
    """
    if not paths:
        return

    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))

    file_input, in_frame = _find_file_input_in_frames(driver, timeout=10)
    if not file_input:
        raise RuntimeError("에디터 새창에서 input[type=file]를 찾지 못했습니다(iframe 포함).")

    # 일부 UI는 input이 숨김이라도 send_keys는 가능
    joined = "\n".join(paths)
    try:
        file_input.send_keys(joined)
    finally:
        if in_frame:
            driver.switch_to.default_content()

    # 업로드/삽입 시간(필요시 늘리기)
    time.sleep(1.0)


def collect_new_image_srcs(driver, before_count: int, expected_new: int, timeout: int = 30) -> List[str]:
    """
    업로드 전 이미지 개수(before_count)를 알고 있을 때,
    업로드 후 새로 추가된 img src들을 반환.
    """
    wait = WebDriverWait(driver, timeout)

    def _imgs():
        return driver.find_elements(By.CSS_SELECTOR, "img")

    target_total = before_count + max(0, expected_new)

    wait.until(lambda d: len(_imgs()) >= target_total)

    imgs = _imgs()
    new_imgs = imgs[before_count:before_count + expected_new]
    srcs = []
    for im in new_imgs:
        try:
            s = (im.get_attribute("src") or "").strip()
            if s:
                srcs.append(s)
        except Exception:
            pass
    return srcs


def count_images(driver) -> int:
    return len(driver.find_elements(By.CSS_SELECTOR, "img"))

def _click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)

def _find_in_frames(driver, css, timeout=2):
    """top -> iframe 순회로 요소 찾기. return (el, in_frame)"""
    # top
    try:
        el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
        return el, False
    except Exception:
        pass

    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for fr in frames:
        try:
            driver.switch_to.frame(fr)
            el = WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, css)))
            return el, True
        except Exception:
            driver.switch_to.default_content()

    driver.switch_to.default_content()
    return None, False

def upload_images_in_smarteditor(driver, paths, timeout=30):
    """
    SmartEditor ONE 새창에서:
    - 툴바 '사진 추가' 클릭
    - '내 사진' 클릭
    - input[type=file]에 send_keys로 업로드
    """
    if not paths:
        return

    wait = WebDriverWait(driver, timeout)

    # 1) 사진 추가 버튼
    photo_btn_css = "button[data-name='image'][data-log='dot.img']"
    photo_btn, in_frame = _find_in_frames(driver, photo_btn_css, timeout=6)
    if not photo_btn:
        raise RuntimeError("사진 추가 버튼을 찾지 못했습니다.")
    _click(driver, photo_btn)
    if in_frame:
        driver.switch_to.default_content()

    # 2) 내 사진 버튼(ngf-select)
    my_photo_xpath = ("//button[@ngf-select and contains(normalize-space(.), '내 사진')]")
    # iframe일 수도 있으므로 top/iframe 모두 시도
    my_photo = None
    try:
        my_photo = wait.until(EC.element_to_be_clickable((By.XPATH, my_photo_xpath)))
        _click(driver, my_photo)
    except Exception:
        # iframe scan
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
        for fr in frames:
            try:
                driver.switch_to.frame(fr)
                my_photo = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, my_photo_xpath)))
                _click(driver, my_photo)
                break
            except Exception:
                driver.switch_to.default_content()
        driver.switch_to.default_content()

    if not my_photo:
        raise RuntimeError("'내 사진' 버튼을 찾지 못했습니다.")

    # 3) file input 찾기 (ngf-select는 내부적으로 input[type=file] 사용)
    file_input, in_frame = _find_in_frames(driver, "input[type='file']", timeout=10)
    if not file_input:
        raise RuntimeError("input[type=file]를 찾지 못했습니다.")

    joined = "\n".join(paths)
    try:
        file_input.send_keys(joined)  # 다중 업로드(지원 시)
    finally:
        if in_frame:
            driver.switch_to.default_content()

    # 4) 업로드 완료 대기(최소)
    time.sleep(1.0)

def _scroll_center(driver, el) -> None:
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)


def _click(driver, el) -> None:
    _scroll_center(driver, el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)


def open_editor_one_new_window(driver, timeout: int = 15) -> Tuple[str, str]:
    """
    상품등록 화면에서 '스마트 에디터 ONE으로 작성' 클릭 -> 새창 전환
    return: (original_handle, new_handle)
    """
    wait = WebDriverWait(driver, timeout)
    original = driver.current_window_handle
    before = set(driver.window_handles)

    btn = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//button[@ng-click=\"vm.func.openEditor($event, false)\"]")
    ))
    _click(driver, btn)

    wait.until(lambda d: len(set(d.window_handles) - before) > 0)
    new_handle = list(set(driver.window_handles) - before)[0]
    driver.switch_to.window(new_handle)
    return original, new_handle


def _find_file_inputs_top(driver):
    return driver.find_elements(By.CSS_SELECTOR, "input[type='file']")

def _find_file_inputs_in_iframes(driver):
    found = []
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for fr in frames:
        try:
            driver.switch_to.frame(fr)
            found.extend(driver.find_elements(By.CSS_SELECTOR, "input[type='file']"))
        except Exception:
            pass
        finally:
            driver.switch_to.default_content()
    return found

def _find_any_file_input(driver, total_wait_sec=12, poll=0.25):
    """
    top 문서 + 모든 iframe을 반복 스캔해서 input[type=file] 하나를 찾는다.
    """
    end = time.time() + total_wait_sec
    last_count = 0

    while time.time() < end:
        # 1) top
        inputs = _find_file_inputs_top(driver)
        if inputs:
            return inputs[0], "top"

        # 2) iframes
        inputs = _find_file_inputs_in_iframes(driver)
        if inputs:
            # 첫 번째 input이 있던 iframe으로 다시 들어가야 send_keys가 가능하므로
            # 여기서는 "iframe index"가 아니라, 아래에서 다시 찾기 쉽게 'iframe scan' 표시만 리턴
            return inputs[0], "iframe"

        # 참고용: 디버깅(필요 없으면 제거)
        cnt = len(driver.find_elements(By.CSS_SELECTOR, "iframe"))
        last_count = cnt

        time.sleep(poll)

    return None, f"not_found (iframes={last_count})"

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

_JS_FIND_FILE_INPUT_DEEP = r"""
function findFileInputDeep(root) {
  const seen = new Set();
  function walk(node) {
    if (!node || seen.has(node)) return null;
    seen.add(node);

    // light DOM query
    try {
      const el = node.querySelector && node.querySelector("input[type='file']");
      if (el) return el;
    } catch (e) {}

    // traverse children
    const kids = node.children || [];
    for (let i = 0; i < kids.length; i++) {
      const r = walk(kids[i]);
      if (r) return r;
    }

    // shadow DOM
    if (node.shadowRoot) {
      const r2 = walk(node.shadowRoot);
      if (r2) return r2;
    }
    return null;
  }
  return walk(root);
}
return findFileInputDeep(document);
"""

def _find_file_input_deep_in_current_doc(driver):
    # Selenium이 JS에서 찾은 element를 WebElement로 반환받을 수 있음
    return driver.execute_script(_JS_FIND_FILE_INPUT_DEEP)

def upload_images_in_editor_one(driver, paths, timeout=40):
    """
    SmartEditor ONE 새창에서 로컬 이미지 업로드.
    - (1) 사진추가 버튼만 눌러 input 생성 유도 (내 사진 클릭 금지)
    - (2) top 문서 + iframe 내부에서 shadow DOM까지 포함해 input[type=file] 탐색
    """
    if not paths:
        return

    wait = WebDriverWait(driver, timeout)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    before_imgs = len(driver.find_elements(By.CSS_SELECTOR, "img"))

    def try_send_in_current_doc() -> bool:
        el = _find_file_input_deep_in_current_doc(driver)
        if not el:
            return False
        el.send_keys("\n".join(paths))
        return True

    # 0) 먼저 top 문서에서 시도
    if try_send_in_current_doc():
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "img")) > before_imgs)
        time.sleep(0.3)
        return

    # 1) input이 아직 생성 전일 수 있으니 '사진 추가'만 클릭해서 생성 유도 (내 사진은 누르지 않음)
    try:
        photo_btn = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR, "button[data-name='image'][data-log='dot.img']"
        )))
        driver.execute_script("arguments[0].click();", photo_btn)
        time.sleep(0.3)
    except Exception:
        pass

    # 2) 다시 top 문서 시도
    if try_send_in_current_doc():
        wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "img")) > before_imgs)
        time.sleep(0.3)
        return

    # 3) iframe 1개가 있다고 했으니 그 안도 시도 (shadow DOM 포함)
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for fr in frames:
        try:
            driver.switch_to.frame(fr)

            # iframe 내부에서도 '사진 추가'가 있을 수 있으니 한 번 눌러줌(있으면)
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, "button[data-name='image'][data-log='dot.img']")
                if btns:
                    driver.execute_script("arguments[0].click();", btns[0])
                    time.sleep(0.3)
            except Exception:
                pass

            if try_send_in_current_doc():
                driver.switch_to.default_content()
                wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "img")) > before_imgs)
                time.sleep(0.3)
                return

        except Exception:
            pass
        finally:
            driver.switch_to.default_content()

    raise RuntimeError("SmartEditor 새창(top/iframe/shadow 포함)에서 input[type=file]를 찾지 못했습니다.")

def run_editor_upload_flow(driver, image_paths: List[str], timeout: int = 40) -> None:
    """
    전체 플로우 중간/말미에 호출하는 '정식 단계'
    - 새창 열기
    - 업로드
    - 닫고 복귀
    """
    original, _new = open_editor_one_new_window(driver, timeout=timeout)
    upload_images_in_editor_one(driver, image_paths, timeout=timeout)