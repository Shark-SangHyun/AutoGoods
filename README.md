# AutoGoods (NaverGoods + kv_mvp 연동 기본)

목표:
- kv_mvp 실행 결과(`kv_mvp/out/.../product.json`)를 **변경 없이** 읽어서
- NaverGoods의 `static/register.html`에서 품번 기준으로 자동 채움(사용자 검수/수정은 수동)
- 스마트스토어 자동화는 **로그인 + 상품등록 화면 이동까지만** 제공

## 폴더 구조
- `kv_mvp/` : 원본 kv_mvp (코드 수정 없음)
- `kv_mvp/out/` : kv_mvp 실행 결과 저장 폴더
- `static/register.html` : 품번 입력 + KV 데이터 불러오기 버튼
- `server.py` : FastAPI 서버 (KV 읽기 전용 API 포함)
- `selenium_runner.py` : Selenium (로그인/상품등록 이동)

## 실행
```bash
python -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

브라우저:
- http://127.0.0.1:8000/static/register.html
- (로그인/이동 테스트) http://127.0.0.1:8000/static/index.html 또는 next.html

## KV 연동 확인
- http://127.0.0.1:8000/api/kv/health
- http://127.0.0.1:8000/api/kv/list
- http://127.0.0.1:8000/api/kv/product/{품번}

## kv_mvp out 경로가 다를 때
기본은 `./kv_mvp/out` 를 찾도록 되어있음.
다르면 환경변수로 지정:

Windows PowerShell:
```powershell
setx KV_OUT_ROOT "C:\path\to\kv_mvp\out"
```
새 터미널을 열고 다시 실행.
