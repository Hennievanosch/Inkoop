import test from 'node:test';
import assert from 'node:assert/strict';
import {matchesSupplierProduct, normalizeSearch} from '../frontend/src/search.js';

const maps = {
  suppliers: {s1: {name: 'Café Print'}, s2: {name: 'Andere leverancier'}},
  categories: {c1: {name: 'Drukwerk'}, c2: {name: 'Folie'}},
};
const rows = [
  {id: 'r1', supplier_id: 's1', category_id: 'c1', product_name: 'Etiketten'},
  {id: 'r2', supplier_id: 's1', category_id: 'c2', product_name: 'Raamfolie'},
  {id: 'r3', supplier_id: 's2', category_id: 'c1', product_name: 'Etiketten'},
];
const results = query => rows.filter(row => matchesSupplierProduct(row, maps, query)).map(row => row.id);

test('Zoeken negeert hoofdletters, accenten en extra spaties', () => {
  assert.equal(normalizeSearch('  CAFÉ   PrInT  '), 'cafe print');
  assert.deepEqual(results('  CAFE  '), ['r1', 'r2']);
});
test('Een zoekterm kan leverancier, product en categorie combineren', () => {
  assert.deepEqual(results('print etiketten'), ['r1']);
  assert.deepEqual(results('drukwerk'), ['r1', 'r3']);
  assert.deepEqual(results('raam'), ['r2']);
  assert.deepEqual(results('print drukwerk raam'), []);
});
test('Leeg zoeken geeft alle productregels terug en behoudt oorspronkelijke gegevens', () => {
  const before = JSON.stringify({rows, maps});
  assert.deepEqual(results('   '), ['r1', 'r2', 'r3']);
  assert.deepEqual(results('onbekende zoekterm'), []);
  assert.equal(JSON.stringify({rows, maps}), before);
  assert.equal(matchesSupplierProduct({product_name: 'Sticker'}, {}, 'sticker'), true);
});
