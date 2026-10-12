import test from 'node:test';
import assert from 'node:assert/strict';
import {sumPrices,formatPrice,companyTotals} from '../frontend/src/pricing.js';

test('Prices add in exact cents, including values exceeding safe floating-point precision',()=>{
  assert.equal(sumPrices(['0.10','0.20']),'0.30');
  assert.equal(sumPrices(['999999999999.99','999999999999.99','0.01']),'1999999999999.99');
  assert.equal(sumPrices(Array(20000).fill('999999999999.99')),'19999999999999800.00');
  assert.equal(formatPrice('19999999999999800.01'),'€ 19.999.999.999.999.800,01');
});

test('An empty price and an explicit zero both contribute zero to the sum',()=>{
  assert.equal(sumPrices([undefined,null,'','0.00','12.34']),'12.34');
  assert.equal(sumPrices([]),'0.00');
  assert.equal(formatPrice('0.00'),'€ 0,00');
});

test('Every company retains its own sum, independent of generic prices and links',()=>{
  const rows=[{price:'999.00',company_ids:[],company_prices:{tve:'12.34',forty:'88.90'}},{company_ids:['tve'],company_prices:{tve:'35.67',forty:'45.67'}}];
  const totals=companyTotals(rows,[{id:'tve'},{id:'forty'},{id:'vdr'}]);
  assert.deepEqual(totals,{tve:'48.01',forty:'134.57',vdr:'0.00'});
  assert.equal(sumPrices(Object.values(totals)),'182.58');
});
