# server.py  (에러 메시지에 타입 + 내용 포함해서 내려주기 적용 버전)

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path

import json
import os
import sys

# --- kv_mvp 수집기(collector) 단일 서버 통합 ---
_KV_DIR = (Path(__file__).resolve().parent / "kv_mvp")
if _KV_DIR.exists() and str(_KV_DIR) not in sys.path:
    sys.path.insert(0, str(_KV_DIR))

import kv_mvp.app as kv_collector

from selenium_runner import (
    open_smartstore,
    check_logged_in,
    go_product_register,
    go_register_and_set_category,
    go_register_and_apply,
)

app = FastAPI()

# 정적 파일 서빙: /static/...
app.mount("/static", StaticFiles(directory="static"), name="static")

# kv_mvp 수집기 앱을 /collector 로 마운트 (단일 서버)
try:
    kv_collector.BASE_OUT = Path(__file__).resolve().parent / "kv_mvp" / "out"
except Exception:
    pass
app.mount("/collector", kv_collector.app)

# kv_mvp UI가 fetch("/run_async") 처럼 절대 경로를 호출하기 때문에 리다이렉트
@app.post("/run_async")
def _kv_run_async_redirect():
    return RedirectResponse(url="/collector/run_async", status_code=307)


@app.get("/progress/{job_id}")
def _kv_progress_redirect(job_id: str):
    return RedirectResponse(url=f"/collector/progress/{job_id}", status_code=307)


@app.get("/status/{job_id}")
def _kv_status_redirect(job_id: str):
    return RedirectResponse(url=f"/collector/status/{job_id}", status_code=307)


@app.get("/result/{job_id}")
def _kv_result_redirect(job_id: str):
    return RedirectResponse(url=f"/collector/result/{job_id}", status_code=307)


class ApplyReq(BaseModel):
    query: Optional[str] = None
    product_name: Optional[str] = None
    sale_price: Optional[int] = None  # ✅ 추가


class KvProductReq(BaseModel):
    code: str


def _resolve_kv_out_root() -> Path:
    """kv_mvp 결과(out) 폴더를 찾는다."""
    env = os.environ.get("KV_OUT_ROOT")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))

    cwd = Path.cwd()
    candidates += [
        cwd / "kv_mvp" / "out",
        cwd / ".." / "kv_mvp" / "out",
        cwd / ".." / "kv" / "kv_mvp" / "out",
    ]

    here = Path(__file__).resolve().parent
    candidates += [
        here / "kv_mvp" / "out",
        here / ".." / "kv_mvp" / "out",
        here / ".." / "kv_mvp" / "kv_mvp" / "out",
    ]

    for p in candidates:
        try:
            if p.exists() and p.is_dir():
                return p.resolve()
        except Exception:
            continue

    raise FileNotFoundError(
        "kv_mvp out 폴더를 찾지 못했습니다. 환경변수 KV_OUT_ROOT를 설정하거나, "
        "프로젝트 폴더 기준으로 kv_mvp/out 경로에 kv_mvp 결과물이 있어야 합니다."
    )


def _find_product_json(out_root: Path, code: str) -> Path:
    """품번에 해당하는 product.json 위치를 찾는다."""
    c = str(code).strip()
    if not c:
        raise FileNotFoundError("code is empty")

    candidates = [
        out_root / c / "product.json",
        out_root / "JSON" / f"v{c}" / "product.json",
        out_root / "JSON" / c / "product.json",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    raise FileNotFoundError(f"product.json not found for code={c}")


def _err(e: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/api/open-smartstore")
def api_open_smartstore():
    try:
        open_smartstore()
        return {"ok": True}
    except Exception as e:
        raise _err(e)


@app.post("/api/check-login")
def api_check_login():
    try:
        return {"logged_in": bool(check_logged_in())}
    except Exception as e:
        raise _err(e)


@app.post("/api/go-register")
def api_go_register():
    try:
        go_product_register()
        return {"ok": True}
    except Exception as e:
        raise _err(e)


@app.post("/api/set-category")
def api_set_category(req: ApplyReq):
    """
    버튼(상품입력하기)에서 호출:
    - 카테고리(query), 상품명(product_name), 판매가(sale_price)를 "사람 입력 방식"으로 적용.
    - 셋 중 하나만 보내도 동작.
    - go_register_and_apply 내부에서 '이미 상품등록 화면이면 이동 생략' 처리됨.
    """
    try:
        q = (req.query or "").strip()
        n = (req.product_name or "").strip()
        sp = req.sale_price

        if not q and not n and sp is None:
            raise ValueError("query/product_name/sale_price are all empty")

        go_register_and_apply(
            query=q or None,
            product_name=n or None,
            sale_price=sp,
        )

        return {"ok": True}
    except Exception as e:
        raise _err(e)


@app.post("/api/go-register-and-set-category")
def api_go_register_and_set_category(req: ApplyReq):
    try:
        q = (req.query or "").strip()
        if not q:
            raise ValueError("query is empty")
        go_register_and_set_category(q)
        return {"ok": True}
    except Exception as e:
        raise _err(e)


# ---------------- kv_mvp 연동 (읽기 전용) ----------------

@app.get("/api/kv/health")
def api_kv_health():
    try:
        out_root = _resolve_kv_out_root()
        return {"ok": True, "out_root": str(out_root)}
    except Exception as e:
        raise _err(e)


@app.get("/api/kv/list")
def api_kv_list():
    try:
        out_root = _resolve_kv_out_root()
        items = []
        for p in out_root.iterdir():
            if p.is_dir() and (p / "product.json").exists():
                items.append(p.name)
        items.sort()
        return {"ok": True, "count": len(items), "codes": items}
    except Exception as e:
        raise _err(e)


@app.get("/api/kv/product/{code}")
def api_kv_product(code: str):
    try:
        out_root = _resolve_kv_out_root()
        pj = _find_product_json(out_root, code)
        data = json.loads(pj.read_text(encoding="utf-8"))

        payload = {
            "ok": True,
            "code": data.get("code") or code,
            "title": data.get("title"),
            "list_price": data.get("list_price"),
            "sale_price": data.get("sale_price"),
            "source_url": data.get("source_url"),
            "_paths": {
                "product_json": str(pj),
                "out_dir": str(pj.parent),
            },
            "raw": data,
        }
        return payload
    except Exception as e:
        raise _err(e)


@app.post("/api/kv/product")
def api_kv_product_post(req: KvProductReq):
    return api_kv_product(req.code)
