import {
  BarcodePresenceTracker,
  addSessionUnit,
  sessionIsReadyToSave,
  setSessionItemLocation
} from "./scanner-state.mjs";

const config = window.__FRIDIVO_CONFIG__ || {};
const API_BASE_URL = String(config.apiBaseUrl || "").replace(/\/$/, "");
const TOKEN_KEY = "fridivo_access_token";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const elements = {
  boot: $("#boot-screen"), login: $("#login-screen"), authenticated: $("#authenticated-app"),
  loginForm: $("#login-form"), loginButton: $("#login-button"), loginError: $("#login-error"),
  inventoryView: $("#inventory-view"), searchView: $("#search-view"), inventoryList: $("#inventory-list"),
  inventoryLoading: $("#inventory-loading"), inventoryEmpty: $("#inventory-empty"), inventoryError: $("#inventory-error"),
  inventoryCount: $("#inventory-count"), fab: $("#fab-add"), searchForm: $("#search-form"),
  searchInput: $("#search-input"), clearSearch: $("#clear-search"), searchResults: $("#search-results"),
  searchLoading: $("#search-loading"), searchEmpty: $("#search-empty"), searchError: $("#search-error"), searchWelcome: $("#search-welcome"),
  backdrop: $("#sheet-backdrop"), sheet: $("#add-sheet"), selectedProduct: $("#selected-product"),
  addForm: $("#add-form"), addError: $("#add-error"), confirmAdd: $("#confirm-add"),
  quantityValue: $("#quantity-value"), expiryDate: $("#expiry-date"), toast: $("#toast"),
  scannerModal: $("#scanner-modal"), scannerLive: $("#scanner-live"), scannerSummary: $("#scanner-summary"),
  scannerVideo: $("#scanner-video"), cameraLoading: $("#camera-loading"), cameraError: $("#camera-error"),
  cameraErrorMessage: $("#camera-error-message"), scanFeedback: $("#scan-feedback"), scanFeedbackText: $("#scan-feedback-text"),
  scanAddOne: $("#scan-add-one"), scanRecent: $("#scan-recent"),
  scanTotal: $("#scan-total"), summaryList: $("#summary-list"), summaryEmpty: $("#summary-empty"),
  summaryOptions: $("#summary-options"), scanExpiryDate: $("#scan-expiry-date"),
  scannerSaveError: $("#scanner-save-error"), confirmScanned: $("#confirm-scanned")
};

let token = sessionStorage.getItem(TOKEN_KEY);
let selectedProduct = null;
let quantity = 1;
let toastTimer;
let lastFocusedElement;
let scannerStream = null;
let scannerFrame = null;
let scannerDetector = null;
let zxingControls = null;
let cameraStartId = 0;
let scannerActive = false;
let detectionPending = false;
let feedbackTimer;
let scanAudioContext = null;
let nextScanBeepAt = 0;
let manualAddBarcode = null;
const scanSession = new Map();
const barcodePresence = new BarcodePresenceTracker();
const scanLookups = new Set();
const pendingScanUnits = new Map();
const unknownScans = [];
const BARCODE_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"];
const HELD_NOTICE_DELAY_MS = 1200;

class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (response.status === 401 && path !== "/api/v1/auth/login") {
    clearSession();
    showLogin("La sessione è scaduta. Accedi di nuovo.");
    throw new ApiError(401, "session_expired");
  }
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).detail || ""; } catch { /* response without JSON */ }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? null : response.json();
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
  button.setAttribute("aria-busy", String(loading));
}

function setMessage(element, message = "") {
  element.textContent = message;
  element.hidden = !message;
}

function clearSession() {
  token = null;
  sessionStorage.removeItem(TOKEN_KEY);
}

function showLogin(message = "") {
  elements.boot.hidden = true;
  elements.authenticated.hidden = true;
  elements.login.hidden = false;
  closeSheet();
  closeScanner();
  setMessage(elements.loginError, message);
}

function showApp() {
  elements.boot.hidden = true;
  elements.login.hidden = true;
  elements.authenticated.hidden = false;
  showView("inventory");
}

