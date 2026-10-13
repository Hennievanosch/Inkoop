export function normalizeSearch(value) {
  return String(value ?? '').normalize('NFD').replace(/\p{M}/gu, '')
    .toLocaleLowerCase('nl-NL').trim().replace(/\s+/g, ' ');
}

export function matchesSupplierProduct(row, maps, query) {
  const terms = normalizeSearch(query).split(' ').filter(Boolean);
  if (!terms.length) return true;
  const text = normalizeSearch([
    maps.suppliers?.[row.supplier_id]?.name,
    row.product_name,
    maps.categories?.[row.category_id]?.name,
  ].filter(Boolean).join(' '));
  return terms.every(term => text.includes(term));
}
