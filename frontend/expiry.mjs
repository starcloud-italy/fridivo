const MILLISECONDS_PER_DAY = 86_400_000;

function utcDayNumber(year, month, day) {
  return Date.UTC(year, month - 1, day) / MILLISECONDS_PER_DAY;
}

export function expiryTiming(dateValue, today = new Date()) {
  if (!dateValue) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateValue);
  if (!match) return null;
  const expiryDay = utcDayNumber(Number(match[1]), Number(match[2]), Number(match[3]));
  const currentDay = utcDayNumber(
    today.getFullYear(),
    today.getMonth() + 1,
    today.getDate()
  );
  const days = expiryDay - currentDay;
  if (days < 0) return { status: "EXPIRED", days };
  if (days === 0) return { status: "TODAY", days };
  if (days === 1) return { status: "TOMORROW", days };
  return { status: "FUTURE", days };
}

export function partitionConsumeFirst(items) {
  return items.reduce((groups, item) => {
    const target = item.expiry_status === "EXPIRED" ? groups.expired : groups.upcoming;
    target.push(item);
    return groups;
  }, { expired: [], upcoming: [] });
}

export function planAllowsConsumeFirst(plan) {
  return plan === "PLUS";
}

export function visibleInventoryItems(plan, inventoryItems, consumeFirstItems) {
  if (!planAllowsConsumeFirst(plan)) return inventoryItems;
  const displayedPriorityIds = new Set(
    consumeFirstItems.slice(0, 5).map((item) => String(item.id))
  );
  if (!displayedPriorityIds.size) return inventoryItems;
  return inventoryItems.filter((item) => !displayedPriorityIds.has(String(item.id)));
}