function userMessage(error, context) {
  if (error.status === 0) return "Non riusciamo a contattare Fridivo. Controlla la connessione.";
  if (error.status === 401) return context === "login" ? "Email o password non corretti." : "La sessione è scaduta. Accedi di nuovo.";
  if (error.status === 404) return context === "add" ? "Questo prodotto non è più disponibile nel catalogo." : "Prodotto non trovato.";
  if (error.status === 409) return "Questo prodotto è già presente nella tua dispensa.";
  if (error.status === 422) return context === "search" ? "Inserisci almeno 2 caratteri per cercare." : "Controlla i dati inseriti e riprova.";
  return "Qualcosa non ha funzionato. Riprova tra poco.";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function productImage(product) {
  const name = escapeHtml(product.product_name || product.name || "Prodotto");
  if (!product.image_url) return '<div class="product-image image-fallback" aria-hidden="true">🥫</div>';
  return `<img class="product-image" src="${escapeHtml(product.image_url)}" alt="${name}" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=&quot;product-image image-fallback&quot; aria-hidden=&quot;true&quot;>🥫</div>'" />`;
}

const locations = { fridge: "Frigorifero", freezer: "Congelatore", pantry: "Dispensa", other: "Altro" };
const summaryStorageLocations = [
  { value: "fridge", label: "Frigo", icon: '<svg viewBox="0 0 24 24"><rect x="6" y="3" width="12" height="18" rx="2"/><path d="M6 10h12M9 6v2M9 13v3"/></svg>' },
  { value: "freezer", label: "Freezer", icon: '<svg viewBox="0 0 24 24"><path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9 5l3 2 3-2M9 19l3-2 3 2"/></svg>' },
  { value: "pantry", label: "Dispensa", icon: '<svg viewBox="0 0 24 24"><path d="M4 6h16v14H4zM4 11h16M8 8h3M8 14h3"/></svg>' },
  { value: "other", label: "Altro", icon: '<svg viewBox="0 0 24 24"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/></svg>' }
];

function expiryMeta(dateValue) {
  if (!dateValue) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const expiry = new Date(`${dateValue}T00:00:00`);
  const days = Math.round((expiry - today) / 86400000);
  const formatted = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short" }).format(expiry);
  if (days < 0) return `<span class="expiry expired">Scaduto · ${formatted}</span>`;
  if (days === 0) return '<span class="expiry soon">Scade oggi</span>';
  if (days <= 7) return `<span class="expiry soon">Scade tra ${days} ${days === 1 ? "giorno" : "giorni"}</span>`;
  return `<span class="expiry">Scade il ${formatted}</span>`;
}

function renderInventory(items) {
  const sorted = [...items].sort((a, b) => {
    if (!a.expiry_date && !b.expiry_date) return 0;
    if (!a.expiry_date) return 1;
    if (!b.expiry_date) return -1;
    return a.expiry_date.localeCompare(b.expiry_date);
  });
  elements.inventoryCount.textContent = `${items.length} ${items.length === 1 ? "prodotto" : "prodotti"}`;
  elements.inventoryCount.hidden = items.length === 0;
  elements.inventoryEmpty.hidden = items.length !== 0;
  elements.inventoryList.innerHTML = sorted.map((item) => `
    <article class="product-card">
      ${productImage(item)}
      <div class="product-info">
        <h2 class="product-name">${escapeHtml(item.product_name || "Prodotto")}</h2>
        ${item.brands ? `<p class="product-brand">${escapeHtml(item.brands)}</p>` : ""}
        <div class="product-meta">
          <span class="quantity-pill">${item.quantity} ${item.quantity === 1 ? "pezzo" : "pezzi"}</span>
          ${item.product_quantity ? `<span>${escapeHtml(item.product_quantity)}</span>` : ""}
          <span>${escapeHtml(locations[item.storage_location] || "Altro")}</span>
          ${expiryMeta(item.expiry_date)}
        </div>
      </div>
    </article>`).join("");
}

async function loadInventory() {
  elements.inventoryLoading.hidden = false;
  elements.inventoryError.hidden = true;
  elements.inventoryEmpty.hidden = true;
  elements.inventoryList.innerHTML = "";
  try {
    renderInventory(await api("/api/v1/inventory"));
  } catch (error) {
    if (error.status !== 401) elements.inventoryError.hidden = false;
  } finally {
    elements.inventoryLoading.hidden = true;
  }
}

function showView(viewName) {
  const inventory = viewName === "inventory";
  elements.inventoryView.hidden = !inventory;
  elements.searchView.hidden = inventory;
  elements.fab.hidden = !inventory;
  $$(".nav-item").forEach((item) => {
    const active = item.dataset.view === viewName;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
  });
  if (inventory) loadInventory(); else setTimeout(() => elements.searchInput.focus(), 50);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetSearchStates() {
  elements.searchLoading.hidden = true;
  elements.searchEmpty.hidden = true;
  elements.searchError.hidden = true;
  elements.searchWelcome.hidden = true;
  elements.searchResults.innerHTML = "";
}

async function searchProducts(query) {
  resetSearchStates();
  elements.searchLoading.hidden = false;
  try {
    const response = await api(`/api/v1/products/search?q=${encodeURIComponent(query)}`);
    const products = response.items || [];
    elements.searchEmpty.hidden = products.length !== 0;
    elements.searchResults.innerHTML = products.map((product, index) => `
      <button class="product-card search-result" type="button" data-index="${index}">
        ${productImage(product)}
        <div class="product-info">
          <h2 class="product-name">${escapeHtml(product.name || "Prodotto")}</h2>
          ${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}
          ${product.quantity ? `<div class="product-meta"><span>${escapeHtml(product.quantity)}</span></div>` : ""}
        </div>
        <span class="select-cue" aria-hidden="true">›</span>
      </button>`).join("");
    $$(".search-result").forEach((button) => button.addEventListener("click", () => openSheet(products[Number(button.dataset.index)], button)));
  } catch (error) {
    if (error.status !== 401) {
      elements.searchError.hidden = false;
      elements.searchError.querySelector("p").textContent = userMessage(error, "search");
    }
  } finally {
    elements.searchLoading.hidden = true;
  }
}

function openSheet(product, trigger) {
  selectedProduct = product;
  quantity = 1;
  elements.quantityValue.textContent = quantity;
  elements.expiryDate.value = "";
  elements.addForm.elements.location.value = "fridge";
  setMessage(elements.addError);
  elements.selectedProduct.innerHTML = `${productImage(product)}<div><h3 class="product-name">${escapeHtml(product.name || "Prodotto")}</h3>${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}${product.quantity ? `<div class="product-meta">${escapeHtml(product.quantity)}</div>` : ""}</div>`;
  lastFocusedElement = trigger || document.activeElement;
  elements.backdrop.hidden = false;
  elements.sheet.hidden = false;
  document.body.classList.add("sheet-open");
  setTimeout(() => $("#quantity-minus").focus(), 50);
}

function closeSheet() {
  if (elements.sheet.hidden) return;
  elements.sheet.hidden = true;
  elements.backdrop.hidden = true;
  document.body.classList.remove("sheet-open");
  selectedProduct = null;
  lastFocusedElement?.focus();
}

function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function scannedUnitCount() {
  return [...scanSession.values()].reduce((total, item) => total + item.quantity, 0);
}

function setScanFeedback(message, type = "", reset = true, manualBarcode = null) {
  clearTimeout(feedbackTimer);
  elements.scanFeedback.className = `scan-feedback ${type}`.trim();
  elements.scanFeedbackText.textContent = message;
  manualAddBarcode = manualBarcode;
  elements.scanAddOne.hidden = !manualBarcode;
  if (reset && scannerActive) {
    feedbackTimer = setTimeout(() => setScanFeedback("Inquadra il prossimo barcode", "", false), 1600);
  }
}

function initializeScanAudio() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  try {
    if (!scanAudioContext) scanAudioContext = new AudioContextClass();
    if (scanAudioContext.state === "suspended") scanAudioContext.resume().catch(() => {});
    const oscillator = scanAudioContext.createOscillator();
    const gain = scanAudioContext.createGain();
    gain.gain.value = 0;
    oscillator.connect(gain);
    gain.connect(scanAudioContext.destination);
    oscillator.start();
    oscillator.stop(scanAudioContext.currentTime + 0.005);
  } catch {
    scanAudioContext = null;
  }
}

function playScanBeep() {
  if (!scanAudioContext || scanAudioContext.state === "closed") return;
  try {
    if (scanAudioContext.state === "suspended") scanAudioContext.resume().catch(() => {});
    const now = Math.max(scanAudioContext.currentTime, nextScanBeepAt);
    nextScanBeepAt = now + 0.09;
    const oscillator = scanAudioContext.createOscillator();
    const gain = scanAudioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, now);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.055, now + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.065);
    oscillator.connect(gain);
    gain.connect(scanAudioContext.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.07);
  } catch {
    // Audio is optional; visual feedback and scanning continue normally.
  }
}

