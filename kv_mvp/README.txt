반영 사항
1) <base href="상품 URL"> 추가: 상대경로 이미지/CSS가 복제 렌더링에서도 정상 로드
2) 더 상위 부모 컨테이너까지 복제: 원본 레이아웃(여백/정렬/폰트)을 최대한 보존
   - MD COMMENT: 상위 8단계
   - 아코디언(detail-table): 상위 6단계
3) lazy 이미지(data-src 등) -> src 승격 후 복제(이미지 누락 완화)
4) 복제 페이지에서 networkidle 대기(리소스 로딩 안정화)

출력:
- out/<code>/captures/md_comment.jpg
- out/<code>/captures/pd_accordion_material_care.jpg
- out/<code>/captures/pd_accordion_product_notice.jpg

실행:
pip install -r requirements.txt
python -m playwright install
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
