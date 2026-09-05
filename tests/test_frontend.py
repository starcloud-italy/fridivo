import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.main import FRONTEND_ASSET_VERSION, _frontend_asset_version


VERSIONED_ASSET_PREFIX = f"/assets/{FRONTEND_ASSET_VERSION}"


def test_frontend_is_served_from_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert "La tua dispensa" in response.text
    assert "Aggiungi prodotto" in response.text
    assert "Registrati" in response.text


def test_frontend_assets_and_runtime_config_are_available(client):
    stylesheet = client.get("/assets/styles.css")
    script = client.get("/assets/app.js")
    scanner_state = client.get("/assets/scanner-state.mjs")
    registration = client.get("/assets/registration.mjs")
    i18n = client.get("/assets/i18n.mjs")
    expiry = client.get("/assets/expiry.mjs")
    shopping_suggestions = client.get("/assets/shopping-suggestions.mjs")
    waste_watch = client.get("/assets/waste-watch.mjs")
    overview = client.get("/assets/overview.mjs")
    consumption_actions = client.get("/assets/consumption-actions.mjs")
    zxing = client.get("/assets/vendor/zxing-browser-0.2.1.min.js")
    zxing_license = client.get("/assets/vendor/ZXING-LICENSE.txt")
    config = client.get("/app-config.js")
    logo = client.get("/assets/assets/fridivo-logo.png")

    assert stylesheet.status_code == 200
    assert "#3f6b57" in stylesheet.text.lower()
    assert script.status_code == 200
    assert scanner_state.status_code == 200
    assert registration.status_code == 200
    assert i18n.status_code == 200
    assert expiry.status_code == 200
    assert shopping_suggestions.status_code == 200
    assert waste_watch.status_code == 200
    assert overview.status_code == 200
    assert consumption_actions.status_code == 200
    assert "TRANSLATIONS" in i18n.text
    assert "class BarcodePresenceTracker" in scanner_state.text
    assert '"/api/v1/auth/login"' in script.text
    assert '"/api/v1/inventory"' in script.text
    assert "/api/v1/products/search?q=" in script.text
    assert zxing.status_code == 200
    assert "ZXingBrowser" in zxing.text
    assert zxing_license.status_code == 200
    assert "MIT License" in zxing_license.text
    assert config.status_code == 200
    assert config.headers["cache-control"] == "no-store"
    assert '"apiBaseUrl": ""' in config.text
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"


def test_index_uses_one_release_namespace_for_all_static_assets(client):
    response = client.get("/")
    html = response.text

    assert f'href="{VERSIONED_ASSET_PREFIX}/styles.css"' in html
    assert f'src="{VERSIONED_ASSET_PREFIX}/app.js"' in html
    assert f'src="{VERSIONED_ASSET_PREFIX}/vendor/zxing-browser-0.2.1.min.js"' in html
    assert f'src="{VERSIONED_ASSET_PREFIX}/assets/fridivo-logo.png"' in html
    assert 'src="/app-config.js"' in html
    assert 'src="/assets/app.js"' not in html
    assert 'href="/assets/styles.css"' not in html
    asset_urls = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
    assert asset_urls
    assert all(url.startswith(f"{VERSIONED_ASSET_PREFIX}/") for url in asset_urls)