function provideUnitFeedback() {
  playScanBeep();
  if (navigator.vibrate) navigator.vibrate(70);
}

function commitScannedUnit(barcode, product, keepManualAction = false) {
  const item = addSessionUnit(scanSession, barcode, product, provideUnitFeedback);
  renderScanSession();
  if (keepManualAction) {
    setScanFeedback(`Già scansionato · ${product.name || "Prodotto"} ×${item.quantity}`, "", false, barcode);
  } else {
    setScanFeedback(`${product.name || "Prodotto"} · ×${item.quantity}`, "success");
  }
  return item;
}

function renderScanSession() {
  const items = [...scanSession.values()].sort((a, b) => b.lastScannedAt - a.lastScannedAt);
  const total = scannedUnitCount();
  elements.scanTotal.textContent = `${total} unità`;
  const knownRows = items.slice(0, 4).map(({ product, quantity: itemQuantity }) => `
    <div class="scan-recent-item">
      ${productImage(product)}
      <div><p class="product-name">${escapeHtml(product.name || "Prodotto")}</p>${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}</div>
      <span class="scan-quantity">×${itemQuantity}</span>
    </div>`);
  const unknownRows = unknownScans.slice(0, Math.max(0, 4 - knownRows.length)).map(({ barcode }) => `
    <div class="scan-recent-item">
      <div class="product-image image-fallback" aria-hidden="true">?</div>
      <div><p class="product-name">Prodotto non riconosciuto</p><p class="product-brand">${escapeHtml(barcode)}</p></div>
    </div>`);
  elements.scanRecent.innerHTML = knownRows.length || unknownRows.length
    ? [...knownRows, ...unknownRows].join("")
    : '<p class="scan-empty">I prodotti riconosciuti appariranno qui.</p>';
}

