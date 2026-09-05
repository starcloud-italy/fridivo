export function visibleOverview(plan, overview) {
  return plan === "PLUS" && overview ? overview : null;
}

export function quantityKey(prefix, count) {
  return `${prefix}${count === 1 ? "One" : "Many"}`;
}
