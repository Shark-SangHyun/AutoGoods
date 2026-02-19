// register.js
// - 폴더 선택(webkitdirectory) → product.json 자동 읽기
// - 폼 자동 채우기(title/list_price/sale_price/제조국/gvnt_info.제조연월(수입연월))
// - 상품명: POP/브랜드/성별/아이템 + JSON title + "SKU COLOR" 규칙 반영
// - sku/color는 상태 변수로 저장 후 재사용
// - JSON/log는 콘솔 + result 영역에 같이 출력

document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);

  // ---- Elements ----
  const skuInput = $("sku");
  const skuColorInput = $("skuColor");
  const btnPickSku = $("btnPickSku");
  const skuFolderInput = $("skuFolder");
  const btnDetect = $("btnDetect");
  const result = $("result");

  const productNameInput = $("productName");
  const productGroupInput = $("productGroup");

  const categoryQueryInput = $("categoryQuery");
  const teeTypeWrap = $("teeTypeWrap");
  const teeTypeSelect = $("teeType");
  const btnApplyCategory = $("btnApplyCategory");

  const priceOriginalInput = $("priceOriginal");
  const priceSaleInput = $("priceSale");
  const priceDiffInput = $("priceDiff");

  const originCountryInput = $("originCountry");
  const manufactureDateInput = $("manufactureDate");

  // ---- Logger (console + result append) ----
  function uiLog(...args) {
    console.log("[register]", ...args);
    if (!result) return;

    const msg = args
      .map((a) => {
        if (typeof a === "string") return a;
        try {
          return JSON.stringify(a);
        } catch {
          return String(a);
        }
      })
      .join(" ");

    result.textContent = (result.textContent ? result.textContent + "\n" : "") + msg;
  }

  uiLog("loaded");

  // =========================
  // 상품명 글자수 + 경고(50자)
  // =========================
  const PRODUCT_NAME_MAX = 100;
  const PRODUCT_NAME_WARN = 50;

  function updateProductNameCounter() {
    const input = document.getElementById("productName");
    const counter = document.getElementById("productNameCounter");
    const warning = document.getElementById("productNameWarning");

    if (!input || !counter) return;

    const len = (input.value || "").length;
    counter.textContent = `${len}/${PRODUCT_NAME_MAX}`;

    if (warning) {
      warning.textContent = len > PRODUCT_NAME_WARN ? "⚠ 권장 길이(50자)를 초과했습니다." : "";
    }
  }

  function setProductNameValue(v) {
    if (!productNameInput) return;
    productNameInput.value = v ?? "";
    updateProductNameCounter();
  }

  if (productNameInput) {
    productNameInput.addEventListener("input", updateProductNameCounter);
  }

  // ---- Maps ----
  const MAP_AGE = { D: "아이더 성인", J: "아이더 아동" };
  const MAP_GENDER = { M: "남성", W: "여성", U: "공용" };
  const MAP_GENDER_NAME = { M: "남자", W: "여자", U: "남여공용" };
  const MAP_SEASON = { P: "봄", M: "여름", U: "가을", W: "겨울", S: "S/S", F: "F/W", A: "ALL" };

  const MAP_ITEM = {
    "1": "자켓",
    "2": "티셔츠",
    "3": "바지",
    "4": "셔츠",
    "5": "다운(패딩)",
    "6": "베스트(조끼)",
    "7": "고어택스",
    "8": "속옷",
    "9": "용품",
    A: "캠핑",
    B: "가방",
    C: "모자",
    S: "양말",
    T: "스틱",
    V: "장갑",
    M: "SET(티/바지)",
    G: "고어택스신발",
    N: "일반신발",
  };

  const MAP_BRAND_NAME = { D: "아이더", J: "아이더 아동" };
  const MAP_GENDER_LABEL = { M: "남성", W: "여성", U: "남녀공용" };

  const skuState = {
    sku8: "",
    color2: "",
    set(nextSku8, nextColor2) {
      this.sku8 = String(nextSku8 || "").trim().toUpperCase().slice(0, 8);
      this.color2 = String(nextColor2 || "").trim().toUpperCase().slice(0, 2);
    },
    syncFromInputs() {
      this.set(skuInput?.value || "", skuColorInput?.value || "");
    },
    skuText() {
      return `${this.sku8} ${this.color2}`.trim();
    },
  };

  function lineToGroup(n) {
    if (n >= 1 && n <= 40) return "M";
    if (n >= 41 && n <= 80) return "C";
    if (n >= 81 && n <= 99) return "P";
    return null;
  }

  function classifyProductGroup(itemCode) {
    const code = String(itemCode || "").toUpperCase();
    if (["1", "2", "3", "4", "5", "6", "7", "8", "M"].includes(code)) return "의류";
    if (["N", "G"].includes(code)) return "구두/신발";
    if (code === "B") return "가방";
    if (["A", "T"].includes(code)) return "스포츠용품";
    return "패션잡화";
  }

  function categoryPathByItemCode(itemCode, teeType) {
    const code = String(itemCode || "").toUpperCase();

    const MAP = {
      "1": "스포츠/레저>등산>등산의류>재킷",
      "5": "스포츠/레저>등산>등산의류>점퍼",
      "3": "스포츠/레저>등산>등산의류>바지",
      "6": "스포츠/레저>등산>등산의류>조끼",
      "8": "스포츠/레저>등산>등산의류>기능성언더웨어",
      G: "스포츠/레저>등산>등산화",
      N: "스포츠/레저>등산>등산화",
      B: "스포츠/레저>등산>등산가방",
      C: "스포츠/레저>등산>등산잡화>모자",
      S: "스포츠/레저>등산>등산잡화>양말",
      V: "스포츠/레저>등산>등산잡화>장갑",
      T: "스포츠/레저>등산>등산장비>스틱",
    };

    if (code === "2") {
      return teeType === "short"
        ? "스포츠/레저>등산>등산의류>반팔티셔츠"
        : "스포츠/레저>등산>등산의류>긴팔티셔츠";
    }

    return MAP[code] || "";
  }

  function parseSku(raw) {
    const s = String(raw || "").trim().toUpperCase();
    if (s.length !== 8) return { ok: false, error: "품번은 8자리로 입력해야 합니다." };

    const ageCode = s[0];
    const genderCode = s[1];
    const seasonCode = s[2];
    const yearCode = s.slice(3, 5);
    const itemCode = s[5];
    const lineCode = s.slice(6, 8);

    if (!/^\d{2}$/.test(yearCode)) return { ok: false, error: "연도 구분(4번)은 숫자 2자리여야 합니다. (예: 26)" };
    if (!/^\d{2}$/.test(lineCode)) return { ok: false, error: "라인 구분(6번)은 숫자 2자리여야 합니다. (예: 01~99)" };

    if (!MAP_AGE[ageCode]) return { ok: false, error: "연령 구분(1번)이 올바르지 않습니다. (D/J)" };
    if (!MAP_GENDER[genderCode]) return { ok: false, error: "성별 구분(2번)이 올바르지 않습니다. (M/W/U)" };
    if (!MAP_SEASON[seasonCode]) return { ok: false, error: "시즌 구분(3번)이 올바르지 않습니다. (P/M/U/W/S/F/A)" };
    if (!MAP_ITEM[itemCode]) return { ok: false, error: "아이템 구분(5번)이 올바르지 않습니다." };

    const yearNum = Number(yearCode);
    const fullYear = 2000 + yearNum;

    const lineNum = Number(lineCode);
    if (lineNum < 1 || lineNum > 99) return { ok: false, error: "라인 구분(6번)은 01~99 범위여야 합니다." };

    const lineGroup = lineToGroup(lineNum);
    if (!lineGroup) return { ok: false, error: "라인 구분(6번)이 범위를 벗어났습니다." };

    return {
      ok: true,
      normalized: s,
      parts: {
        "1. 연령": { code: ageCode, value: MAP_AGE[ageCode] },
        "2. 성별": { code: genderCode, value: MAP_GENDER[genderCode] },
        "3. 시즌": { code: seasonCode, value: MAP_SEASON[seasonCode] },
        "4. 연도": { code: yearCode, value: `${fullYear}년도` },
        "5. 아이템": { code: itemCode, value: MAP_ITEM[itemCode] },
        "6. 라인": { code: lineCode, value: `${String(lineNum).padStart(2, "0")} (구분: ${lineGroup})` },
      },
      meta: { genderName: MAP_GENDER_NAME[genderCode], itemCode },
    };
  }

  function renderResult(parsed) {
    if (!result) return;

    if (!parsed.ok) {
      result.textContent = `❌ 잘못 입력되었습니다.\n- ${parsed.error}\n\n예시: DMU26101`;
      return;
    }

    const lines = [`✅ 식별 완료: ${parsed.normalized}`, ""];
    for (const [k, v] of Object.entries(parsed.parts)) lines.push(`${k}  ${v.code}  →  ${v.value}`);
    result.textContent = lines.join("\n");
  }

  function buildFinalProductNameFromState(jsonTitle) {
    const sku8 = skuState.sku8;
    const color2 = skuState.color2;
    const title = String(jsonTitle ?? "").trim();

    if (!sku8 || sku8.length !== 8) return title;

    const pop = sku8[6] === "8" || sku8[6] === "9" ? "POP " : "";
    const brand = MAP_BRAND_NAME[sku8[0]] || "";
    const gender = MAP_GENDER_LABEL[sku8[1]] || "";
    const itemText = MAP_ITEM[sku8[5]] || "";
    const suffix = `${sku8} ${color2}`.trim();

    return `${pop}${brand} ${gender} ${itemText} ${title} ${suffix}`.replace(/\s+/g, " ").trim();
  }

  function runDetect() {
    if (!skuInput) return;

    skuState.syncFromInputs();

    const parsed = parseSku(skuInput.value);
    renderResult(parsed);
    if (!parsed.ok) return;

    setProductNameValue(buildFinalProductNameFromState(""));

    if (productGroupInput) productGroupInput.value = classifyProductGroup(parsed.meta.itemCode);

    const isTee = String(parsed.meta.itemCode || "").toUpperCase() === "2";
    if (teeTypeWrap) teeTypeWrap.style.display = isTee ? "" : "none";

    const teeType = teeTypeSelect ? teeTypeSelect.value : "long";
    const path = categoryPathByItemCode(parsed.meta.itemCode, teeType);
    if (categoryQueryInput && path) categoryQueryInput.value = path;
  }

  function splitSkuAndColor(folderName) {
    const s = String(folderName || "").trim().toUpperCase();
    if (s.length >= 10) return { sku: s.slice(0, s.length - 2).slice(0, 8), color: s.slice(-2) };
    if (s.length === 8) return { sku: s, color: "" };
    if (s.length > 8) return { sku: s.slice(0, 8), color: s.slice(8, 10) || "" };
    return { sku: s, color: "" };
  }

  function lockSkuFields(lock) {
    if (skuInput) {
      skuInput.readOnly = !!lock;
      skuInput.classList.toggle("locked", !!lock);
    }
    if (skuColorInput) {
      skuColorInput.readOnly = !!lock;
      skuColorInput.classList.toggle("locked", !!lock);
    }
  }

  function onlyNumberText(s) {
    return String(s || "").replace(/[^\d]/g, "");
  }

  function formatKRW(n) {
    if (!Number.isFinite(n)) return "";
    return n.toLocaleString("ko-KR");
  }

  function calcPriceDiff() {
    if (!priceOriginalInput || !priceSaleInput || !priceDiffInput) return;

    const original = Number(onlyNumberText(priceOriginalInput.value));
    const sale = Number(onlyNumberText(priceSaleInput.value));

    if (!original && !sale) {
      priceDiffInput.value = "";
      return;
    }

    const diff = original - sale;
    priceDiffInput.value = `${formatKRW(diff)}원`;
  }

  function formatManufactureDate(raw) {
    if (!raw) return "";

    const match = String(raw).match(/(\d{4})\D*(\d{1,2})/);
    if (!match) return String(raw);

    const year = match[1];
    const month = match[2].padStart(2, "0");
    return `${year}.${month}.01`;
  }

  async function readProductJsonFromFolder(fileList) {
    if (!fileList || fileList.length === 0) return null;

    const files = Array.from(fileList);
    const jsonFile = files.find((f) => (f.name || "").toLowerCase() === "product.json");
    if (!jsonFile) return null;

    uiLog("product.json found:", jsonFile.webkitRelativePath || jsonFile.name);

    const text = await jsonFile.text();
    const data = JSON.parse(text);

    uiLog("product.json parsed keys:", Object.keys(data || {}));
    uiLog("json.title:", data.title);
    uiLog("json.list_price:", data.list_price, "json.sale_price:", data.sale_price, "json.제조국:", data["제조국"]);
    uiLog("json.제조연월(수입연월):", data.gvnt_info?.["제조연월(수입연월)"]);

    return data;
  }

  function applyProductJson(data) {
    if (!data || typeof data !== "object") return;

    const finalName = buildFinalProductNameFromState(data.title);
    setProductNameValue(finalName);

    if (priceOriginalInput) priceOriginalInput.value = data.list_price != null ? String(data.list_price) : "";
    if (priceSaleInput) priceSaleInput.value = data.sale_price != null ? String(data.sale_price) : "";
    if (originCountryInput) originCountryInput.value = String(data["제조국"] ?? "");

    const rawDate = data.gvnt_info?.["제조연월(수입연월)"];
    if (manufactureDateInput && rawDate) {
      const formatted = formatManufactureDate(rawDate);
      manufactureDateInput.value = formatted;
      uiLog("제조연월 변환:", rawDate, "→", formatted);
    }

    calcPriceDiff();
  }

  async function handleFolderPicked(fileList) {
    if (!fileList || fileList.length === 0) return;

    const anyFile = fileList[0];
    const rel = anyFile.webkitRelativePath || "";
    const topFolder = rel ? rel.split("/")[0] : "";

    uiLog("folder picked top:", topFolder || "(unknown)");
    uiLog("first file relpath:", rel || "(no webkitRelativePath)");

    const { sku, color } = splitSkuAndColor(topFolder);

    if (skuInput) skuInput.value = sku;
    if (skuColorInput) skuColorInput.value = color;
    skuState.set(sku, color);

    lockSkuFields(true);
    runDetect();

    try {
      const data = await readProductJsonFromFolder(fileList);
      if (!data) {
        uiLog("product.json not found in selected folder.");
        return;
      }
      applyProductJson(data);
    } catch (e) {
      uiLog("product.json read/parse failed:", e?.message || String(e));
      alert("product.json 읽기 실패: " + (e?.message || String(e)));
    }
  }

  if (btnDetect) {
    btnDetect.addEventListener("click", (e) => {
      e.preventDefault();
      runDetect();
    });
  }

  if (skuInput) {
    skuInput.addEventListener("input", () => skuState.syncFromInputs());
    skuInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        runDetect();
      }
    });
  }

  if (skuColorInput) {
    skuColorInput.addEventListener("input", () => skuState.syncFromInputs());
  }

  if (teeTypeSelect) {
    teeTypeSelect.addEventListener("change", () => {
      if (!skuInput) return;
      const parsed = parseSku(skuInput.value);
      if (!parsed.ok) return;

      const path = categoryPathByItemCode(parsed.meta.itemCode, teeTypeSelect.value);
      if (categoryQueryInput && path) categoryQueryInput.value = path;
    });
  }

  if (priceOriginalInput) priceOriginalInput.addEventListener("input", calcPriceDiff);
  if (priceSaleInput) priceSaleInput.addEventListener("input", calcPriceDiff);

  // ✅ 상품입력하기: 카테고리 + 상품명 + 판매가 전송
  if (btnApplyCategory) {
    btnApplyCategory.addEventListener("click", async () => {
      const q = String(categoryQueryInput?.value || "").trim();
      const name = String(productNameInput?.value || "").trim();
      const salePriceNum = Number(onlyNumberText(priceSaleInput?.value || ""));

      const sale_price = Number.isFinite(salePriceNum) && salePriceNum > 0 ? salePriceNum : null;

      if (!q && !name && sale_price === null) {
        alert("카테고리/상품명/판매가 중 최소 1개는 있어야 합니다.");
        return;
      }

      try {
        btnApplyCategory.disabled = true;

        const res = await fetch("/api/set-category", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: q || null,
            product_name: name || null,
            sale_price,
          }),
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);

        alert("상품 입력 완료");
      } catch (e) {
        alert(`실패: ${e.message}`);
      } finally {
        btnApplyCategory.disabled = false;
      }
    });
  }

  if (btnPickSku && skuFolderInput) {
    btnPickSku.addEventListener("click", (e) => {
      e.preventDefault();
      skuFolderInput.value = "";
      skuFolderInput.click();
    });

    skuFolderInput.addEventListener("change", () => {
      handleFolderPicked(skuFolderInput.files);
    });
  } else {
    uiLog("WARN: btnPickSku or skuFolderInput missing", {
      btnPickSku: !!btnPickSku,
      skuFolderInput: !!skuFolderInput,
    });
  }

  lockSkuFields(false);
  skuState.syncFromInputs();
  updateProductNameCounter();
});