function cameraErrorMessage(error) {
  if (!window.isSecureContext) return "La fotocamera richiede una connessione HTTPS sicura.";
  if (!("BarcodeDetector" in window) && !window.ZXingBrowser?.BrowserMultiFormatReader) return "Questo browser non supporta la scansione barcode. Puoi continuare con la ricerca manuale.";
  if (!navigator.mediaDevices?.getUserMedia) return "Questo browser non consente l’accesso alla fotocamera.";
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") return "Il permesso fotocamera è stato negato. Abilitalo nelle impostazioni del browser o usa la ricerca manuale.";
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") return "Non è stata trovata una fotocamera utilizzabile.";
  if (error?.name === "NotReadableError" || error?.name === "TrackStartError") return "La fotocamera è già in uso o non può essere avviata.";
  return "Non è stato possibile avviare la scansione. Puoi usare la ricerca manuale.";
}

function showCameraError(error) {
  stopCamera();
  elements.cameraLoading.hidden = true;
  elements.cameraErrorMessage.textContent = cameraErrorMessage(error);
  elements.cameraError.hidden = false;
  setScanFeedback("Scansione non disponibile", "warning", false);
}

async function createBarcodeDetector() {
  if (!("BarcodeDetector" in window)) throw new DOMException("Barcode detector unsupported", "NotSupportedError");
  if (typeof window.BarcodeDetector.getSupportedFormats !== "function") return new window.BarcodeDetector({ formats: BARCODE_FORMATS });
  const supported = await window.BarcodeDetector.getSupportedFormats();
  const formats = BARCODE_FORMATS.filter((format) => supported.includes(format));
  if (!formats.length) throw new DOMException("Barcode formats unsupported", "NotSupportedError");
  return new window.BarcodeDetector({ formats });
}

