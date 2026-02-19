const btn = document.getElementById("openSmartstore");
const statusEl = document.getElementById("status");

btn.addEventListener("click", async () => {
  btn.disabled = true;
  statusEl.textContent = "스마트스토어 여는 중...";

  try {
    const res = await fetch("/api/open-smartstore", { method: "POST" });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);

    statusEl.textContent = "요청 완료. 새 크롬 창(또는 탭)에서 스마트스토어가 열립니다.\n다음 페이지로 이동합니다.";

    // “스마트스토어 열기”를 트리거한 뒤, 내 페이지는 다음 화면으로 이동
    window.location.href = "/static/next.html";
  } catch (e) {
    statusEl.textContent = `실패: ${e.message}\n- Python 서버가 실행 중인지 확인하세요.`;
    btn.disabled = false;
  }
});