def test_versioned_entrypoint_modules_and_css_are_immutable(client):
    expected_cache_control = "public, max-age=31536000, immutable"

    stylesheet = client.get(f"{VERSIONED_ASSET_PREFIX}/styles.css")
    script = client.get(f"{VERSIONED_ASSET_PREFIX}/app.js")
    scanner_state = client.get(f"{VERSIONED_ASSET_PREFIX}/scanner-state.mjs")

    for response in (stylesheet, script, scanner_state):
        assert response.status_code == 200
        assert response.headers["cache-control"] == expected_cache_control
    assert 'from "./scanner-state.mjs"' in script.text
    assert "export function isAcceptableBarcode" in scanner_state.text
    module_paths = re.findall(r'from "\./([^\"]+\.mjs)"', script.text)
    assert "scanner-state.mjs" in module_paths
    for module_path in module_paths:
        module = client.get(f"{VERSIONED_ASSET_PREFIX}/{module_path}")
        assert module.status_code == 200
        assert module.headers["cache-control"] == expected_cache_control

    revalidated = client.get(
        f"{VERSIONED_ASSET_PREFIX}/app.js",
        headers={"If-None-Match": script.headers["etag"]},
    )
    assert revalidated.status_code == 304
    assert revalidated.headers["cache-control"] == expected_cache_control


def test_frontend_asset_version_changes_with_asset_content():
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        asset_dir = Path(directory)
        asset = asset_dir / "app.js"
        asset.write_text("export const release = 1;", encoding="utf-8")
        first_version = _frontend_asset_version(asset_dir)

        asset.write_text("export const release = 2;", encoding="utf-8")
        second_version = _frontend_asset_version(asset_dir)

    assert first_version != second_version
    assert len(first_version) == len(second_version) == 16


