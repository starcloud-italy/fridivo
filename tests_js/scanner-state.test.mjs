import assert from "node:assert/strict";
import test from "node:test";

import {
  BARCODE_EXIT_GRACE_MS,
  BARCODE_EXIT_MISSES,
  BarcodePresenceTracker,
  addSessionUnit,
  isAcceptableBarcode,
  normalizeBarcode,
  sessionIsReadyToSave,
  setSessionItemExpiry,
  setSessionItemLocation
} from "../frontend/scanner-state.mjs";

const A = "0801234567890";
const B = "8001234567896";
const productA = { barcode: A, name: "Baiocchi" };

test("manual barcode normalization preserves leading zeroes", () => {
  const barcode = normalizeBarcode("  0012345678905  ");
  assert.equal(barcode, "0012345678905");
  assert.equal(isAcceptableBarcode(barcode), true);
});

test("barcode validation matches the existing 8 to 14 digit lookup format", () => {
  assert.equal(isAcceptableBarcode("12345678"), true);
  assert.equal(isAcceptableBarcode("12345678901234"), true);
  assert.equal(isAcceptableBarcode("1234567"), false);
  assert.equal(isAcceptableBarcode("1234-5678"), false);
  assert.equal(isAcceptableBarcode("123456789012345"), false);
});

function registerEntries(tracker, session, values, time, feedback) {
  const events = tracker.observe(values, time);
  for (const barcode of events.entered) {
    addSessionUnit(session, barcode, barcode === A ? productA : { barcode, name: "Latte" }, feedback);
  }
  return events;
}

test("first appearance registers exactly one unit", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  registerEntries(tracker, session, [A], 0);
  assert.equal(session.get(A).quantity, 1);
});

test("a barcode held in frame for several seconds remains one unit", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  registerEntries(tracker, session, [A], 0);
  for (let time = 250; time <= 10000; time += 250) registerEntries(tracker, session, [A], time);
  assert.equal(session.get(A).quantity, 1);
});

test("one or two missed attempts do not unlock a barcode", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  registerEntries(tracker, session, [A], 0);
  registerEntries(tracker, session, [], BARCODE_EXIT_GRACE_MS);
  registerEntries(tracker, session, [], BARCODE_EXIT_GRACE_MS + 100);
  registerEntries(tracker, session, [A], BARCODE_EXIT_GRACE_MS + 200);
  assert.equal(session.get(A).quantity, 1);
});

test("confirmed exit followed by re-entry registers a second unit", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  registerEntries(tracker, session, [A], 0);
  for (let miss = 1; miss <= BARCODE_EXIT_MISSES; miss += 1) {
    registerEntries(tracker, session, [], BARCODE_EXIT_GRACE_MS + miss * 100);
  }
  registerEntries(tracker, session, [A], BARCODE_EXIT_GRACE_MS + 500);
  assert.equal(session.get(A).quantity, 2);
});

test("three distinct passes register three units", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  let time = 0;
  for (let pass = 0; pass < 3; pass += 1) {
    registerEntries(tracker, session, [A], time);
    time += BARCODE_EXIT_GRACE_MS;
    for (let miss = 0; miss < BARCODE_EXIT_MISSES; miss += 1) {
      registerEntries(tracker, session, [], time + miss * 100);
    }
    time += 1000;
  }
  assert.equal(session.get(A).quantity, 3);
});

test("a held barcode A does not block a newly appearing barcode B", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  registerEntries(tracker, session, [A], 0);
  const events = registerEntries(tracker, session, [A, B], 250);
  assert.deepEqual(events.entered, [B]);
  assert.equal(session.get(A).quantity, 1);
  assert.equal(session.get(B).quantity, 1);
});

test("a single-result decoder does not treat seeing B as proof that A exited", () => {
  const tracker = new BarcodePresenceTracker();
  tracker.observe([A], 0, { completeFrame: false });
  for (let time = 250; time <= 2000; time += 250) {
    tracker.observe([B], time, { completeFrame: false });
  }
  const aState = tracker.stateFor(A);
  assert.ok(aState);
  assert.equal(aState.missedAttempts, 0);
});

test("manual add registers one extra unit", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, A, productA);
  assert.equal(session.get(A).quantity, 2);
});

test("feedback is emitted once per valid increment and never for held reads", () => {
  const tracker = new BarcodePresenceTracker();
  const session = new Map();
  let beeps = 0;
  const feedback = () => { beeps += 1; };
  registerEntries(tracker, session, [A], 0, feedback);
  for (let time = 250; time <= 3000; time += 250) registerEntries(tracker, session, [A], time, feedback);
  assert.equal(beeps, 1);
  addSessionUnit(session, A, productA, feedback);
  assert.equal(beeps, 2);
});

test("unavailable optional audio feedback cannot block quantity updates", () => {
  const session = new Map();
  addSessionUnit(session, A, productA, () => { throw new Error("Web Audio unavailable"); });
  assert.equal(session.get(A).quantity, 1);
});

test("different products retain different storage locations", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, B, { barcode: B, name: "Latte" });
  setSessionItemLocation(session, A, "pantry");
  setSessionItemLocation(session, B, "fridge");
  assert.equal(session.get(A).storageLocation, "pantry");
  assert.equal(session.get(B).storageLocation, "fridge");
});

test("session is not ready while at least one product has no location", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, B, { barcode: B, name: "Latte" });
  setSessionItemLocation(session, A, "pantry");
  assert.equal(sessionIsReadyToSave(session), false);
});

test("session becomes ready after every product receives a location", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, B, { barcode: B, name: "Latte" });
  setSessionItemLocation(session, A, "pantry");
  setSessionItemLocation(session, B, "fridge");
  assert.equal(sessionIsReadyToSave(session), true);
});

test("quantity changes preserve the selected product location", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  setSessionItemLocation(session, A, "pantry");
  addSessionUnit(session, A, productA);
  assert.equal(session.get(A).quantity, 2);
  assert.equal(session.get(A).storageLocation, "pantry");
});

test("different scanned products retain independent optional expiry dates", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, B, { barcode: B, name: "Latte" });
  setSessionItemExpiry(session, A, "2027-02-15");
  setSessionItemExpiry(session, B, "2026-09-08");
  assert.equal(session.get(A).expiryDate, "2027-02-15");
  assert.equal(session.get(B).expiryDate, "2026-09-08");
});

test("a missing expiry date does not prevent scanner confirmation", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  setSessionItemLocation(session, A, "pantry");
  assert.equal(session.get(A).expiryDate, null);
  assert.equal(sessionIsReadyToSave(session), true);
});

test("removing an unassigned product recalculates readiness from remaining products", () => {
  const session = new Map();
  addSessionUnit(session, A, productA);
  addSessionUnit(session, B, { barcode: B, name: "Latte" });
  setSessionItemLocation(session, A, "pantry");
  session.delete(B);
  assert.equal(sessionIsReadyToSave(session), true);
});
