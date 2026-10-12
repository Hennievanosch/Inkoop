// Stored prices are decimal text. Add integer cents so totals keep every cent.
export function sumPrices(values){
  const cents=values.reduce((sum,value)=>{
    if(value===undefined||value===null||value==='')return sum;
    const [whole,fraction='']=String(value).split('.');
    return sum+BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
  },0n);
  return `${cents/100n}.${String(cents%100n).padStart(2,'0')}`;
}

export function formatPrice(value){
  if(value===undefined||value===null||value==='')return 'Geen prijs';
  const [whole,fraction='']=String(value).split('.');
  return `€ ${new Intl.NumberFormat('nl-NL').format(BigInt(whole))},${fraction.padEnd(2,'0')}`;
}

export function companyTotals(rows,companies){
  return Object.fromEntries(companies.map(company=>[company.id,sumPrices(rows.map(row=>row.company_prices?.[company.id]))]));
}
