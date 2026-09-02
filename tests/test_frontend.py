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
    zxing = client.get("/assets/vendor/zxing-browser-0.2.1.min.js")
    zxing_license = client.get("/assets/vendor/ZXING-LICENSE.txt")
    config = client.get("/app-config.js")

    assert stylesheet.status_code == 200
    assert "#3f6b57" in stylesheet.text.lower()
    assert script.status_code == 200
    assert scanner_state.status_code == 200
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
    assert 'id="scan-expiry-date"' in html
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
    assert "Prodotto rimosso dalla dispensa" in script


def test_inventory_management_reuses_mobile_scanner_location_controls(client):
    html = client.get("/").text
    stylesheet = client.get("/assets/styles.css").text
    script = client.get("/assets/app.js").text

    assert 'class="summary-location-field inventory-location-field"' in html
    assert 'class="summary-location-grid"' in html
    assert 'renderSummaryLocationButtons(inventoryEditLocation, "inventory-location")' in script
    assert ".summary-location-button" in stylesheet
    assert "min-height: 52px" in stylesheet