function stopCamera() {
  cameraStartId += 1;
  scannerActive = false;
  detectionPending = false;
  if (scannerFrame !== null) cancelAnimationFrame(scannerFrame);
  scannerFrame = null;
  scannerDetector = null;
  if (zxingControls) zxingControls.stop();
  zxingControls = null;
  if (scannerStream) scannerStream.getTracks().forEach((track) => track.stop());
  scannerStream = null;
  elements.scannerVideo.pause();
  elements.scannerVideo.srcObject = null;
}

async function lookupScannedBarcode(barcode) {
  if (scanLookups.has(barcode)) {
    pendingScanUnits.set(barcode, (pendingScanUnits.get(barcode) || 0) + 1);
    return;
  }
  scanLookups.add(barcode);
  pendingScanUnits.set(barcode, 1);
  try {
    const product = await api(`/api/v1/products/barcode/${encodeURIComponent(barcode)}`);
    const units = pendingScanUnits.get(barcode) || 1;
    for (let unit = 0; unit < units; unit += 1) commitScannedUnit(barcode, product);
  } catch (error) {
    if (error.status === 404) {
      unknownScans.unshift({ barcode, scannedAt: Date.now() });
      renderScanSession();
      setScanFeedback("Prodotto non riconosciuto", "warning");
    } else if (error.status !== 401) {
      setScanFeedback("Errore di lookup. Continua con il prossimo prodotto.", "warning");
    }
  } finally {
    scanLookups.delete(barcode);
    pendingScanUnits.delete(barcode);
  }
}

function registerBarcodeEntry(barcode) {
  const knownItem = scanSession.get(barcode);
  if (knownItem) commitScannedUnit(barcode, knownItem.product);
  else lookupScannedBarcode(barcode);
}

function showHeldBarcodeAction(barcode) {
  const item = scanSession.get(barcode);
  if (!item) return;
  barcodePresence.markBlockedNoticeShown(barcode);
  setScanFeedback(`Già scansionato · ${item.product.name || "Prodotto"} ×${item.quantity}`, "", false, barcode);
}

function handleDetectionAttempt(rawValues, observedAt = Date.now(), completeFrame = true) {
  const events = barcodePresence.observe(rawValues, observedAt, { completeFrame });
  for (const barcode of events.exited) {
    if (manualAddBarcode === barcode) setScanFeedback("Inquadra il prossimo barcode", "", false);
  }
  for (const barcode of events.held) {
    const state = barcodePresence.stateFor(barcode);
    if (
      state
      && !state.blockedNoticeShown
      && observedAt - state.enteredAt >= HELD_NOTICE_DELAY_MS
    ) {
      showHeldBarcodeAction(barcode);
    }
  }
  for (const barcode of events.entered) registerBarcodeEntry(barcode);
  return events;
}

async function detectBarcodeFrame() {
  if (!scannerActive) return;
  if (!detectionPending && elements.scannerVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    detectionPending = true;
    try {
      const results = await scannerDetector.detect(elements.scannerVideo);
      handleDetectionAttempt(results.map((result) => result.rawValue));
    } catch (error) {
      if (error.name !== "InvalidStateError") showCameraError(error);
    } finally {
      detectionPending = false;
    }
  }
  if (scannerActive) scannerFrame = requestAnimationFrame(detectBarcodeFrame);
}

async function startCamera() {
  stopCamera();
  const startId = cameraStartId;
  elements.cameraError.hidden = true;
  elements.cameraLoading.hidden = false;
  setScanFeedback("Avvio fotocamera…", "", false);
  try {
    const constraints = {
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false
    };
    if ("BarcodeDetector" in window) {
      try {
        scannerDetector = await createBarcodeDetector();
      } catch (error) {
        if (error.name !== "NotSupportedError" || !window.ZXingBrowser?.BrowserMultiFormatReader) throw error;
      }
    }
    if (scannerDetector) {
      const streamPromise = navigator.mediaDevices.getUserMedia(constraints);
      streamPromise.then((stream) => {
        if (startId !== cameraStartId) stream.getTracks().forEach((track) => track.stop());
      }).catch(() => {});
      scannerStream = await streamPromise;
      if (startId !== cameraStartId) {
        scannerStream.getTracks().forEach((track) => track.stop());
        scannerStream = null;
        return;
      }
      elements.scannerVideo.srcObject = scannerStream;
      await elements.scannerVideo.play();
    } else if (window.ZXingBrowser?.BrowserMultiFormatReader) {
      const codeReader = new window.ZXingBrowser.BrowserMultiFormatReader(undefined, {
        delayBetweenScanAttempts: 250,
        delayBetweenScanSuccess: 250
      });
      const controlsPromise = codeReader.decodeFromConstraints(constraints, elements.scannerVideo, (result) => {
        handleDetectionAttempt(result ? [result.getText()] : [], Date.now(), false);
      });
      controlsPromise.then((controls) => {
        if (startId !== cameraStartId) controls.stop();
      }).catch(() => {});
      const controls = await controlsPromise;
      if (startId !== cameraStartId) {
        controls.stop();
        return;
      }
      zxingControls = controls;
    } else {
      throw new DOMException("Barcode detector unsupported", "NotSupportedError");
    }
    elements.cameraLoading.hidden = true;
    scannerActive = true;
    setScanFeedback("Inquadra un barcode", "", false);
    if (scannerDetector) scannerFrame = requestAnimationFrame(detectBarcodeFrame);
  } catch (error) {
    showCameraError(error);
  }
}

