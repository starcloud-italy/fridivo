import {
  BarcodePresenceTracker,
  addSessionUnit,
  sessionIsReadyToSave,
  setSessionItemExpiry,
  setSessionItemLocation
} from "./scanner-state.mjs";
import { resolveInitialLanguage, translate } from "./i18n.mjs";

const config = window.__FRIDIVO_CONFIG__ || {};
const API_BASE_URL = String(config.apiBaseUrl || "").replace(/\/$/, "");
const TOKEN_KEY = "fridivo_access_token";
const LANGUAGE_KEY = "fridivo_language";

function storedLanguage() {
  try { return localStorage.getItem(LANGUAGE_KEY); } catch { return null; }
}

let currentLanguage = resolveInitialLanguage(
  storedLanguage(),
  navigator.languages?.length ? navigator.languages : [navigator.language]
);
const t = (key, variables) => translate(currentLanguage, key, variables);
const locale = () => currentLanguage === "it" ? "it-IT" : "en";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const elements = {
  boot: $("#boot-screen"), login: $("#login-screen"), authenticated: $("#authenticated-app"),
  loginForm: $("#login-form"), loginButton: $("#login-button"), loginError: $("#login-error"),
  inventoryView: $("#inventory-view"), searchView: $("#search-view"), historyView: $("#history-view"), insightsView: $("#insights-view"), inventoryList: $("#inventory-list"),
  inventoryLoading: $("#inventory-loading"), inventoryEmpty: $("#inventory-empty"), inventoryError: $("#inventory-error"),
  inventoryCount: $("#inventory-count"), fab: $("#fab-add"), searchForm: $("#search-form"),
  historyList: $("#history-list"), historyLoading: $("#history-loading"), historyEmpty: $("#history-empty"), historyError: $("#history-error"),
  insightsContent: $("#insights-content"), insightsLoading: $("#insights-loading"), insightsEmpty: $("#insights-empty"), insightsError: $("#insights-error"),
  searchInput: $("#search-input"), clearSearch: $("#clear-search"), searchResults: $("#search-results"),
  searchLoading: $("#search-loading"), searchEmpty: $("#search-empty"), searchError: $("#search-error"), searchWelcome: $("#search-welcome"),
  backdrop: $("#sheet-backdrop"), sheet: $("#add-sheet"), selectedProduct: $("#selected-product"),
  addForm: $("#add-form"), addError: $("#add-error"), confirmAdd: $("#confirm-add"),
  quantityValue: $("#quantity-value"), expiryDate: $("#expiry-date"), toast: $("#toast"),
  inventorySheet: $("#inventory-sheet"), inventoryEditForm: $("#inventory-edit-form"),
  inventoryEditProduct: $("#inventory-edit-product"), inventoryEditQuantity: $("#inventory-edit-quantity"),
  inventoryEditLocation: $("#inventory-edit-location"), inventoryEditError: $("#inventory-edit-error"),
  saveInventoryEdit: $("#save-inventory-edit"), inventoryDeleteConfirm: $("#inventory-delete-confirm"),
  consumptionConfirm: $("#consumption-confirm"), consumptionConfirmText: $("#consumption-confirm-text"),
  consumptionQuantityField: $("#consumption-quantity-field"), consumptionQuantity: $("#consumption-quantity"),
  scannerModal: $("#scanner-modal"), scannerLive: $("#scanner-live"), scannerSummary: $("#scanner-summary"),
  scannerVideo: $("#scanner-video"), cameraLoading: $("#camera-loading"), cameraError: $("#camera-error"),
  cameraErrorMessage: $("#camera-error-message"), scanFeedback: $("#scan-feedback"), scanFeedbackText: $("#scan-feedback-text"),
  scanAddOne: $("#scan-add-one"), scanRecent: $("#scan-recent"),
  scanTotal: $("#scan-total"), summaryList: $("#summary-list"), summaryEmpty: $("#summary-empty"),
  scannerSaveError: $("#scanner-save-error"), confirmScanned: $("#confirm-scanned")
};