def test_legacy_assets_revalidate_and_wrong_release_paths_do_not_fall_back(client):
    for path in ("app.js", "scanner-state.mjs", "styles.css"):
        response = client.get(f"/assets/{path}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"

    assert client.get("/assets/not-the-current-release/app.js").status_code == 404


def test_runtime_config_remains_unversioned_and_never_cached(client):
    index = client.get("/").text
    config = client.get("/app-config.js")

    assert 'src="/app-config.js"' in index
    assert config.status_code == 200
    assert config.headers["cache-control"] == "no-store"


def test_official_logo_replaces_placeholders_without_distortion(client):
    html = client.get("/").text
    stylesheet = client.get("/assets/styles.css").text

    assert html.count(f'src="{VERSIONED_ASSET_PREFIX}/assets/fridivo-logo.png"') == 4
    assert 'class="boot-logo"' in html
    assert 'class="login-logo"' in html
    assert 'class="header-logo"' in html
    assert "brand-mark" not in html
    assert "wordmark-dot" not in html
    assert ".login-logo" in stylesheet
    assert ".header-logo" in stylesheet
    assert "height: auto" in stylesheet
    assert "object-fit: contain" in stylesheet


def test_frontend_does_not_render_backend_identifiers(client):
    html = client.get("/").text

    for technical_label in ("household_id", "inventory_items", "product_barcode", "JWT"):
        assert technical_label not in html


def test_frontend_contains_accessible_mobile_controls(client):
    html = client.get("/").text
    stylesheet = client.get("/assets/styles.css").text

    assert 'name="viewport"' in html
    assert 'aria-label="Navigazione principale"' in html
    assert 'aria-modal="true"' in html
    assert "font-size: 16px" in stylesheet
    assert "min-height: 44px" in stylesheet


def test_add_view_keeps_manual_search_and_exposes_multi_barcode_scanner(client):
    html = client.get("/").text

    assert 'id="open-scanner"' in html
    assert "Scansiona barcode" in html
    assert "Fotocamera continua per più prodotti" in html
    assert 'id="search-form"' in html
    assert 'id="search-input"' in html
    assert "oppure cerca manualmente" in html


def test_add_view_exposes_a_localized_collapsible_manual_barcode_lookup(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    translations = client.get("/assets/i18n.mjs").text

    assert 'id="manual-barcode-disclosure"' in html
    assert 'data-i18n="barcode.enter"' in html
    assert 'id="manual-barcode-form"' in html
    assert 'type="text" inputmode="numeric"' in html
    assert 'pattern="[0-9]{8,14}"' in html
    assert 'data-i18n="barcode.label"' in html
    assert 'data-i18n="barcode.find"' in html
    assert "normalizeBarcode(elements.manualBarcodeInput.value)" in script
    assert "isAcceptableBarcode(barcode)" in script
    assert "const product = await lookupBarcodeProduct(barcode)" in script
    assert 'userMessage(error, "barcode")' in script
    for key in ("barcode.enter", "barcode.label", "barcode.find", "barcode.validation"):
        assert translations.count(f'"{key}"') == 2


def test_scanner_has_camera_errors_continuous_session_and_finish_controls(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="scanner-video"' in html
    assert 'playsinline' in html
    assert 'id="camera-error"' in html
    assert "Usa la ricerca manuale" in html
    assert "Termina scansione" in html
    assert "Ultimi prodotti" in html
    assert "navigator.mediaDevices.getUserMedia" in script
    assert "requestAnimationFrame(detectBarcodeFrame)" in script
    assert "NotAllowedError" in script
    assert "NotFoundError" in script
    assert '"BarcodeDetector" in window' in script
    assert "ZXingBrowser?.BrowserMultiFormatReader" in script
    assert "decodeFromConstraints" in script


def test_scanner_uses_per_barcode_presence_instead_of_time_cooldown(client):
    script = client.get("/assets/app.js").text
    scanner_state = client.get("/assets/scanner-state.mjs").text

    assert "const scanSession = new Map()" in script
    assert "new BarcodePresenceTracker()" in script
    assert "barcodePresence.observe(rawValues, observedAt, { completeFrame })" in script
    assert "BARCODE_COOLDOWN_MS" not in script
    assert "BARCODE_EXIT_GRACE_MS = 700" in scanner_state
    assert "BARCODE_EXIT_MISSES = 3" in scanner_state
    assert "state.missedAttempts >= this.requiredMisses" in scanner_state
    assert "observedAt - state.lastSeenAt >= this.graceMs" in scanner_state
    assert "/api/v1/products/barcode/${encodeURIComponent(barcode)}" in script
    assert "addSessionUnit(scanSession, barcode, product" in script
    assert "navigator.vibrate(70)" in script


def test_unknown_scanner_reads_are_silent_and_never_join_the_session(client):
    script = client.get("/assets/app.js").text

    assert "Prodotto non riconosciuto" not in script
    assert "unknownScans" not in script
    assert "if (error.status === 404)" in script
    assert "Unknown or transient decoder reads are intentionally silent" in script
    assert "for (let unit = 0; unit < units; unit += 1) commitScannedUnit(barcode, product)" in script
    assert "provideUnitFeedback" in script


def test_scanner_has_manual_increment_and_optional_local_audio_feedback(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="scan-add-one"' in html
    assert ">+1</button>" in html
    assert "window.AudioContext || window.webkitAudioContext" in script
    assert "initializeScanAudio();" in script
    assert 'oscillator.type = "sine"' in script
    assert "oscillator.frequency.setValueAtTime(880" in script
    assert "playScanBeep();" in script
    assert "Audio is optional" in script
    assert "commitScannedUnit(manualAddBarcode, item.product, true)" in script


def test_scanner_summary_is_editable_and_only_saves_after_confirmation(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="scanner-summary"' in html
    assert 'data-summary-action="decrease"' in script
    assert 'data-summary-action="increase"' in script
    assert 'data-summary-action="remove"' in script
    assert "Continua a scansionare" in html
    assert 'id="confirm-scanned"' in html
    assert "Aggiungi alla dispensa" in html
    assert 'name="scan-location"' not in html
    assert "data-summary-location" in script
    for location in ("fridge", "freezer", "pantry", "other"):
        assert f'value: "{location}"' in script
    assert "setSessionItemLocation(scanSession" in script
    assert "elements.confirmScanned.disabled = !sessionIsReadyToSave(scanSession)" in script
    assert 'data-summary-expiry' in script
    assert 'id="scan-expiry-date"' not in html
    assert "setSessionItemExpiry(scanSession" in script
    assert 'method: "POST"' in script
    assert 'method: "PATCH"' in script
    assert "existing.quantity + scannedItem.quantity" in script
    assert "const storageLocation = scannedItem.storageLocation" in script
    assert "storage_location: storageLocation" in script


def test_scanner_layout_is_mobile_first(client):
    stylesheet = client.get("/assets/styles.css").text

    assert ".scanner-modal { position: fixed" in stylesheet
    assert "env(safe-area-inset-bottom)" in stylesheet
    assert ".camera-frame" in stylesheet
    assert "aspect-ratio: 4 / 3" in stylesheet
    assert "@media (max-width: 370px)" in stylesheet


def test_inventory_cards_open_the_manual_management_sheet(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="inventory-sheet"' in html
    assert 'id="inventory-edit-product"' in html
    assert 'id="inventory-edit-quantity"' in html
    assert 'id="inventory-edit-location"' in html
    assert 'data-inventory-id="${escapeHtml(item.id)}"' in script
    assert "openInventorySheet(item, card)" in script
    assert "item.expiry_date" in script


def test_inventory_management_patches_quantity_and_location_and_updates_ui(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="inventory-quantity-minus"' in html
    assert 'id="inventory-quantity-plus"' in html
    assert 'id="save-inventory-edit"' in html
    assert 'data-inventory-location' in script
    assert 'method: "PATCH"' in script
    assert "quantity: inventoryEditQuantity" in script
    assert "storage_location: inventoryEditLocation" in script
    assert "inventoryItems = inventoryItems.map" in script
    assert "renderInventoryWithPriorities()" in script


def test_inventory_manual_removal_requires_confirmation_and_updates_ui(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert 'id="remove-inventory-item"' in html
    assert 'id="inventory-delete-confirm"' in html
    assert 'id="cancel-remove-inventory-item"' in html
    assert 'id="confirm-remove-inventory-item"' in html
    assert 'method: "DELETE"' in script
    assert "inventoryItems = inventoryItems.filter" in script
    assert 't("success.inventoryRemoved")' in script


def test_inventory_management_reuses_mobile_scanner_location_controls(client):
    html = client.get("/").text
    stylesheet = client.get("/assets/styles.css").text
    script = client.get("/assets/app.js").text

    assert 'class="summary-location-field inventory-location-field"' in html
    assert 'class="summary-location-grid"' in html
    assert 'renderSummaryLocationButtons(inventoryEditLocation, "inventory-location")' in script
    assert ".summary-location-button" in stylesheet
    assert "min-height: 52px" in stylesheet


def test_frontend_supports_italian_and_english_with_browser_detection(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    i18n = client.get("/assets/i18n.mjs").text

    assert 'html lang="it"' in html
    assert 'it: {' in i18n
    assert 'en: {' in i18n
    assert 'startsWith("it") ? "it" : "en"' in i18n
    assert "navigator.languages" in script
    assert 'document.documentElement.lang = currentLanguage' in script


def test_language_switch_is_manual_persistent_and_does_not_reload(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert html.count('data-language="it"') == 3
    assert html.count('data-language="en"') == 3
    assert 'localStorage.getItem(LANGUAGE_KEY)' in script
    assert 'localStorage.setItem(LANGUAGE_KEY, language)' in script
    assert "applyStaticTranslations()" in script
    assert "refreshLocalizedView()" in script
    assert "window.location.reload" not in script


def test_registration_ui_validates_submits_and_reuses_the_existing_session(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    registration = client.get("/assets/registration.mjs").text
    i18n = client.get("/assets/i18n.mjs").text
    stylesheet = client.get("/assets/styles.css").text

    for fragment in (
        'id="show-register"',
        'id="register-screen"',
        'id="register-form"',
        'name="first_name"',
        'name="email" type="email"',
        'name="password" type="password" minlength="8" maxlength="128"',
        'name="confirm_password" type="password" minlength="8" maxlength="128"',
        'id="register-duplicate-error"',
        'id="duplicate-sign-in"',
        'id="show-login"',
    ):
        assert fragment in html

    assert 'api("/api/v1/auth/register"' in script
    assert "registrationValidationKey(values)" in script
    assert "registrationPayload(values, currentLanguage)" in script
    assert "if (elements.registerButton.disabled) return" in script
    assert "setLoading(elements.registerButton, true)" in script
    assert "setLoading(elements.registerButton, false)" in script
    assert "error.status === 409" in script
    assert "response.access_token" in script
    assert "sessionStorage.setItem(TOKEN_KEY, token)" in script
    assert "elements.registerForm.reset()" in script
    assert "showApp()" in script
    assert 'confirm_password" in registrationPayload' not in registration
    assert "confirm_password" not in registration
    assert 'language_code: languageCode' in registration
    assert "REGISTRATION_PASSWORD_MIN_LENGTH = 8" in registration
    assert "REGISTRATION_PASSWORD_MAX_LENGTH = 128" in registration
    assert ".auth-mode-button" in stylesheet
    assert "min-height: 44px" in stylesheet

    for key in (
        "login.noAccount",
        "login.signUp",
        "register.title",
        "register.name",
        "register.confirmPassword",
        "register.submit",
        "register.haveAccount",
        "register.signIn",
        "register.duplicateEmail",
        "register.validationName",
        "register.validationEmail",
        "register.validationPasswordLength",
        "register.validationPasswordMismatch",
        "register.error",
    ):
        assert i18n.count(f'"{key}"') == 2


def test_static_dynamic_scanner_and_inventory_texts_are_localized(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    i18n = client.get("/assets/i18n.mjs").text

    for marker in (
        'data-i18n="login.welcome"',
        'data-i18n="inventory.manageTitle"',
        'data-i18n="scanner.title"',
        'data-i18n="scanner.summaryIntro"',
        'data-i18n-aria-label="scanner.videoLabel"',
        'data-i18n-placeholder="search.placeholder"',
    ):
        assert marker in html
    for key in (
        "location.fridge",
        "location.freezer",
        "location.pantry",
        "location.other",
        "camera.denied",
        "error.sessionExpired",
        "success.inventoryUpdated",
        "inventory.removeConfirm",
    ):
        assert f'"{key}"' in i18n
    assert 'new Intl.DateTimeFormat(locale()' in script
    assert 't("validation.locations")' in script


def test_consumption_and_history_ui_use_existing_i18n_and_api(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    i18n = client.get("/assets/i18n.mjs").text

    assert 'data-view="history"' in html
    assert 'id="history-view"' in html
    assert 'data-consumption-type="CONSUMED"' in html
    assert 'data-consumption-type="FINISHED"' in html
    assert 'data-consumption-type="DISCARDED"' in html
    assert 'api("/api/v1/consumption-events"' in script
    assert 'api("/api/v1/consumption-events?limit=50&offset=0")' in script
    assert 'method: "DELETE"' in script
    for key in (
        "consumption.consumed",
        "consumption.finished",
        "consumption.discarded",
        "history.title",
        "history.emptyTitle",
        "summary.optionalExpiry",
    ):
        assert f'"{key}"' in i18n


def test_insights_ui_has_all_states_navigation_dynamic_data_and_i18n(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    styles = client.get("/assets/styles.css").text
    i18n = client.get("/assets/i18n.mjs").text

    assert 'data-view="insights"' in html
    assert 'id="insights-view"' in html
    assert 'id="insights-loading"' in html
    assert 'id="insights-empty"' in html
    assert 'id="insights-error"' in html
    assert 'id="insights-content"' in html
    assert 'api("/api/v1/insights/consumption")' in script
    assert "summary.consumed_quantity" in script
    assert "summary.discarded_quantity" in script
    assert "data.most_consumed" in script
    assert "data.most_discarded" in script
    assert "data.products.map(insightProductDetail)" in script
    assert '$("#retry-insights").addEventListener("click", loadInsights)' in script
    assert "grid-template-columns: repeat(5, minmax(0,1fr))" in styles
    assert "min-width: 0" in styles
    for key in (
        "nav.insights",
        "insights.eyebrow",
        "insights.title",
        "insights.loading",
        "insights.empty",
        "insights.errorTitle",
        "insights.consumed",
        "insights.discarded",
        "insights.productsTracked",
        "insights.waste",
        "insights.mostConsumed",
        "insights.mostDiscarded",
        "insights.lastEvent",
    ):
        assert i18n.count(f'"{key}"') == 2


def test_shopping_ui_supports_quick_add_all_states_actions_and_i18n(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    styles = client.get("/assets/styles.css").text
    i18n = client.get("/assets/i18n.mjs").text

    for fragment in (
        'data-view="shopping"',
        'id="shopping-view"',
        'id="shopping-quick-form"',
        'id="shopping-name"',
        'id="shopping-quantity"',
        'id="shopping-note"',
        'id="shopping-loading"',
        'id="shopping-empty"',
        'id="shopping-error"',
        'id="shopping-active-list"',
        'data-i18n="shopping.checkHint"',
        'id="shopping-completed-section"',
        'id="shopping-sheet"',
        'id="shopping-delete-confirm"',
    ):
        assert fragment in html
    assert 'api("/api/v1/shopping-list")' in script
    assert 'method: "POST"' in script
    assert 'method: "PATCH"' in script
    assert 'method: "DELETE"' in script
    assert "data-shopping-status" in script
    assert 'role="checkbox"' in script
    assert 'aria-checked="${item.is_completed ? "true" : "false"}"' in script
    assert 'class="shopping-checkbox-mark"' in script
    assert 'title="${escapeHtml(actionLabel)}"' in script
    assert 'item.is_completed ? "shopping.restoreItem" : "shopping.markPurchased"' in script
    assert "data-shopping-edit" in script
    assert "shoppingItems = [saved" in script
    assert "min-height: 46px" in styles
    for key in (
        "nav.shopping",
        "shopping.title",
        "shopping.toBuy",
        "shopping.checkHint",
        "shopping.purchased",
        "shopping.add",
        "shopping.edit",
        "shopping.delete",
        "shopping.restore",
        "shopping.markPurchased",
        "shopping.restoreItem",
        "shopping.name",
        "shopping.note",
        "shopping.emptyTitle",
        "shopping.loading",
        "shopping.errorTitle",
        "shopping.deleteConfirm",
        "shopping.completed",
        "shopping.restored",
    ):
        assert i18n.count(f'"{key}"') == 2


def test_scanner_uses_individual_optional_expiry_dates(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text

    assert "Scadenza comune" not in html
    assert "Shared expiry date" not in client.get("/assets/i18n.mjs").text
    assert 'data-summary-expiry' in script
    assert "scannedItem.expiryDate || null" in script
    assert "if (scannedItem.expiryDate) payload.expiry_date = scannedItem.expiryDate" in script
    assert "elements.confirmScanned.disabled = !sessionIsReadyToSave(scanSession)" in script


def test_consume_first_ui_is_plan_aware_localized_and_semantically_separates_expired(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    translations = client.get("/assets/i18n.mjs").text

    assert 'id="consume-first-section"' in html
    assert 'id="expired-priority-group"' in html
    assert 'id="consume-priority-group"' in html
    assert 'class="priority-group expired-priority"' in html
    assert 'planAllowsConsumeFirst(householdPlan)' in script
    assert 'api("/api/v1/households/current")' in script
    assert 'api("/api/v1/inventory/consume-first")' in script
    assert "items.slice(0, 5)" in script
    assert 'item.expiry_status === "EXPIRED"' in client.get("/assets/expiry.mjs").text
    for key in (
        "consumeFirst.attentionEyebrow",
        "consumeFirst.expiredTitle",
        "consumeFirst.expiredNote",
        "consumeFirst.eyebrow",
        "consumeFirst.title",
        "consumeFirst.empty",
        "consumeFirst.error",
    ):
        assert translations.count(f'"{key}"') == 2


def test_inventory_rendering_excludes_only_displayed_plus_priorities(client):
    script = client.get("/assets/app.js").text
    expiry = client.get("/assets/expiry.mjs").text

    assert "visibleInventoryItems(householdPlan, inventoryItems, consumeFirstItems)" in script
    assert "consumeFirstItems.slice(0, 5)" in expiry
    assert "!planAllowsConsumeFirst(plan)" in expiry
    assert "displayedPriorityIds.has(String(item.id))" in expiry
    assert "if (inventoryLoaded) renderInventoryWithPriorities()" in script


def test_consume_first_cards_reuse_the_existing_consumption_flow(client):
    script = client.get("/assets/app.js").text
    actions = client.get("/assets/consumption-actions.mjs").text
    translations = client.get("/assets/i18n.mjs").text

    assert 'data-priority-consumption="${action.type}"' in script
    assert 'data-priority-item-id="${escapeHtml(item.id)}"' in script
    assert "CONSUMPTION_ACTIONS.map" in script
    assert "openInventorySheet(item, action, action.dataset.priorityConsumption)" in script
    assert "consumptionEventPayload(item.id, eventType, consumptionQuantity)" in script
    assert "inventoryAfterConsumption(" in script
    assert 'api("/api/v1/consumption-events", {' in script
    assert "await loadConsumeFirst()" in script
    assert actions.count('type: "CONSUMED"') == 1
    assert actions.count('type: "FINISHED"') == 1
    assert actions.count('type: "DISCARDED"') == 1
    for key in (
        "consumption.consumed",
        "consumption.finished",
        "consumption.discarded",
    ):
        assert translations.count(f'"{key}"') == 2


@pytest.mark.parametrize("viewport_width", (375, 390, 430))
def test_consume_first_mobile_layout_uses_shrinkable_columns_without_overflow(
    client, viewport_width
):
    html = client.get("/").text
    styles = client.get("/assets/styles.css").text

    assert 'name="viewport"' in html
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' in html
    assert viewport_width >= 375
    assert ".priority-section { display: grid;" in styles
    assert ".priority-card { display: grid; grid-template-columns: 52px minmax(0,1fr);" in styles
    assert ".priority-heading h2 { margin: 0; overflow-wrap: anywhere;" in styles
    assert ".priority-list { display: grid; gap: 8px; min-width: 0; }" in styles
    assert ".priority-actions { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(3, minmax(0,1fr));" in styles
    assert ".priority-action { display: inline-flex;" in styles
    assert "min-height: 44px;" in styles


def test_shopping_suggestions_are_plus_only_and_use_existing_shopping_api(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    translations = client.get("/assets/i18n.mjs").text
    suggestion_helpers = client.get("/assets/shopping-suggestions.mjs").text

    assert 'id="shopping-suggestions-section"' in html
    assert 'id="shopping-suggestions-list"' in html
    assert 'api("/api/v1/shopping-list/suggestions")' in script
    assert 'api("/api/v1/shopping-list", {' in script
    assert 'data-shopping-suggestion="${escapeHtml(item.product_barcode)}"' in script
    assert "removeShoppingSuggestion(" in script
    assert 'plan === "PLUS" ? suggestions.slice(0, 5) : []' in suggestion_helpers
    for key in (
        "shoppingSuggestions.eyebrow",
        "shoppingSuggestions.title",
        "shoppingSuggestions.add",
        "shoppingSuggestions.added",
        "shoppingSuggestions.error",
    ):
        assert translations.count(f'"{key}"') == 2


@pytest.mark.parametrize("viewport_width", (375, 390, 430))
def test_shopping_suggestions_mobile_layout_has_no_fixed_width_overflow(
    client, viewport_width
):
    styles = client.get("/assets/styles.css").text

    assert viewport_width >= 375
    assert ".shopping-suggestions { min-width: 0;" in styles
    assert ".shopping-suggestions-list { display: grid; gap: 8px; min-width: 0; }" in styles
    assert "grid-template-columns: 48px minmax(0,1fr);" in styles
    assert ".shopping-suggestion-add { grid-column: 1 / -1;" in styles
    assert "width: 100%;" in styles


def test_waste_watch_ui_is_plus_only_cautious_localized_and_has_no_empty_panel(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    translations = client.get("/assets/i18n.mjs").text
    helper = client.get("/assets/waste-watch.mjs").text

    assert 'id="waste-watch-section"' in html
    assert 'id="waste-watch-list"' in html
    assert 'api("/api/v1/insights/waste-watch")' in script
    assert "visible.length === 0" in script
    assert 'plan === "PLUS" ? items.slice(0, 5) : []' in helper
    assert "item.discarded_event_count === 1" in script
    assert "item.discarded_quantity === 1" in script
    assert 't("wasteWatch.suggestion")' in script
    for key in (
        "wasteWatch.eyebrow",
        "wasteWatch.title",
        "wasteWatch.discardedOne",
        "wasteWatch.discardedMany",
        "wasteWatch.quantityOne",
        "wasteWatch.quantityMany",
        "wasteWatch.suggestion",
    ):
        assert translations.count(f'"{key}"') == 2


@pytest.mark.parametrize("viewport_width", (375, 390, 430))
def test_waste_watch_mobile_layout_uses_shrinkable_columns_without_overflow(
    client, viewport_width
):
    styles = client.get("/assets/styles.css").text

    assert viewport_width >= 375
    assert ".waste-watch { min-width: 0;" in styles
    assert ".waste-watch-list { display: grid; gap: 8px; min-width: 0; }" in styles
    assert ".waste-watch-item { display: grid; grid-template-columns: 52px minmax(0,1fr);" in styles
    assert "overflow-wrap: anywhere; font-size: 12px;" in styles


def test_overview_ui_is_plus_only_localized_and_handles_null_ratio(client):
    html = client.get("/").text
    script = client.get("/assets/app.js").text
    translations = client.get("/assets/i18n.mjs").text
    helper = client.get("/assets/overview.mjs").text

    assert 'id="overview-section"' in html
    assert 'id="overview-period"' in html
    assert 'id="overview-metrics"' in html
    assert 'api("/api/v1/insights/overview")' in script
    assert 'householdPlan !== "PLUS"' in script
    assert 'overview.waste_ratio === null ? ""' in script
    assert 'visibleOverview(plan, overview)' in helper
    for key in (
        "overview.title",
        "overview.period",
        "overview.usedOne",
        "overview.usedMany",
        "overview.discardedOne",
        "overview.discardedMany",
        "overview.wasteRatio",
        "overview.repeatedWasteOne",
        "overview.repeatedWasteMany",
        "overview.repurchaseOne",
        "overview.repurchaseMany",
        "overview.expiryOne",
        "overview.expiryMany",
    ):
        assert translations.count(f'"{key}"') == 2
    assert "Il tuo andamento" in translations
    assert "Your overview" in translations
    assert "Ultimi {count} giorni" in translations
    assert "Last {count} days" in translations


@pytest.mark.parametrize("width", [375, 390, 430])
def test_overview_mobile_layout_is_compact_and_avoids_overflow(client, width):
    styles = client.get("/assets/styles.css").text

    assert width >= 375
    assert ".overview { min-width: 0;" in styles
    assert ".overview-metrics { display: grid; grid-template-columns: repeat(2, minmax(0,1fr));" in styles
    assert ".overview-metric { display: grid;" in styles
    assert ".overview-metric span { overflow-wrap: anywhere;" in styles
    assert ".waste-watch { min-width: 0;" in styles
