import React,{useEffect,useState} from 'react';
import {formatPrice} from './pricing';
import BrandSpinner from './BrandSpinner';

const yearColors=['#244c78','#0099cb','#b03178','#dc6030','#268575','#a48d53'];
const yearColor=year=>yearColors[((Number(year)-2024)%yearColors.length+yearColors.length)%yearColors.length];
const compactMoney=value=>new Intl.NumberFormat('nl-NL',{style:'currency',currency:'EUR',notation:'compact',maximumFractionDigits:1}).format(value);

function Comparison({title,series,field='total'}){
  const maximum=Math.max(1,...series.map(p=>Number(p[field]||0)));
  const latest=series.at(-1)?.[field],previous=series.at(-2)?.[field];
  const difference=latest!=null&&previous!=null?Number(latest)-Number(previous):null;
  const years=[...new Set(series.map(p=>p.key.slice(0,4)))];
  const left=48,right=432,top=28,bottom=180,step=(right-left)/Math.max(series.length,1);
  const points=series.map((p,i)=>({...p,x:left+(i+.5)*step,y:bottom-Number(p[field]||0)/maximum*(bottom-top),known:p[field]!=null,color:yearColor(p.key.slice(0,4))}));
  const segments=points.slice(1).flatMap((point,i)=>{
    const previous=points[i];if(!point.known||!previous.known)return [];
    const middle={x:(previous.x+point.x)/2,y:(previous.y+point.y)/2};
    return [{a:previous,b:middle,color:previous.color},{a:middle,b:point,color:point.color}];
  });
  return <section className="panel period-comparison"><div className="panel-head"><div><h3>{title}</h3><p>Productprijzen · zes vorige periodes en de lopende periode</p></div></div>
    <div className="period-year-legend" aria-label="Kleuren per jaar">{years.map(year=><span key={year}><i style={{background:yearColor(year)}}/>{year}</span>)}</div>
    <div className="period-bars">
      <svg className="period-combined-chart" viewBox="0 0 444 232" role="img" aria-label={`${title}: staven met een lijn tussen de toppen. Elke grafiek heeft een eigen euroschaal.`}>
        {[0,.5,1].map(fraction=>{const y=bottom-fraction*(bottom-top);return <g key={fraction}><line x1={left} x2={right} y1={y} y2={y} className="period-gridline"/><text x={left-5} y={y+3} textAnchor="end" className="period-axis-label">{compactMoney(maximum*fraction)}</text></g>})}
        {points.map(p=><g className="period-bar" key={p.key}>
          <title>{`${p.key}${p.current?' (lopend)':''}: ${p.known?formatPrice(p[field]):'Geen historie'}`}</title>
          {p.known?<rect x={p.x-12} y={p.y} width={24} height={bottom-p.y} rx={3} fill={p.color} fillOpacity={.75}/>:<text x={p.x} y={bottom-8} textAnchor="middle" className="period-no-history">–</text>}
          <text x={p.x} y={p.known?Math.max(p.y-8,12):top-12} textAnchor="middle" className="period-amount-label">{p.known?compactMoney(Number(p[field])):'Geen data'}</text>
          <text x={p.x} y={bottom+18} textAnchor="middle" className="period-tick-label">{p.key.includes('-Q')?p.key.split('-')[1]:new Intl.DateTimeFormat('nl-NL',{month:'short'}).format(new Date(p.key+'-01T12:00:00'))}</text>
          <text x={p.x} y={bottom+32} textAnchor="middle" className="period-axis-label">{p.key.slice(0,4)}{p.current?' · nu':''}</text>
        </g>)}
        <g className="period-trend" fill="none" strokeWidth={2.5} strokeLinecap="round">{segments.map((s,i)=><line key={i} x1={s.a.x} y1={s.a.y} x2={s.b.x} y2={s.b.y} stroke={s.color}/>)}</g>
        {points.filter(p=>p.known).map(p=><circle className="period-trend-point" key={p.key} cx={p.x} cy={p.y} r={3} fill={p.color} stroke="white" strokeWidth={1.5}><title>{`${p.key}: ${formatPrice(p[field])}`}</title></circle>)}
      </svg>
    </div>
    <p className="period-note">{difference===null?'Nog geen vorige periode om mee te vergelijken.':`Verschil met vorige periode: ${difference>0?'+':''}${formatPrice(difference.toFixed(2))}.`} Eigen euroschaal per grafiek. De lopende periode kan nog onvolledig zijn.</p>
    <details><summary>Bedragen per periode</summary><table className="data-table"><thead><tr><th>Periode</th><th>Bedrag</th></tr></thead><tbody>{series.map(p=><tr key={p.key}><td>{p.key}</td><td>{p[field]===null?'Geen historie':formatPrice(p[field])}</td></tr>)}</tbody></table></details>
  </section>
}

