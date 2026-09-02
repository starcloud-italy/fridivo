import assert from "node:assert/strict";
import test from "node:test";

import {
  BARCODE_EXIT_GRACE_MS,
  BARCODE_EXIT_MISSES,
  BarcodePresenceTracker,
  addSessionUnit
} from "../frontend/scanner-state.mjs";

const A = "0801234567890";
const B = "8001234567896";
const productA = { barcode: A, name: "Baiocchi" };

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
