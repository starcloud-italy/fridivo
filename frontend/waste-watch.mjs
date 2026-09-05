export function visibleWasteWatch(plan, items) {
  return plan === "PLUS" ? items.slice(0, 5) : [];
}