let token = sessionStorage.getItem(TOKEN_KEY);
let selectedProduct = null;
let quantity = 1;
let inventoryItems = [];
let inventoryLoaded = false;
let historyItems = [];
let historyLoaded = false;
let insightsData = null;
let insightsLoaded = false;
let searchResultItems = [];
let selectedInventoryItem = null;
let inventoryEditQuantity = 1;
let inventoryEditLocation = null;
let pendingConsumptionType = null;
let consumptionQuantity = 1;
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
    showLogin(t("error.sessionExpired"));
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
  closeInventorySheet();
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
  if (error.status === 0) return t("error.network");
  if (error.status === 401) return t(context === "login" ? "error.invalidCredentials" : "error.sessionExpired");
  if (error.status === 404) {
    if (context === "consumption") return t("error.inventoryItemMissing");
    return t(context === "add" ? "error.productUnavailable" : "error.productNotFound");
  }
  if (error.status === 409) return t(context === "consumption" ? "error.consumptionQuantity" : "error.duplicate");
  if (error.status === 422) return t(context === "search" ? "error.searchValidation" : "error.validation");
  return t("error.generic");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function productImage(product) {
  const name = escapeHtml(product.product_name || product.name || t("common.product"));
  if (!product.image_url) return '<div class="product-image image-fallback" aria-hidden="true">🥫</div>';
  return `<img class="product-image" src="${escapeHtml(product.image_url)}" alt="${name}" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=&quot;product-image image-fallback&quot; aria-hidden=&quot;true&quot;>🥫</div>'" />`;
}

const locationTranslationKeys = {
  fridge: "location.fridgeLong",
  freezer: "location.freezerLong",
  pantry: "location.pantry",
  other: "location.other"
};
const summaryStorageLocations = [
  { value: "fridge", key: "location.fridge", icon: '<svg viewBox="0 0 24 24"><rect x="6" y="3" width="12" height="18" rx="2"/><path d="M6 10h12M9 6v2M9 13v3"/></svg>' },
  { value: "freezer", key: "location.freezer", icon: '<svg viewBox="0 0 24 24"><path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9 5l3 2 3-2M9 19l3-2 3 2"/></svg>' },
  { value: "pantry", key: "location.pantry", icon: '<svg viewBox="0 0 24 24"><path d="M4 6h16v14H4zM4 11h16M8 8h3M8 14h3"/></svg>' },
  { value: "other", key: "location.other", icon: '<svg viewBox="0 0 24 24"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/></svg>' }
];

