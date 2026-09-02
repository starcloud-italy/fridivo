export const BARCODE_EXIT_GRACE_MS = 700;
export const BARCODE_EXIT_MISSES = 3;
export const SCANNER_STORAGE_LOCATIONS = ["fridge", "freezer", "pantry", "other"];

function normalizeBarcodes(rawValues) {
  return new Set(
    [...rawValues]
      .map((value) => String(value || "").trim())
      .filter((value) => /^\d{8,14}$/.test(value))
  );
}

export class BarcodePresenceTracker {
  constructor({ graceMs = BARCODE_EXIT_GRACE_MS, requiredMisses = BARCODE_EXIT_MISSES } = {}) {
    this.graceMs = graceMs;
    this.requiredMisses = requiredMisses;
    this.present = new Map();
  }

  observe(rawValues, observedAt = Date.now(), { completeFrame = true } = {}) {
    const seen = normalizeBarcodes(rawValues);
    const entered = [];
    const held = [];
    const exited = [];

    for (const [barcode, state] of this.present) {
      if (seen.has(barcode)) {
        state.lastSeenAt = observedAt;
        state.missedAttempts = 0;
      } else if (completeFrame || seen.size === 0) {
        state.missedAttempts += 1;
        if (
          state.missedAttempts >= this.requiredMisses
          && observedAt - state.lastSeenAt >= this.graceMs
        ) {
          this.present.delete(barcode);
          exited.push(barcode);
        }
      }
    }

    for (const barcode of seen) {
      const state = this.present.get(barcode);
      if (state) {
        held.push(barcode);
      } else {
        this.present.set(barcode, {
          enteredAt: observedAt,
          lastSeenAt: observedAt,
          missedAttempts: 0,
          blockedNoticeShown: false
        });
        entered.push(barcode);
      }
    }

    return { entered, held, exited };
  }

  stateFor(barcode) {
    return this.present.get(barcode);
  }

  markBlockedNoticeShown(barcode) {
    const state = this.present.get(barcode);
    if (state) state.blockedNoticeShown = true;
  }

  clear() {
    this.present.clear();
  }
}

export function addSessionUnit(session, barcode, product, onIncrement = () => {}) {
  const previous = session.get(barcode);
  const item = {
    product,
    quantity: (previous?.quantity || 0) + 1,
    lastScannedAt: Date.now(),
    storageLocation: previous?.storageLocation || null,
    expiryDate: previous?.expiryDate || null
  };
  session.set(barcode, item);
  try {
    onIncrement(item);
  } catch {
    // Audio, vibration, or another optional feedback must never block scanning.
  }
  return item;
}

export function setSessionItemLocation(session, barcode, storageLocation) {
  const item = session.get(barcode);
  if (!item || !SCANNER_STORAGE_LOCATIONS.includes(storageLocation)) return false;
  item.storageLocation = storageLocation;
  return true;
}

export function setSessionItemExpiry(session, barcode, expiryDate) {
  const item = session.get(barcode);
  if (!item) return false;
  item.expiryDate = expiryDate || null;
  return true;
}

export function sessionIsReadyToSave(session) {
  return session.size > 0 && [...session.values()].every((item) => item.storageLocation);
}
