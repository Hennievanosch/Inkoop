import React,{useEffect,useState} from 'react';
import {formatPrice} from './pricing';
import BrandSpinner from './BrandSpinner';

const yearColors=['#244c78','#0099cb','#b03178','#dc6030','#268575','#a48d53'];
const yearColor=year=>yearColors[((Number(year)-2024)%yearColors.length+yearColors.length)%yearColors.length];
const compactMoney=value=>new Intl.NumberFormat('nl-NL',{style:'currency',currency:'EUR',notation:'compact',maximumFractionDigits:1}).format(value);

function Comparison({title,series,field='total'}){
  const maximum=Math.max(1,...series.map(p=>Number(p[field]||0)));
  const years=[...new Set(series.map(p=>p.key.slice(0,4)))].sort();
  const annual=series.filter(p=>!p.key.includes('-Q'));
  const quarterly=series.filter(p=>p.key.includes('-Q'));
  const quarterYears=[...new Set(quarterly.map(p=>p.key.slice(0,4)))].sort();
  const quarters=quarterly.length?['Q1','Q2','Q3','Q4']:[];
  const groups=[...annual.map(p=>({label:p.key,items:[p]})),...quarters.map(q=>({label:q,items:quarterYears.map(year=>quarterly.find(p=>p.key===`${year}-${q}`)||{key:`${year}-${q}`,[field]:null})}))];
  const current=quarterly.find(p=>p.current);
  const previous=current&&quarterly.find(p=>p.key===`${Number(current.key.slice(0,4))-1}-${current.key.split('-')[1]}`);
  const difference=current?.[field]!=null&&previous?.[field]!=null?Number(current[field])-Number(previous[field]):null;
  const left=48,right=432,top=28,bottom=180,step=(right-left)/Math.max(groups.length,1);
  const barWidth=Math.min(22,58/Math.max(quarterYears.length,1));
  const points=groups.flatMap((group,q)=>group.items.map((p,i)=>({...p,year:p.key.slice(0,4),quarter:p.key.split('-')[1],x:left+(q+.5)*step+(i-(group.items.length-1)/2)*(barWidth+5),y:bottom-Number(p[field]||0)/maximum*(bottom-top),known:p[field]!=null,color:yearColor(p.key.slice(0,4)),annual:!p.key.includes('-Q')})));
  const segments=quarterYears.flatMap(year=>{
    const yearly=points.filter(p=>p.year===year&&!p.annual);
    return yearly.slice(1).flatMap((point,i)=>yearly[i].known&&point.known?[{a:yearly[i],b:point,color:point.color,year}]:[]);
  });
  return <section className="panel period-comparison"><div className="panel-head"><div><h3>{title}</h3><p>2026 als jaarbedrag · kwartaalmetingen vanaf januari 2027</p></div></div>
    <div className="period-year-legend" aria-label="Kleuren per jaar">{years.map(year=><span key={year}><i style={{background:yearColor(year)}}/>{year}</span>)}</div>
    <div className="period-bars">
      <svg className="period-combined-chart" viewBox="0 0 444 232" role="img" aria-label={`${title}: 2026 als één jaarbedrag; kwartalen vanaf 2027 met een eigen lijn per meetjaar. Elke grafiek heeft een eigen euroschaal.`}>
        {[0,.5,1].map(fraction=>{const y=bottom-fraction*(bottom-top);return <g key={fraction}><line x1={left} x2={right} y1={y} y2={y} className="period-gridline"/><text x={left-5} y={y+3} textAnchor="end" className="period-axis-label">{compactMoney(maximum*fraction)}</text></g>})}
        {points.map(p=><g className="period-bar" key={p.key} data-period={p.key} data-year={p.year}>
          <title>{`${p.key}${p.annual?' (heel jaar)':p.current?' (lopend)':''}: ${p.known?formatPrice(p[field]):p.future?'Nog niet begonnen':'Geen historie'}`}</title>
          {p.known?<rect x={p.x-barWidth/2} y={p.y} width={barWidth} height={bottom-p.y} rx={3} fill={p.color} fillOpacity={.75}/>:<text x={p.x} y={bottom-8} textAnchor="middle" className="period-no-history">–</text>}
          <text x={p.x+(p.annual?0:p.year===quarterYears[0]?-3:3)} y={p.known?Math.max(p.y-8,12):top-12} textAnchor={p.annual?'middle':p.year===quarterYears[0]?'end':'start'} style={{fontSize:quarterYears.length>1?8:9}} className="period-amount-label">{p.known?compactMoney(Number(p[field])):''}</text>
          <text x={p.x} y={bottom+15} textAnchor="middle" className="period-axis-label">{p.annual?'Heel jaar':p.year}{p.current&&!p.annual?' · nu':''}</text>
        </g>)}
        {groups.map((group,i)=><text key={group.label} x={left+(i+.5)*step} y={bottom+31} textAnchor="middle" className="period-tick-label">{group.label}</text>)}
        <g className="period-trend" fill="none" strokeWidth={2.5} strokeLinecap="round">{segments.map((s,i)=><line key={i} x1={s.a.x} y1={s.a.y} x2={s.b.x} y2={s.b.y} stroke={s.color} data-year={s.year}/>)}</g>
        {points.filter(p=>p.known).map(p=><circle className="period-trend-point" key={p.key} data-period={p.key} cx={p.x} cy={p.y} r={3} fill={p.color} stroke="white" strokeWidth={1.5}><title>{`${p.key}: ${formatPrice(p[field])}`}</title></circle>)}
      </svg>
    </div>
    <p className="period-note">{difference===null?(quarterly.length?'Er is nog geen vergelijking met een overeenkomstig kwartaal beschikbaar.':'2026 toont uitsluitend het jaarbedrag. Meten per kwartaal begint in januari 2027.'):`Verschil ${current.key} t.o.v. ${previous.key}: ${difference>0?'+':''}${formatPrice(difference.toFixed(2))}.`} Het jaarbedrag van 2026 wordt niet met een kwartaal vergeleken. Eigen euroschaal per grafiek.</p>
    <details><summary>Bedragen per periode</summary><table className="data-table"><thead><tr><th>Periode</th><th>Bedrag</th></tr></thead><tbody>{series.map(p=><tr key={p.key}><td>{p.key}</td><td>{p[field]===null?(p.future?'Nog niet begonnen':'Geen historie'):formatPrice(p[field])}</td></tr>)}</tbody></table></details>
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
    <section className="panel period-entry"><div><h2>{report.informative_only?'Jaargegevens 2026 · informatief':`Prijsinvoer ${report.period}`}</h2><p>{report.deadline?`Uiterlijk ${new Date(report.deadline+'T12:00:00').toLocaleDateString('nl-NL')} · `:''} {report.coverage.expected-report.coverage.missing} van {report.coverage.expected} bedrijfsprijzen ingevuld.</p></div>
      {error&&<div className="alert error" role="alert">{error}</div>}
      {report.informative_only?<p className="muted">Vul de bedragen voor heel 2026 in. Dit jaar wordt niet over kwartalen verdeeld. Meten per kwartaal begint op 1 januari 2027.</p>:report.completion?<p className="alert">Periode bevestigd op {new Date(report.completion.at).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'})}.</p>:<><p className={report.overdue?'alert warning':'muted'}>{report.overdue?'De deadline is verstreken. Vul de ontbrekende prijzen alsnog in en bevestig de periode.':'Vul uw prijzen in en bevestig daarna de periode, ook als de bedragen gelijk zijn gebleven.'}</p><button className="btn primary" disabled={busy||report.coverage.missing>0||!report.coverage.expected} onClick={()=>submit('/reporting/complete',{period:report.period})}>{busy&&<BrandSpinner size={18} decorative/>}Invoer voor deze periode bevestigen</button></>}
      {admin&&<details className="period-settings"><summary>Invoerperiode en herinneringen instellen</summary><form onSubmit={e=>{e.preventDefault();submit('/reporting/config',draft)}}><label>Periode<select aria-label="Periode" value={draft.frequency} onChange={e=>setDraft({...draft,frequency:e.target.value})}><option value="quarter">Per kwartaal</option><option value="month">Per maand</option></select></label><label>Deadline in de laatste maand<select aria-label="Deadline in de laatste maand" value={draft.deadline} onChange={e=>setDraft({...draft,deadline:e.target.value})}><option value="day25">De 25e</option><option value="last_friday">De laatste vrijdag</option></select></label><p>Vanaf 2027 ontvangt op de deadline iedere actieve gebruiker die zijn invoer nog niet heeft bevestigd één herinnering van info@tve.nl.</p><p className={report.mail_ready?'muted':'alert warning'}>{report.mail_ready?'De verzendinstellingen zijn aanwezig.':'Automatische mail is nog niet actief: de maildienst moet worden aangesloten.'}</p><button className="btn" disabled={busy}>{busy&&<BrandSpinner size={18} decorative/>}Instellingen opslaan</button></form></details>}
    </section>
    {admin&&<label className="period-company">Bedrijf in het overzicht<select aria-label="Bedrijf in het overzicht" value={company||report.selected_company||''} onChange={e=>setCompany(e.target.value)}>{report.companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
    <div className="period-comparisons">
      <Comparison title={admin?'Bedrijfsoverzicht':'Overzicht voor uw bedrijven'} series={report.series}/>
      <Comparison title="Groepsoverzicht" series={report.series} field="group_total"/>
    </div>
  </div>
}