function locationLabel(value) {
  return t(locationTranslationKeys[value] || "location.other");
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLanguage;
  document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = t(element.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((element) => { element.innerHTML = t(element.dataset.i18nHtml); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { element.placeholder = t(element.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => { element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel)); });
  document.querySelectorAll("[data-i18n-content]").forEach((element) => { element.setAttribute("content", t(element.dataset.i18nContent)); });
  document.querySelectorAll("[data-language]").forEach((button) => {
    const selected = button.dataset.language === currentLanguage;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function expiryMeta(dateValue) {
  if (!dateValue) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const expiry = new Date(`${dateValue}T00:00:00`);
  const days = Math.round((expiry - today) / 86400000);
  const formatted = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short" }).format(expiry);
  if (days < 0) return `<span class="expiry expired">${escapeHtml(t("expiry.expired", { date: formatted }))}</span>`;
  if (days === 0) return `<span class="expiry soon">${escapeHtml(t("expiry.today"))}</span>`;
  if (days === 1) return `<span class="expiry soon">${escapeHtml(t("expiry.inOneDay"))}</span>`;
  if (days <= 7) return `<span class="expiry soon">${escapeHtml(t("expiry.inDays", { days }))}</span>`;
  return `<span class="expiry">${escapeHtml(t("expiry.on", { date: formatted }))}</span>`;
}

function renderInventory(items) {
  const sorted = [...items].sort((a, b) => {
    if (!a.expiry_date && !b.expiry_date) return 0;
    if (!a.expiry_date) return 1;
    if (!b.expiry_date) return -1;
    return a.expiry_date.localeCompare(b.expiry_date);
  });
  elements.inventoryCount.textContent = t(items.length === 1 ? "inventory.countOne" : "inventory.countMany", { count: items.length });
  elements.inventoryCount.hidden = items.length === 0;
  elements.inventoryEmpty.hidden = items.length !== 0;
  elements.inventoryList.innerHTML = sorted.map((item) => `
    <button class="product-card inventory-item" type="button" data-inventory-id="${escapeHtml(item.id)}" aria-label="${escapeHtml(t("inventory.editProduct", { name: item.product_name || t("common.product") }))}">
      ${productImage(item)}
      <div class="product-info">
        <h2 class="product-name">${escapeHtml(item.product_name || t("common.product"))}</h2>
        ${item.brands ? `<p class="product-brand">${escapeHtml(item.brands)}</p>` : ""}
        <div class="product-meta">
          <span class="quantity-pill">${item.quantity} ${escapeHtml(t(item.quantity === 1 ? "common.piece" : "common.pieces"))}</span>
          ${item.product_quantity ? `<span>${escapeHtml(item.product_quantity)}</span>` : ""}
          <span>${escapeHtml(locationLabel(item.storage_location))}</span>
          ${expiryMeta(item.expiry_date)}
        </div>
      </div>
      <span class="select-cue" aria-hidden="true">›</span>
    </button>`).join("");
}

async function loadInventory() {
  inventoryLoaded = false;
  elements.inventoryLoading.hidden = false;
  elements.inventoryError.hidden = true;
  elements.inventoryEmpty.hidden = true;
  elements.inventoryList.innerHTML = "";
  try {
    inventoryItems = await api("/api/v1/inventory");
    inventoryLoaded = true;
    renderInventory(inventoryItems);
  } catch (error) {
    if (error.status !== 401) elements.inventoryError.hidden = false;
  } finally {
    elements.inventoryLoading.hidden = true;
  }
}

const consumptionTypeKeys = {
  CONSUMED: "consumption.consumed",
  FINISHED: "consumption.finished",
  DISCARDED: "consumption.discarded"
};

function renderHistory(items) {
  elements.historyEmpty.hidden = items.length !== 0;
  elements.historyList.innerHTML = items.map((event) => {
    const eventDate = new Intl.DateTimeFormat(locale(), {
      day: "2-digit", month: "2-digit", year: "numeric"
    }).format(new Date(event.occurred_at));
    return `
      <article class="history-item">
        ${productImage(event)}
        <div>
          <h2 class="product-name">${escapeHtml(event.product_name || t("common.product"))}</h2>
          <p class="history-line"><span class="history-event-type">${escapeHtml(t(consumptionTypeKeys[event.event_type]))}</span> · ×${event.quantity} · ${escapeHtml(eventDate)}</p>
        </div>
      </article>`;
  }).join("");
}

async function loadHistory() {
  historyLoaded = false;
  elements.historyLoading.hidden = false;
  elements.historyError.hidden = true;
  elements.historyEmpty.hidden = true;
  elements.historyList.innerHTML = "";
  try {
    historyItems = await api("/api/v1/consumption-events?limit=50&offset=0");
    historyLoaded = true;
    renderHistory(historyItems);
  } catch (error) {
    if (error.status !== 401) elements.historyError.hidden = false;
  } finally {
    elements.historyLoading.hidden = true;
  }
}

function formatWasteRatio(value) {
  return new Intl.NumberFormat(locale(), { style: "percent", maximumFractionDigits: 0 }).format(value);
}

function insightEventCount(product) {
  return product.consumed_event_count + product.finished_event_count + product.discarded_event_count;
}

function insightProductCard(product, metric) {
  const amount = metric === "discarded" ? product.discarded_quantity : product.consumed_quantity;
  const amountKey = metric === "discarded" ? "insights.discardedQuantity" : "insights.usedQuantity";
  const ratio = metric === "discarded" && product.waste_ratio !== null
    ? `<span>${escapeHtml(t("insights.waste"))}: ${escapeHtml(formatWasteRatio(product.waste_ratio))}</span>`
    : "";
  return `<article class="insight-product">
    ${productImage(product)}
    <div class="insight-product-copy">
      <h3 class="product-name">${escapeHtml(product.product_name || t("common.product"))}</h3>
      ${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}
      <div class="insight-product-meta"><strong>${escapeHtml(t(amountKey, { count: amount }))}</strong>${ratio}</div>
    </div>
  </article>`;
}

function insightProductDetail(product) {
  const eventDate = new Intl.DateTimeFormat(locale(), {
    day: "2-digit", month: "2-digit", year: "numeric"
  }).format(new Date(product.last_event_at));
  const ratio = product.waste_ratio === null
    ? ""
    : `<span>${escapeHtml(t("insights.waste"))}: <strong>${escapeHtml(formatWasteRatio(product.waste_ratio))}</strong></span>`;
  return `<details class="insight-detail">
    <summary>${productImage(product)}<span><strong>${escapeHtml(product.product_name || t("common.product"))}</strong>${product.brands ? `<small>${escapeHtml(product.brands)}</small>` : ""}</span><span class="select-cue" aria-hidden="true">›</span></summary>
    <div class="insight-detail-metrics">
      <span>${escapeHtml(t("insights.consumed"))}: <strong>${product.consumed_quantity}</strong></span>
      <span>${escapeHtml(t("insights.discarded"))}: <strong>${product.discarded_quantity}</strong></span>
      <span>${escapeHtml(t("insights.events"))}: <strong>${insightEventCount(product)}</strong></span>
      ${ratio}
      <span class="insight-last-event">${escapeHtml(t("insights.lastEvent"))}: <strong>${escapeHtml(t(consumptionTypeKeys[product.last_event]))}</strong> · ${escapeHtml(eventDate)}</span>
    </div>
  </details>`;
}

function renderInsights(data) {
  const summary = data.summary;
  elements.insightsEmpty.hidden = summary.distinct_products !== 0;
  if (summary.distinct_products === 0) {
    elements.insightsContent.innerHTML = "";
    return;
  }
  const waste = summary.waste_ratio === null ? "" : `
    <div><span>${escapeHtml(t("insights.waste"))}</span><strong>${escapeHtml(formatWasteRatio(summary.waste_ratio))}</strong></div>`;
  const discarded = data.most_discarded.length
    ? data.most_discarded.map((product) => insightProductCard(product, "discarded")).join("")
    : `<p class="insight-none">${escapeHtml(t("insights.noDiscarded"))}</p>`;
  elements.insightsContent.innerHTML = `
    <section class="insight-summary" aria-label="${escapeHtml(t("insights.eyebrow"))}">
      <div><span>${escapeHtml(t("insights.consumed"))}</span><strong>${summary.consumed_quantity}</strong></div>
      <div><span>${escapeHtml(t("insights.discarded"))}</span><strong>${summary.discarded_quantity}</strong></div>
      <div><span>${escapeHtml(t("insights.productsTracked"))}</span><strong>${summary.distinct_products}</strong></div>
      ${waste}
    </section>
    <section class="insight-section"><h2>${escapeHtml(t("insights.mostConsumed"))}</h2><div class="insight-list">${data.most_consumed.map((product) => insightProductCard(product, "consumed")).join("")}</div></section>
    <section class="insight-section"><h2>${escapeHtml(t("insights.mostDiscarded"))}</h2><div class="insight-list">${discarded}</div></section>
    <section class="insight-section"><h2>${escapeHtml(t("insights.allProducts"))}</h2><div class="insight-details">${data.products.map(insightProductDetail).join("")}</div></section>`;
}

async function loadInsights() {
  insightsLoaded = false;
  elements.insightsLoading.hidden = false;
  elements.insightsError.hidden = true;
  elements.insightsEmpty.hidden = true;
  elements.insightsContent.innerHTML = "";
  try {
    insightsData = await api("/api/v1/insights/consumption");
    insightsLoaded = true;
    renderInsights(insightsData);
  } catch (error) {
    if (error.status !== 401) elements.insightsError.hidden = false;
  } finally {
    elements.insightsLoading.hidden = true;
  }
}

function showView(viewName) {
  const inventory = viewName === "inventory";
  const search = viewName === "search";
  const history = viewName === "history";
  const insights = viewName === "insights";
  elements.inventoryView.hidden = !inventory;
  elements.searchView.hidden = !search;
  elements.historyView.hidden = !history;
  elements.insightsView.hidden = !insights;
  elements.fab.hidden = !inventory;
  $$(".nav-item").forEach((item) => {
    const active = item.dataset.view === viewName;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page"); else item.removeAttribute("aria-current");
  });
  if (inventory) loadInventory();
  if (history) loadHistory();
  if (insights) loadInsights();
  if (search) setTimeout(() => elements.searchInput.focus(), 50);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetSearchStates() {
  elements.searchLoading.hidden = true;
  elements.searchEmpty.hidden = true;
  elements.searchError.hidden = true;
  elements.searchWelcome.hidden = true;
  searchResultItems = [];
  elements.searchResults.innerHTML = "";
}

function renderSearchResults(products) {
  elements.searchResults.innerHTML = products.map((product, index) => `
    <button class="product-card search-result" type="button" data-index="${index}">
      ${productImage(product)}
      <div class="product-info">
        <h2 class="product-name">${escapeHtml(product.name || t("common.product"))}</h2>
        ${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}
        ${product.quantity ? `<div class="product-meta"><span>${escapeHtml(product.quantity)}</span></div>` : ""}
      </div>
      <span class="select-cue" aria-hidden="true">›</span>
    </button>`).join("");
  $$(".search-result").forEach((button) => button.addEventListener("click", () => openSheet(products[Number(button.dataset.index)], button)));
}

async function searchProducts(query) {
  resetSearchStates();
  elements.searchLoading.hidden = false;
  try {
    const response = await api(`/api/v1/products/search?q=${encodeURIComponent(query)}`);
    searchResultItems = response.items || [];
    elements.searchEmpty.hidden = searchResultItems.length !== 0;
    renderSearchResults(searchResultItems);
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
  renderSelectedProduct();
  lastFocusedElement = trigger || document.activeElement;
  elements.backdrop.hidden = false;
  elements.sheet.hidden = false;
  document.body.classList.add("sheet-open");
  setTimeout(() => $("#quantity-minus").focus(), 50);
}

function renderSelectedProduct() {
  if (!selectedProduct) return;
  elements.selectedProduct.innerHTML = `${productImage(selectedProduct)}<div><h3 class="product-name">${escapeHtml(selectedProduct.name || t("common.product"))}</h3>${selectedProduct.brands ? `<p class="product-brand">${escapeHtml(selectedProduct.brands)}</p>` : ""}${selectedProduct.quantity ? `<div class="product-meta">${escapeHtml(selectedProduct.quantity)}</div>` : ""}</div>`;
}

function closeSheet() {
  if (elements.sheet.hidden) return;
  elements.sheet.hidden = true;
  elements.backdrop.hidden = true;
  document.body.classList.remove("sheet-open");
  selectedProduct = null;
  lastFocusedElement?.focus();
}

function formatInventoryDate(dateValue) {
  if (!dateValue) return t("expiry.none");
  const date = new Intl.DateTimeFormat(locale(), { day: "numeric", month: "long", year: "numeric" }).format(new Date(`${dateValue}T00:00:00`));
  return t("expiry.full", { date });
}

function renderInventoryEditLocation() {
  elements.inventoryEditLocation.innerHTML = renderSummaryLocationButtons(inventoryEditLocation, "inventory-location");
}

function openInventorySheet(item, trigger) {
  selectedInventoryItem = item;
  inventoryEditQuantity = item.quantity;
  inventoryEditLocation = item.storage_location;
  pendingConsumptionType = null;
  consumptionQuantity = 1;
  elements.inventoryEditQuantity.textContent = inventoryEditQuantity;
  renderInventoryEditProduct();
  renderInventoryEditLocation();
  setMessage(elements.inventoryEditError);
  elements.inventoryDeleteConfirm.hidden = true;
  renderConsumptionConfirmation();
  lastFocusedElement = trigger || document.activeElement;
  elements.backdrop.hidden = false;
  elements.inventorySheet.hidden = false;
  document.body.classList.add("sheet-open");
  setTimeout(() => $("#inventory-quantity-minus").focus(), 50);
}

function renderInventoryEditProduct() {
  if (!selectedInventoryItem) return;
  const item = selectedInventoryItem;
  elements.inventoryEditProduct.innerHTML = `${productImage(item)}<div><h3 class="product-name">${escapeHtml(item.product_name || t("common.product"))}</h3>${item.brands ? `<p class="product-brand">${escapeHtml(item.brands)}</p>` : ""}<p class="inventory-expiry">${escapeHtml(formatInventoryDate(item.expiry_date))}</p></div>`;
}

function renderConsumptionConfirmation() {
  $$('[data-consumption-type]').forEach((button) => {
    button.classList.toggle("selected", button.dataset.consumptionType === pendingConsumptionType);
  });
  if (!pendingConsumptionType || !selectedInventoryItem) {
    elements.consumptionConfirm.hidden = true;
    return;
  }
  const finished = pendingConsumptionType === "FINISHED";
  elements.consumptionConfirm.hidden = false;
  elements.consumptionQuantityField.hidden = finished;
  elements.consumptionQuantity.textContent = consumptionQuantity;
  elements.consumptionConfirmText.textContent = t(
    finished ? "consumption.finishedConfirm" : "consumption.quantityPrompt",
    { name: selectedInventoryItem.product_name || t("common.product") }
  );
}

function closeInventorySheet() {
  if (elements.inventorySheet.hidden) return;
  elements.inventorySheet.hidden = true;
  elements.backdrop.hidden = true;
  elements.inventoryDeleteConfirm.hidden = true;
  elements.consumptionConfirm.hidden = true;
  document.body.classList.remove("sheet-open");
  selectedInventoryItem = null;
  lastFocusedElement?.focus();
}

function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function refreshLocalizedView() {
  if (inventoryLoaded) renderInventory(inventoryItems);
  if (historyLoaded) renderHistory(historyItems);
  if (insightsLoaded) renderInsights(insightsData);
  if (searchResultItems.length) renderSearchResults(searchResultItems);
  renderSelectedProduct();
  renderInventoryEditProduct();
  if (selectedInventoryItem) renderInventoryEditLocation();
  renderConsumptionConfirmation();
  if (!elements.scannerModal.hidden) {
    renderScanSession();
    if (!elements.scannerSummary.hidden) renderScannerSummary();
  }
  const passwordVisible = $("#password").type === "text";
  $("#toggle-password").setAttribute("aria-label", t(passwordVisible ? "login.hidePassword" : "login.showPassword"));
}

function setLanguage(language, { persist = true } = {}) {
  if (!["it", "en"].includes(language)) return;
  currentLanguage = language;
  if (persist) {
    try { localStorage.setItem(LANGUAGE_KEY, language); } catch { /* Language still changes for this session. */ }
  }
  applyStaticTranslations();
  refreshLocalizedView();
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
    feedbackTimer = setTimeout(() => setScanFeedback(t("scanner.nextBarcode"), "", false), 1600);
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
    setScanFeedback(t("scanner.alreadyScanned", { name: product.name || t("common.product"), quantity: item.quantity }), "", false, barcode);
  } else {
    setScanFeedback(t("scanner.scanned", { name: product.name || t("common.product"), quantity: item.quantity }), "success");
  }
  return item;
}

function renderScanSession() {
  const items = [...scanSession.values()].sort((a, b) => b.lastScannedAt - a.lastScannedAt);
  const total = scannedUnitCount();
  elements.scanTotal.textContent = t(total === 1 ? "scanner.countOne" : "scanner.countMany", { count: total });
  const knownRows = items.slice(0, 4).map(({ product, quantity: itemQuantity }) => `
    <div class="scan-recent-item">
      ${productImage(product)}
      <div><p class="product-name">${escapeHtml(product.name || t("common.product"))}</p>${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}</div>
      <span class="scan-quantity">×${itemQuantity}</span>
    </div>`);
  elements.scanRecent.innerHTML = knownRows.length
    ? knownRows.join("")
    : `<p class="scan-empty">${escapeHtml(t("scanner.emptyRecent"))}</p>`;
}

function cameraErrorMessage(error) {
  if (!window.isSecureContext) return t("camera.https");
  if (!("BarcodeDetector" in window) && !window.ZXingBrowser?.BrowserMultiFormatReader) return t("camera.unsupported");
  if (!navigator.mediaDevices?.getUserMedia) return t("camera.noAccess");
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") return t("camera.denied");
  if (error?.name === "NotFoundError" || error?.name === "DevicesNotFoundError") return t("camera.notFound");
  if (error?.name === "NotReadableError" || error?.name === "TrackStartError") return t("camera.busy");
  return t("camera.generic");
}

function showCameraError(error) {
  stopCamera();
  elements.cameraLoading.hidden = true;
  elements.cameraErrorMessage.textContent = cameraErrorMessage(error);
  elements.cameraError.hidden = false;
  setScanFeedback(t("scanner.unavailable"), "warning", false);
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
      // Unknown or transient decoder reads are intentionally silent during continuous scanning.
    } else if (error.status !== 401) {
      setScanFeedback(t("scanner.lookupError"), "warning");
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
  setScanFeedback(t("scanner.alreadyScanned", { name: item.product.name || t("common.product"), quantity: item.quantity }), "", false, barcode);
}

function handleDetectionAttempt(rawValues, observedAt = Date.now(), completeFrame = true) {
  const events = barcodePresence.observe(rawValues, observedAt, { completeFrame });
  for (const barcode of events.exited) {
    if (manualAddBarcode === barcode) setScanFeedback(t("scanner.nextBarcode"), "", false);
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
  setScanFeedback(t("scanner.cameraStarting"), "", false);
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
    setScanFeedback(t("scanner.framePrompt"), "", false);
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

function renderSummaryLocationButtons(selectedLocation, dataAttribute = "summary-location") {
  return summaryStorageLocations.map(({ value, key, icon }) => {
    const label = t(key);
    return `
    <button class="summary-location-button${selectedLocation === value ? " selected" : ""}" type="button"
      data-${dataAttribute}="${value}" aria-pressed="${selectedLocation === value}" aria-label="${label}">
      ${icon}<span>${label}</span>
    </button>`;
  }).join("");
}

function updateSummaryConfirmationState() {
  elements.confirmScanned.disabled = !sessionIsReadyToSave(scanSession);
}

function renderScannerSummary() {
  const items = [...scanSession.values()];
  elements.summaryEmpty.hidden = items.length !== 0;
  elements.summaryList.innerHTML = items.map(({ product, quantity: itemQuantity, storageLocation, expiryDate }) => `
    <article class="summary-item${storageLocation ? "" : " location-missing"}" data-barcode="${escapeHtml(product.barcode)}">
      ${productImage(product)}
      <div>
        <h3 class="product-name">${escapeHtml(product.name || t("common.product"))}</h3>
        ${product.brands ? `<p class="product-brand">${escapeHtml(product.brands)}</p>` : ""}
        <button class="remove-summary-item" type="button" data-summary-action="remove">${escapeHtml(t("common.remove"))}</button>
      </div>
      <div class="summary-controls" aria-label="${escapeHtml(t("common.quantity"))}: ${escapeHtml(product.name || t("common.product"))}">
        <button type="button" data-summary-action="decrease" aria-label="${escapeHtml(t("common.decreaseQuantity"))}">−</button>
        <output aria-live="polite">${itemQuantity}</output>
        <button type="button" data-summary-action="increase" aria-label="${escapeHtml(t("common.increaseQuantity"))}">+</button>
      </div>
      <fieldset class="summary-location-field${storageLocation ? "" : " needs-selection"}" aria-invalid="${!storageLocation}">
        <legend>${escapeHtml(t("summary.destination"))} <span>${storageLocation ? escapeHtml(locationLabel(storageLocation)) : escapeHtml(t("summary.chooseLocation"))}</span></legend>
        <div class="summary-location-grid">${renderSummaryLocationButtons(storageLocation)}</div>
      </fieldset>
      <label class="summary-expiry-field">
        <span>${escapeHtml(t("summary.optionalExpiry"))}</span>
        <input type="date" data-summary-expiry value="${escapeHtml(expiryDate || "")}" />
      </label>
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

async function updateExistingInventoryItem(existing, scannedItem, storageLocation) {
  const payload = { quantity: existing.quantity + scannedItem.quantity, storage_location: storageLocation };
  if (scannedItem.expiryDate) payload.expiry_date = scannedItem.expiryDate;
  return api(`/api/v1/inventory/${existing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

async function saveScannedItem(scannedItem, inventoryByBarcode) {
  const barcode = scannedItem.product.barcode;
  const storageLocation = scannedItem.storageLocation;
  const existing = inventoryByBarcode.get(barcode);
  if (existing) return updateExistingInventoryItem(existing, scannedItem, storageLocation);
  try {
    return await api("/api/v1/inventory", {
      method: "POST",
      body: JSON.stringify({
        product_barcode: barcode,
        quantity: scannedItem.quantity,
        expiry_date: scannedItem.expiryDate || null,
        storage_location: storageLocation
      })
    });
  } catch (error) {
    if (error.status !== 409) throw error;
    const refreshed = await api("/api/v1/inventory");
    const concurrentItem = refreshed.find((item) => item.product_barcode === barcode);
    if (!concurrentItem) throw error;
    return updateExistingInventoryItem(concurrentItem, scannedItem, storageLocation);
  }
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(elements.loginError);
  const email = elements.loginForm.elements.email.value.trim();
  const password = elements.loginForm.elements.password.value;
  if (!email || !password) { setMessage(elements.loginError, t("validation.login")); return; }
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
  $("#toggle-password").setAttribute("aria-label", t(visible ? "login.showPassword" : "login.hidePassword"));
});

$("#logout-button").addEventListener("click", () => { clearSession(); showLogin(); });
$$('[data-language]').forEach((button) => button.addEventListener("click", () => setLanguage(button.dataset.language)));
$("#retry-inventory").addEventListener("click", loadInventory);
$("#retry-history").addEventListener("click", loadHistory);
$("#retry-insights").addEventListener("click", loadInsights);
elements.inventoryList.addEventListener("click", (event) => {
  const card = event.target.closest("[data-inventory-id]");
  if (!card) return;
  const item = inventoryItems.find((candidate) => String(candidate.id) === card.dataset.inventoryId);
  if (item) openInventorySheet(item, card);
});
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
    locationField.querySelector("legend span").textContent = locationLabel(item.storageLocation);
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

elements.summaryList.addEventListener("change", (event) => {
  const input = event.target.closest("[data-summary-expiry]");
  const row = event.target.closest("[data-barcode]");
  if (!input || !row) return;
  setSessionItemExpiry(scanSession, row.dataset.barcode, input.value);
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
    setMessage(elements.scannerSaveError, t("validation.locations"));
    return;
  }
  setMessage(elements.scannerSaveError);
  setLoading(elements.confirmScanned, true);
  const failures = [];
  try {
    const inventory = await api("/api/v1/inventory");
    const inventoryByBarcode = new Map(inventory.map((item) => [item.product_barcode, item]));
    for (const [barcode, scannedItem] of items) {
      try {
        const saved = await saveScannedItem(scannedItem, inventoryByBarcode);
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
      showToast(t(items.length === 1 ? "success.scannedOne" : "success.scannedMany", { count: items.length }));
    } else {
      renderScannerSummary();
      setMessage(elements.scannerSaveError, t("error.scanSavePartial", { names: failures.join(", ") }));
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
    elements.searchError.querySelector("p").textContent = t("validation.search");
    elements.searchInput.focus(); return;
  }
  searchProducts(query);
});

$("#close-sheet").addEventListener("click", closeSheet);
$("#close-inventory-sheet").addEventListener("click", closeInventorySheet);
elements.backdrop.addEventListener("click", () => {
  if (!elements.inventorySheet.hidden) closeInventorySheet(); else closeSheet();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!elements.scannerModal.hidden) closeScanner();
  else if (!elements.inventorySheet.hidden) closeInventorySheet();
  else closeSheet();
});
$("#quantity-minus").addEventListener("click", () => { quantity = Math.max(1, quantity - 1); elements.quantityValue.textContent = quantity; });
$("#quantity-plus").addEventListener("click", () => { quantity += 1; elements.quantityValue.textContent = quantity; });

$("#inventory-quantity-minus").addEventListener("click", () => {
  inventoryEditQuantity = Math.max(1, inventoryEditQuantity - 1);
  elements.inventoryEditQuantity.textContent = inventoryEditQuantity;
});
$("#inventory-quantity-plus").addEventListener("click", () => {
  inventoryEditQuantity += 1;
  elements.inventoryEditQuantity.textContent = inventoryEditQuantity;
});
$$('[data-consumption-type]').forEach((button) => button.addEventListener("click", () => {
  pendingConsumptionType = button.dataset.consumptionType;
  consumptionQuantity = 1;
  setMessage(elements.inventoryEditError);
  renderConsumptionConfirmation();
}));
$("#consumption-quantity-minus").addEventListener("click", () => {
  consumptionQuantity = Math.max(1, consumptionQuantity - 1);
  elements.consumptionQuantity.textContent = consumptionQuantity;
});
$("#consumption-quantity-plus").addEventListener("click", () => {
  if (!selectedInventoryItem) return;
  consumptionQuantity = Math.min(selectedInventoryItem.quantity, consumptionQuantity + 1);
  elements.consumptionQuantity.textContent = consumptionQuantity;
});
$("#cancel-consumption").addEventListener("click", () => {
  pendingConsumptionType = null;
  renderConsumptionConfirmation();
});
$("#confirm-consumption").addEventListener("click", async () => {
  if (!selectedInventoryItem || !pendingConsumptionType) return;
  const item = selectedInventoryItem;
  const eventType = pendingConsumptionType;
  const payload = { inventory_item_id: item.id, event_type: eventType };
  if (eventType !== "FINISHED") payload.quantity = consumptionQuantity;
  const button = $("#confirm-consumption");
  setMessage(elements.inventoryEditError);
  setLoading(button, true);
  try {
    const consumptionEvent = await api("/api/v1/consumption-events", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    const remaining = item.quantity - consumptionEvent.quantity;
    inventoryItems = remaining > 0
      ? inventoryItems.map((candidate) => candidate.id === item.id ? { ...candidate, quantity: remaining } : candidate)
      : inventoryItems.filter((candidate) => candidate.id !== item.id);
    historyLoaded = false;
    insightsLoaded = false;
    renderInventory(inventoryItems);
    closeInventorySheet();
    showToast(t(`success.${eventType.toLowerCase()}`));
  } catch (error) {
    if (error.status !== 401) setMessage(elements.inventoryEditError, userMessage(error, "consumption"));
  } finally {
    setLoading(button, false);
  }
});
elements.inventoryEditLocation.addEventListener("click", (event) => {
  const button = event.target.closest("[data-inventory-location]");
  if (!button) return;
  inventoryEditLocation = button.dataset.inventoryLocation;
  renderInventoryEditLocation();
});
elements.inventoryEditForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedInventoryItem) return;
  setMessage(elements.inventoryEditError);
  setLoading(elements.saveInventoryEdit, true);
  try {
    const updated = await api(`/api/v1/inventory/${selectedInventoryItem.id}`, {
      method: "PATCH",
      body: JSON.stringify({ quantity: inventoryEditQuantity, storage_location: inventoryEditLocation })
    });
    inventoryItems = inventoryItems.map((item) => item.id === updated.id ? updated : item);
    renderInventory(inventoryItems);
    closeInventorySheet();
    showToast(t("success.inventoryUpdated"));
  } catch (error) {
    if (error.status !== 401) setMessage(elements.inventoryEditError, userMessage(error, "inventory"));
  } finally {
    setLoading(elements.saveInventoryEdit, false);
  }
});
$("#remove-inventory-item").addEventListener("click", () => {
  elements.inventoryDeleteConfirm.hidden = false;
  $("#confirm-remove-inventory-item").focus();
});
$("#cancel-remove-inventory-item").addEventListener("click", () => {
  elements.inventoryDeleteConfirm.hidden = true;
});
$("#confirm-remove-inventory-item").addEventListener("click", async () => {
  if (!selectedInventoryItem) return;
  const itemId = selectedInventoryItem.id;
  const button = $("#confirm-remove-inventory-item");
  setMessage(elements.inventoryEditError);
  setLoading(button, true);
  try {
    await api(`/api/v1/inventory/${itemId}`, { method: "DELETE" });
    inventoryItems = inventoryItems.filter((item) => item.id !== itemId);
    renderInventory(inventoryItems);
    closeInventorySheet();
    showToast(t("success.inventoryRemoved"));
  } catch (error) {
    if (error.status !== 401) setMessage(elements.inventoryEditError, userMessage(error, "inventory"));
  } finally {
    setLoading(button, false);
  }
});

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
    showToast(t("success.productAdded"));
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
    if (error.status !== 401) showLogin(t("error.network"));
  }
}

applyStaticTranslations();
bootstrap();
