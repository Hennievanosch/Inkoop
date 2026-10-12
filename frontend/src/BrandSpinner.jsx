import React from 'react';
import mark from './assets/tve-mark.png';

export default function BrandSpinner({size=24,label='Even geduld…',decorative=false}){
  return <span className="brand-spinner" style={{width:size,height:size}} role={decorative?undefined:'status'} aria-label={decorative?undefined:label} aria-hidden={decorative?true:undefined}><img src={mark} alt="" width={size} height={size}/></span>;
}
