import assert from "node:assert/strict";
import test from "node:test";

import { translate } from "../frontend/i18n.mjs";
import { quantityKey, visibleOverview } from "../frontend/overview.mjs";


const overview = {
  period: { days: 30 },
  used_quantity: 32,
  discarded_quantity: 5,
  waste_ratio: 0.135,
  repeated_waste_product_count: 2,
  repurchase_candidate_count: 3,
  expiry_attention_product_count: 2
};


test("overview is visible only to PLUS households", () => {
  assert.equal(visibleOverview("PLUS", overview), overview);
  assert.equal(visibleOverview("FREE", overview), null);
  assert.equal(visibleOverview("PLUS", null), null);
});

test("overview titles and period are localized", () => {
  assert.equal(translate("it", "overview.title"), "Il tuo andamento");
  assert.equal(translate("en", "overview.title"), "Your overview");
  assert.equal(translate("it", "overview.period", { count: 30 }), "Ultimi 30 giorni");
  assert.equal(translate("en", "overview.period", { count: 30 }), "Last 30 days");
});

test("overview metric labels use correct singular and plural", () => {
  assert.equal(quantityKey("overview.used", 1), "overview.usedOne");
  assert.equal(quantityKey("overview.used", 0), "overview.usedMany");
  assert.equal(translate("it", quantityKey("overview.repeatedWaste", 1)), "prodotto con scarti ripetuti");
  assert.equal(translate("it", quantityKey("overview.repurchase", 2)), "prodotti che potrebbero servire nuovamente");
  assert.equal(translate("en", quantityKey("overview.expiry", 1)), "product needing expiry attention");
  assert.equal(translate("en", quantityKey("overview.discarded", 2)), "units discarded");
});
