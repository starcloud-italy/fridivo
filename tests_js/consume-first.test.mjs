import assert from "node:assert/strict";
import test from "node:test";

import {
  expiryTiming,
  partitionConsumeFirst,
  planAllowsConsumeFirst
} from "../frontend/expiry.mjs";
import { translate } from "../frontend/i18n.mjs";


const TODAY = new Date(2030, 5, 15, 12, 0, 0);


test("expiry states are deterministic for expired, today, tomorrow and future", () => {
  assert.deepEqual(expiryTiming("2030-06-14", TODAY), { status: "EXPIRED", days: -1 });
  assert.deepEqual(expiryTiming("2030-06-15", TODAY), { status: "TODAY", days: 0 });
  assert.deepEqual(expiryTiming("2030-06-16", TODAY), { status: "TOMORROW", days: 1 });
  assert.deepEqual(expiryTiming("2030-06-18", TODAY), { status: "FUTURE", days: 3 });
  assert.equal(expiryTiming(null, TODAY), null);
});

test("expiry day arithmetic is not affected by daylight-saving-hour changes", () => {
  const beforeEuropeanDst = new Date(2030, 2, 30, 12, 0, 0);
  assert.deepEqual(
    expiryTiming("2030-04-01", beforeEuropeanDst),
    { status: "FUTURE", days: 2 }
  );
});

test("PLUS rendering separates expired products from consume-first products", () => {
  const items = [
    { id: "expired", expiry_status: "EXPIRED" },
    { id: "today", expiry_status: "TODAY" },
    { id: "future", expiry_status: "FUTURE" }
  ];
  assert.deepEqual(partitionConsumeFirst(items), {
    expired: [items[0]],
    upcoming: [items[1], items[2]]
  });
  assert.equal(planAllowsConsumeFirst("PLUS"), true);
  assert.equal(planAllowsConsumeFirst("FREE"), false);
});

test("consume-first and expiry copy is available in Italian and English", () => {
  assert.equal(translate("it", "consumeFirst.title"), "Da consumare prima");
  assert.equal(translate("en", "consumeFirst.title"), "Consume first");
  assert.equal(translate("it", "consumeFirst.expiredTitle"), "Scaduti · da verificare");
  assert.equal(translate("en", "consumeFirst.expiredTitle"), "Expired · check first");
  assert.equal(translate("it", "expiry.today"), "Scade oggi");
  assert.equal(translate("en", "expiry.today"), "Expires today");
  assert.equal(translate("it", "expiry.inOneDay"), "Scade domani");
  assert.equal(translate("en", "expiry.inOneDay"), "Expires tomorrow");
  assert.equal(translate("it", "expiry.inDays", { days: 3 }), "Scade tra 3 giorni");
  assert.equal(translate("en", "expiry.inDays", { days: 3 }), "Expires in 3 days");
});