function openScanner() {
  scanSession.clear();
  barcodePresence.clear();
  scanLookups.clear();
  pendingScanUnits.clear();
  unknownScans.length = 0;
  elements.scanExpiryDate.value = "";
  setMessage(elements.scannerSaveError);
  renderScanSession();
  elements.scannerLive.hidden = false;
  elements.scannerSummary.hidden = true;
  elements.scannerModal.hidden = false;
  elements.authenticated.inert = true;
  document.body.classList.add("scanner-open");
  lastFocusedElement = document.activeElement;
  initializeScanAudio();
  startCamera();
}

function closeScanner() {
  if (elements.scannerModal.hidden) return;
  stopCamera();
  clearTimeout(feedbackTimer);
  elements.scannerModal.hidden = true;
  elements.authenticated.inert = false;
  document.body.classList.remove("scanner-open");
  lastFocusedElement?.focus();
}

function renderSummaryLocationButtons(selectedLocation) {
  return summaryStorageLocations.map(({ value, label, icon }) => `
    <button class="summary-location-button${selectedLocation === value ? " selected" : ""}" type="button"
      data-summary-location="${value}" aria-pressed="${selectedLocation === value}" aria-label="${label}">
      ${icon}<span>${label}</span>
    </button>`).join("");
}

function updateSummaryConfirmationState() {
  elements.confirmScanned.disabled = !sessionIsReadyToSave(scanSession);
}

function renderScannerSummary() {
  const items = [...scanSession.values()];
  elements.summaryEmpty.hidden = items.length !== 0;
  elements.summaryOptions.hidden = items.length === 0;
  elements.summaryList.innerHTML = items.map(({ product, quantity: itemQuantity, storageLocation }) => `
    <article class="summary-item${storageLocation ? "" : " location-missing"}" data-barcode="${escapeHtml(product.barcode)}">
      ${productImage(product)}
      <div>
        <h3 class="product-name">${escapeHtml(product.name || "Prodotto")}</h3>
        ${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}
        <button class="remove-summary-item" type="button" data-summary-action="remove">Rimuovi</button>
      </div>
      <div class="summary-controls" aria-label="Quantità di ${escapeHtml(product.name || "prodotto")}">
        <button type="button" data-summary-action="decrease" aria-label="Diminuisci quantità">−</button>
        <output aria-live="polite">${itemQuantity}</output>
        <button type="button" data-summary-action="increase" aria-label="Aumenta quantità">+</button>
      </div>
      <fieldset class="summary-location-field${storageLocation ? "" : " needs-selection"}" aria-invalid="${!storageLocation}">
        <legend>Destinazione <span>${storageLocation ? escapeHtml(locations[storageLocation]) : "Scegli una posizione"}</span></legend>
        <div class="summary-location-grid">${renderSummaryLocationButtons(storageLocation)}</div>
      </fieldset>
    </article>`).join("");
  updateSummaryConfirmationState();
}

function finishScanning() {
  stopCamera();
  setMessage(elements.scannerSaveError);
  elements.scannerLive.hidden = true;
  elements.scannerSummary.hidden = false;
  renderScannerSummary();
  elements.scannerModal.scrollTo({ top: 0, behavior: "smooth" });
}

