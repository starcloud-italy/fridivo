import assert from "node:assert/strict";
import test from "node:test";

import {
  removeShoppingSuggestion,
  visibleShoppingSuggestions
} from "../frontend/shopping-suggestions.mjs";
import { translate } from "../frontend/i18n.mjs";


const suggestions = Array.from({ length: 7 }, (_value, index) => ({
  product_barcode: String(index + 1),
  product_name: `Product ${index + 1}`
}));


test("PLUS renders no more than five shopping suggestions", () => {
  assert.deepEqual(visibleShoppingSuggestions("PLUS", suggestions), suggestions.slice(0, 5));
});

test("FREE renders no shopping suggestions", () => {
  assert.deepEqual(visibleShoppingSuggestions("FREE", suggestions), []);
});

test("a confirmed shopping addition removes its suggestion locally", () => {
  assert.deepEqual(removeShoppingSuggestion(suggestions, "3"), [
    suggestions[0],
    suggestions[1],
    suggestions[3],
    suggestions[4],
    suggestions[5],
    suggestions[6]
  ]);
});

test("shopping suggestion copy is available in Italian and English", () => {
  assert.equal(translate("it", "shoppingSuggestions.title"), "Potrebbero servirti");
  assert.equal(translate("en", "shoppingSuggestions.title"), "You may need these");
  assert.equal(translate("it", "shoppingSuggestions.add"), "Aggiungi alla spesa");
  assert.equal(translate("en", "shoppingSuggestions.add"), "Add to shopping list");
});
