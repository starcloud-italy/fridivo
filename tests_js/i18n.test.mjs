import assert from "node:assert/strict";
import test from "node:test";

import {
  SUPPORTED_LANGUAGES,
  TRANSLATIONS,
  detectBrowserLanguage,
  resolveInitialLanguage,
  translate
} from "../frontend/i18n.mjs";

test("Italian and English are fully available", () => {
  assert.deepEqual(SUPPORTED_LANGUAGES, ["it", "en"]);
  assert.deepEqual(Object.keys(TRANSLATIONS.it).sort(), Object.keys(TRANSLATIONS.en).sort());
});

test("an Italian browser starts in Italian", () => {
  assert.equal(detectBrowserLanguage(["it-IT", "en-US"]), "it");
});

test("a non-Italian browser starts in English", () => {
  assert.equal(detectBrowserLanguage(["fr-FR", "it-IT"]), "en");
  assert.equal(detectBrowserLanguage([]), "en");
});

test("a stored supported language overrides browser detection", () => {
  assert.equal(resolveInitialLanguage("en", ["it-IT"]), "en");
  assert.equal(resolveInitialLanguage("it", ["en-US"]), "it");
});

test("an invalid stored language falls back to browser detection", () => {
  assert.equal(resolveInitialLanguage("fr", ["it-CH"]), "it");
  assert.equal(resolveInitialLanguage(null, ["de-DE"]), "en");
});

test("dynamic messages interpolate in the selected language", () => {
  assert.equal(translate("it", "inventory.countMany", { count: 3 }), "3 prodotti");
  assert.equal(translate("en", "inventory.countMany", { count: 3 }), "3 products");
  assert.equal(translate("en", "scanner.alreadyScanned", { name: "Baiocchi", quantity: 2 }), "Already scanned · Baiocchi ×2");
  assert.equal(translate("it", "shopping.markPurchased", { name: "Latte" }), "Segna Latte come acquistato");
  assert.equal(translate("en", "shopping.markPurchased", { name: "Milk" }), "Mark Milk as purchased");
  assert.equal(translate("it", "shopping.checkHint"), "Tocca il cerchio quando acquisti un prodotto.");
  assert.equal(translate("en", "shopping.checkHint"), "Tap the circle when you purchase an item.");
});

test("product data passed into translations is preserved", () => {
  assert.match(translate("en", "scanner.scanned", { name: "Baiocchi Mulino Bianco", quantity: 1 }), /Baiocchi Mulino Bianco/);
});
