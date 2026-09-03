def test_frontend_is_served_from_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "La tua dispensa" in response.text
    assert "Aggiungi prodotto" in response.text
    assert "Registrati" not in response.text


def test_frontend_assets_and_runtime_config_are_available(client):
    stylesheet = client.get("/assets/styles.css")
    script = client.get("/assets/app.js")
    scanner_state = client.get("/assets/scanner-state.mjs")
    i18n = client.get("/assets/i18n.mjs")
    zxing = client.get("/assets/vendor/zxing-browser-0.2.1.min.js")
    zxing_license = client.get("/assets/vendor/ZXING-LICENSE.txt")
    config = client.get("/app-config.js")
    logo = client.get("/assets/assets/fridivo-logo.png")

    assert stylesheet.status_code == 200
    assert "#3f6b57" in stylesheet.text.lower()
    assert script.status_code == 200
    assert scanner_state.status_code == 200
    assert i18n.status_code == 200
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


def test_official_logo_replaces_placeholders_without_distortion(client):
    html = client.get("/").text
    stylesheet = client.get("/assets/styles.css").text

    assert html.count('src="/assets/assets/fridivo-logo.png"') == 3
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
    assert "renderInventory(inventoryItems)" in script


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

    assert html.count('data-language="it"') == 2
    assert html.count('data-language="en"') == 2
    assert 'localStorage.getItem(LANGUAGE_KEY)' in script
    assert 'localStorage.setItem(LANGUAGE_KEY, language)' in script
    assert "applyStaticTranslations()" in script
    assert "refreshLocalizedView()" in script
    assert "window.location.reload" not in script


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
