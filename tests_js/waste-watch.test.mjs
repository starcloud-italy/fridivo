import assert from "node:assert/strict";
import test from "node:test";

import { translate } from "../frontend/i18n.mjs";
import { visibleWasteWatch } from "../frontend/waste-watch.mjs";


const patterns = Array.from({ length: 7 }, (_value, index) => ({
  product_barcode: String(index + 1),
  discarded_event_count: index + 2,
  discarded_quantity: index + 3
}));


test("PLUS renders at most five waste patterns while FREE renders none", () => {
  assert.deepEqual(visibleWasteWatch("PLUS", patterns), patterns.slice(0, 5));
  assert.deepEqual(visibleWasteWatch("FREE", patterns), []);
});

test("an empty result keeps the waste section empty", () => {
  assert.deepEqual(visibleWasteWatch("PLUS", []), []);
});

test("waste facts use correct Italian and English singular and plural", () => {
  assert.equal(
    translate("it", "wasteWatch.discardedOne", { count: 1 }),
    "Scartato 1 volta negli ultimi 30 giorni."
  );
  assert.equal(
    translate("it", "wasteWatch.discardedMany", { count: 3 }),
    "Scartato 3 volte negli ultimi 30 giorni."
  );
  assert.equal(
    translate("en", "wasteWatch.discardedOne", { count: 1 }),
    "Discarded 1 time in the last 30 days."
  );
  assert.equal(
    translate("en", "wasteWatch.discardedMany", { count: 3 }),
    "Discarded 3 times in the last 30 days."
  );
  assert.equal(
    translate("it", "wasteWatch.quantityMany", { count: 4 }),
    "4 unità scartate complessivamente."
  );
  assert.equal(
    translate("en", "wasteWatch.quantityMany", { count: 4 }),
    "4 units discarded in total."
  );
});

test("waste-watch titles and cautious suggestion are localized", () => {
  assert.equal(translate("it", "wasteWatch.title"), "Sprechi da tenere d'occhio");
  assert.equal(translate("en", "wasteWatch.title"), "Waste to watch");
  assert.equal(
    translate("it", "wasteWatch.suggestion"),
    "Potresti valutare di acquistarne una quantità minore."
  );
  assert.equal(
    translate("en", "wasteWatch.suggestion"),
    "You may want to consider buying a smaller quantity."
  );
});