export function PeriodDashboard({api,post,revision,currentUser,onConfigChanged}){
  const [report,setReport]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[company,setCompany]=useState(''),[draft,setDraft]=useState(null);
  const admin=currentUser.role==='admin';
  async function load(){try{const r=await api('/reporting'+(company?'?company_id='+encodeURIComponent(company):''));setReport(r);setDraft(r.config);setError('')}catch(e){setError(e.message)}}
  useEffect(()=>{let live=true;api('/reporting'+(company?'?company_id='+encodeURIComponent(company):'')).then(r=>{if(live){setReport(r);setDraft(r.config);setError('')}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[revision,company]);
  async function submit(path,body){setBusy(true);setError('');try{await post(path,{...body,revision:report.revision});if(path==='/reporting/config')await onConfigChanged();await load()}catch(e){setError(e.message)}finally{setBusy(false)}}
  if(!report)return <div className="info-strip" role="status">{!error&&<BrandSpinner decorative/>}{error||'Periodeoverzicht laden…'}</div>;
  return <div className="period-dashboard">
    <section className="panel period-entry"><div><h2>Prijsinvoer {report.period}</h2><p>Uiterlijk {new Date(report.deadline+'T12:00:00').toLocaleDateString('nl-NL')} · {report.coverage.expected-report.coverage.missing} van {report.coverage.expected} bedrijfsprijzen ingevuld.</p></div>
      {error&&<div className="alert error" role="alert">{error}</div>}
      {report.completion?<p className="alert">Periode bevestigd op {new Date(report.completion.at).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'})}.</p>:<><p className={report.overdue?'alert warning':'muted'}>{report.overdue?'De deadline is verstreken. Vul de ontbrekende prijzen alsnog in en bevestig de periode.':'Vul uw prijzen in en bevestig daarna de periode, ook als de bedragen gelijk zijn gebleven.'}</p><button className="btn primary" disabled={busy||report.coverage.missing>0||!report.coverage.expected} onClick={()=>submit('/reporting/complete',{period:report.period})}>{busy&&<BrandSpinner size={18} decorative/>}Invoer voor deze periode bevestigen</button></>}
      {admin&&<details className="period-settings"><summary>Invoerperiode en herinneringen instellen</summary><form onSubmit={e=>{e.preventDefault();submit('/reporting/config',draft)}}><label>Periode<select aria-label="Periode" value={draft.frequency} onChange={e=>setDraft({...draft,frequency:e.target.value})}><option value="quarter">Per kwartaal</option><option value="month">Per maand</option></select></label><label>Deadline in de laatste maand<select aria-label="Deadline in de laatste maand" value={draft.deadline} onChange={e=>setDraft({...draft,deadline:e.target.value})}><option value="day25">De 25e</option><option value="last_friday">De laatste vrijdag</option></select></label><p>Op de deadline ontvangt iedere actieve gebruiker die zijn invoer nog niet heeft bevestigd één herinnering van info@tve.nl.</p><p className={report.mail_ready?'muted':'alert warning'}>{report.mail_ready?'De verzendinstellingen zijn aanwezig.':'Automatische mail is nog niet actief: de maildienst moet worden aangesloten.'}</p><button className="btn" disabled={busy}>{busy&&<BrandSpinner size={18} decorative/>}Instellingen opslaan</button></form></details>}
    </section>
    {admin&&<label className="period-company">Bedrijf voor de vergelijking<select aria-label="Bedrijf voor de vergelijking" value={company||report.selected_company||''} onChange={e=>setCompany(e.target.value)}>{report.companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
    <div className="period-comparisons">
      <Comparison title={admin?'Bedrijfsvergelijking':'Vergelijking voor uw bedrijven'} series={report.series}/>
      <Comparison title="Vergelijking voor de hele groep" series={report.series} field="group_total"/>
    </div>
  </div>
}