function resumeScanning() {
  setMessage(elements.scannerSaveError);
  elements.scannerSummary.hidden = true;
  elements.scannerLive.hidden = false;
  renderScanSession();
  startCamera();
}

async function updateExistingInventoryItem(existing, scannedItem, storageLocation, expiryDate) {
  const payload = { quantity: existing.quantity + scannedItem.quantity, storage_location: storageLocation };
  if (expiryDate) payload.expiry_date = expiryDate;
  return api(`/api/v1/inventory/${existing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

async function saveScannedItem(scannedItem, inventoryByBarcode, expiryDate) {
  const barcode = scannedItem.product.barcode;
  const storageLocation = scannedItem.storageLocation;
  const existing = inventoryByBarcode.get(barcode);
  if (existing) return updateExistingInventoryItem(existing, scannedItem, storageLocation, expiryDate);
  try {
    return await api("/api/v1/inventory", {
      method: "POST",
      body: JSON.stringify({
        product_barcode: barcode,
        quantity: scannedItem.quantity,
        expiry_date: expiryDate || null,
        storage_location: storageLocation
      })
    });
  } catch (error) {
    if (error.status !== 409) throw error;
    const refreshed = await api("/api/v1/inventory");
    const concurrentItem = refreshed.find((item) => item.product_barcode === barcode);
    if (!concurrentItem) throw error;
    return updateExistingInventoryItem(concurrentItem, scannedItem, storageLocation, expiryDate);
  }
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(elements.loginError);
  const email = elements.loginForm.elements.email.value.trim();
  const password = elements.loginForm.elements.password.value;
  if (!email || !password) { setMessage(elements.loginError, "Inserisci email e password."); return; }
  setLoading(elements.loginButton, true);
  try {
    const response = await api("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    token = response.access_token;
    sessionStorage.setItem(TOKEN_KEY, token);
    elements.loginForm.reset();
    showApp();
  } catch (error) {
    setMessage(elements.loginError, userMessage(error, "login"));
  } finally { setLoading(elements.loginButton, false); }
});

$("#toggle-password").addEventListener("click", () => {
  const password = $("#password");
  const visible = password.type === "text";
  password.type = visible ? "password" : "text";
  $("#toggle-password").setAttribute("aria-label", visible ? "Mostra password" : "Nascondi password");
});

$("#logout-button").addEventListener("click", () => { clearSession(); showLogin(); });
$("#retry-inventory").addEventListener("click", loadInventory);
$$('.add-product-trigger').forEach((button) => button.addEventListener("click", () => showView("search")));
$$('.nav-item').forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
$("#open-scanner").addEventListener("click", openScanner);
$("#close-scanner").addEventListener("click", closeScanner);
$("#finish-scanning").addEventListener("click", finishScanning);
$("#resume-scanning").addEventListener("click", resumeScanning);
elements.scanAddOne.addEventListener("click", () => {
  if (!manualAddBarcode) return;
  const item = scanSession.get(manualAddBarcode);
  if (item) commitScannedUnit(manualAddBarcode, item.product, true);
});
$("#scanner-manual-search").addEventListener("click", () => {
  closeScanner();
  setTimeout(() => elements.searchInput.focus(), 50);
});

elements.summaryList.addEventListener("click", (event) => {
  const row = event.target.closest("[data-barcode]");
  if (!row) return;
  const item = scanSession.get(row.dataset.barcode);
  if (!item) return;
  const locationButton = event.target.closest("[data-summary-location]");
  if (locationButton) {
    if (!setSessionItemLocation(scanSession, row.dataset.barcode, locationButton.dataset.summaryLocation)) return;
    row.classList.remove("location-missing");
    const locationField = row.querySelector(".summary-location-field");
    locationField.classList.remove("needs-selection");
    locationField.setAttribute("aria-invalid", "false");
    locationField.querySelector("legend span").textContent = locations[item.storageLocation];
    row.querySelectorAll("[data-summary-location]").forEach((button) => {
      const selected = button.dataset.summaryLocation === item.storageLocation;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    setMessage(elements.scannerSaveError);
    updateSummaryConfirmationState();
    return;
  }
  const actionButton = event.target.closest("[data-summary-action]");
  if (!actionButton) return;
  const action = actionButton.dataset.summaryAction;
  if (action === "remove") scanSession.delete(row.dataset.barcode);
  if (action === "increase") item.quantity += 1;
  if (action === "decrease") item.quantity = Math.max(1, item.quantity - 1);
  renderScannerSummary();
});

elements.confirmScanned.addEventListener("click", async () => {
  const items = [...scanSession.entries()];
  if (!items.length) return;
  if (!sessionIsReadyToSave(scanSession)) {
    elements.summaryList.querySelectorAll(".summary-item").forEach((row) => {
      const item = scanSession.get(row.dataset.barcode);
      row.classList.toggle("location-missing", !item?.storageLocation);
      row.querySelector(".summary-location-field").classList.toggle("needs-selection", !item?.storageLocation);
    });
    setMessage(elements.scannerSaveError, "Scegli una destinazione per ogni prodotto.");
    return;
  }
  setMessage(elements.scannerSaveError);
  setLoading(elements.confirmScanned, true);
  const expiryDate = elements.scanExpiryDate.value || null;
  const failures = [];
  try {
    const inventory = await api("/api/v1/inventory");
    const inventoryByBarcode = new Map(inventory.map((item) => [item.product_barcode, item]));
    for (const [barcode, scannedItem] of items) {
      try {
        const saved = await saveScannedItem(scannedItem, inventoryByBarcode, expiryDate);
        inventoryByBarcode.set(barcode, saved);
        scanSession.delete(barcode);
      } catch (error) {
        if (error.status === 401) throw error;
        failures.push(scannedItem.product.name || barcode);
      }
    }
    if (!failures.length) {
      closeScanner();
      showView("inventory");
      showToast(`${items.length} ${items.length === 1 ? "prodotto aggiunto" : "prodotti aggiunti"} alla dispensa`);
    } else {
      renderScannerSummary();
      setMessage(elements.scannerSaveError, `Non è stato possibile aggiungere: ${failures.join(", ")}. Gli altri prodotti sono stati salvati.`);
    }
  } catch (error) {
    if (error.status !== 401) setMessage(elements.scannerSaveError, userMessage(error, "add"));
  } finally {
    setLoading(elements.confirmScanned, false);
  }
});

elements.searchInput.addEventListener("input", () => { elements.clearSearch.hidden = !elements.searchInput.value; });
elements.clearSearch.addEventListener("click", () => {
  elements.searchInput.value = "";
  elements.clearSearch.hidden = true;
  resetSearchStates(); elements.searchWelcome.hidden = false; elements.searchInput.focus();
});
elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = elements.searchInput.value.trim();
  if (query.length < 2) {
    resetSearchStates(); elements.searchError.hidden = false;
    elements.searchError.querySelector("p").textContent = "Scrivi almeno 2 caratteri per cercare.";
    elements.searchInput.focus(); return;
  }
  searchProducts(query);
});

$("#close-sheet").addEventListener("click", closeSheet);
elements.backdrop.addEventListener("click", closeSheet);
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!elements.scannerModal.hidden) closeScanner(); else closeSheet();
});
$("#quantity-minus").addEventListener("click", () => { quantity = Math.max(1, quantity - 1); elements.quantityValue.textContent = quantity; });
$("#quantity-plus").addEventListener("click", () => { quantity += 1; elements.quantityValue.textContent = quantity; });

elements.addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedProduct) return;
  setMessage(elements.addError);
  setLoading(elements.confirmAdd, true);
  try {
    await api("/api/v1/inventory", {
      method: "POST",
      body: JSON.stringify({
        product_barcode: selectedProduct.barcode,
        quantity,
        expiry_date: elements.expiryDate.value || null,
        storage_location: elements.addForm.elements.location.value
      })
    });
    closeSheet();
    showView("inventory");
    showToast("Prodotto aggiunto alla tua dispensa");
  } catch (error) {
    if (error.status !== 401) setMessage(elements.addError, userMessage(error, "add"));
  } finally { setLoading(elements.confirmAdd, false); }
});

async function bootstrap() {
  if (!token) { showLogin(); return; }
  try {
    await api("/api/v1/auth/me");
    showApp();
  } catch (error) {
    if (error.status !== 401) showLogin("Non riusciamo a verificare la sessione. Riprova.");
  }
}

bootstrap();
