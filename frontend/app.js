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
  quantityValue: $("#quantity-value"), expiryDate: $("#expiry-date"), toast: $("#toast")
};

let token = sessionStorage.getItem(TOKEN_KEY);
let selectedProduct = null;
let quantity = 1;
let toastTimer;
let lastFocusedElement;

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
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeSheet(); });
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
