export const CONSUMPTION_ACTIONS = Object.freeze([
  Object.freeze({ type: "CONSUMED", translationKey: "consumption.consumed", icon: "✓" }),
  Object.freeze({ type: "FINISHED", translationKey: "consumption.finished", icon: "∅" }),
  Object.freeze({ type: "DISCARDED", translationKey: "consumption.discarded", icon: "×" })
]);

export function consumptionEventPayload(inventoryItemId, eventType, quantity) {
  const payload = { inventory_item_id: inventoryItemId, event_type: eventType };
  if (eventType !== "FINISHED") payload.quantity = quantity;
  return payload;
}

export function inventoryAfterConsumption(items, inventoryItemId, consumedQuantity) {
  const item = items.find((candidate) => candidate.id === inventoryItemId);
  if (!item) return items;
  const remaining = item.quantity - consumedQuantity;
  return remaining > 0
    ? items.map((candidate) => candidate.id === inventoryItemId
      ? { ...candidate, quantity: remaining }
      : candidate)
    : items.filter((candidate) => candidate.id !== inventoryItemId);
}
