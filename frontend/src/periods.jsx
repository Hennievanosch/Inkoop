import React,{useEffect,useState} from 'react';
import {formatPrice} from './pricing';

function Comparison({title,series,field='total'}){
  const max=Math.max(1,...series.map(p=>Number(p[field]||0)));
  const latest=series.at(-1)?.[field],previous=series.at(-2)?.[field];
  const difference=latest!==null&&previous!==null?Number(latest)-Number(previous):null;
  return <section className="panel period-comparison"><div className="panel-head"><div><h3>{title}</h3><p>Som van de ingevoerde productprijzen · zes vorige periodes en de lopende periode</p></div></div>
    <div className="period-bars" role="img" aria-label={title}>{series.map(p=><div className="period-bar" key={p.key}><strong>{p[field]===null?'Geen historie':formatPrice(p[field])}</strong><div className="period-bar-space"><div style={{height:`${Number(p[field]||0)/max*100}%`}} className={p.current?'current':''}/></div><span>{p.key}{p.current?' (lopend)':''}</span></div>)}</div>
    <p className="period-note">{difference===null?'Er is nog geen vorige periode beschikbaar om mee te vergelijken.':`Verschil met de vorige periode: ${difference>0?'+':''}${formatPrice(difference.toFixed(2))}.`} Dit zijn opgetelde prijzen, geen inkoopuitgaven. De lopende periode kan nog onvolledig zijn.</p>
    <details><summary>Bedragen per periode</summary><table className="data-table"><thead><tr><th>Periode</th><th>Bedrag</th></tr></thead><tbody>{series.map(p=><tr key={p.key}><td>{p.key}</td><td>{p[field]===null?'Geen historie':formatPrice(p[field])}</td></tr>)}</tbody></table></details>
  </section>
}

export function PeriodDashboard({api,post,revision,currentUser,onConfigChanged}){
  const [report,setReport]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[company,setCompany]=useState(''),[draft,setDraft]=useState(null);
  const admin=currentUser.role==='admin';
  async function load(){try{const r=await api('/reporting'+(company?'?company_id='+encodeURIComponent(company):''));setReport(r);setDraft(r.config);setError('')}catch(e){setError(e.message)}}
  useEffect(()=>{let live=true;api('/reporting'+(company?'?company_id='+encodeURIComponent(company):'')).then(r=>{if(live){setReport(r);setDraft(r.config);setError('')}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[revision,company]);
  async function submit(path,body){setBusy(true);setError('');try{await post(path,{...body,revision:report.revision});if(path==='/reporting/config')await onConfigChanged();await load()}catch(e){setError(e.message)}finally{setBusy(false)}}
  if(!report)return <div className="info-strip" role="status">{error||'Periodeoverzicht laden…'}</div>;
  return <div className="period-dashboard">
    <section className="panel period-entry"><div><h2>Prijsinvoer {report.period}</h2><p>Uiterlijk {new Date(report.deadline+'T12:00:00').toLocaleDateString('nl-NL')} · {report.coverage.expected-report.coverage.missing} van {report.coverage.expected} bedrijfsprijzen ingevuld.</p></div>
      {error&&<div className="alert error" role="alert">{error}</div>}
      {report.completion?<p className="alert">Periode bevestigd op {new Date(report.completion.at).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'})}.</p>:<><p className={report.overdue?'alert warning':'muted'}>{report.overdue?'De deadline is verstreken. Vul de ontbrekende prijzen alsnog in en bevestig de periode.':'Vul uw prijzen in en bevestig daarna de periode, ook als de bedragen gelijk zijn gebleven.'}</p><button className="btn primary" disabled={busy||report.coverage.missing>0||!report.coverage.expected} onClick={()=>submit('/reporting/complete',{period:report.period})}>Invoer voor deze periode bevestigen</button></>}
      {admin&&<details className="period-settings"><summary>Invoerperiode en herinneringen instellen</summary><form onSubmit={e=>{e.preventDefault();submit('/reporting/config',draft)}}><label>Periode<select aria-label="Periode" value={draft.frequency} onChange={e=>setDraft({...draft,frequency:e.target.value})}><option value="quarter">Per kwartaal</option><option value="month">Per maand</option></select></label><label>Deadline in de laatste maand<select aria-label="Deadline in de laatste maand" value={draft.deadline} onChange={e=>setDraft({...draft,deadline:e.target.value})}><option value="day25">De 25e</option><option value="last_friday">De laatste vrijdag</option></select></label><p>Op de deadline ontvangt iedere actieve gebruiker die zijn invoer nog niet heeft bevestigd één herinnering van info@tve.nl.</p><p className={report.mail_ready?'muted':'alert warning'}>{report.mail_ready?'De verzendinstellingen zijn aanwezig.':'Automatische mail is nog niet actief: de maildienst moet worden aangesloten.'}</p><button className="btn" disabled={busy}>Instellingen opslaan</button></form></details>}
    </section>
    {admin&&<label className="period-company">Bedrijf voor de vergelijking<select aria-label="Bedrijf voor de vergelijking" value={company||report.selected_company||''} onChange={e=>setCompany(e.target.value)}>{report.companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
    <Comparison title={admin?'Bedrijfsvergelijking':'Vergelijking voor uw bedrijven'} series={report.series}/>
    {admin&&<Comparison title="Vergelijking voor de hele groep" series={report.series} field="group_total"/>}
  </div>
}
