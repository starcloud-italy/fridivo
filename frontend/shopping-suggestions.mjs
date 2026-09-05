export function visibleShoppingSuggestions(plan, suggestions) {
  return plan === "PLUS" ? suggestions.slice(0, 5) : [];
}

export function removeShoppingSuggestion(suggestions, productBarcode) {
  return suggestions.filter((item) => item.product_barcode !== productBarcode);
}
