import React,{useEffect,useState} from 'react';
import BrandSpinner from './BrandSpinner';

const kinds={monthly:'Automatisch',manual:'Tussentijds',before_restore:'Veiligheidskopie vóór herstel'};
const date=value=>new Date(value).toLocaleString('nl-NL',{timeZone:'Europe/Amsterdam'});

export default function BackupsPanel({api,post,Button,revision,onBusyChange,onRestored}){
  const [records,setRecords]=useState(null),[selected,setSelected]=useState(''),[confirmed,setConfirmed]=useState(false),[base,setBase]=useState(revision),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{let active=true;api('/backups').then(result=>{if(active){setRecords(result.backups);setBase(result.revision)}}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[]);
  async function reload(){const result=await api('/backups');setRecords(result.backups);setBase(result.revision);setConfirmed(false);return result;}
  async function run(restore=false){
    setBusy(true);onBusyChange(true);setError('');setMessage('');
    try{
      if(restore){const result=await post('/backups/'+encodeURIComponent(selected)+'/restore',{revision:base,confirmed});onRestored(result);}
      else{await post('/backups',{revision:base});await reload();setSelected('');setMessage('De extra back-up is gemaakt.');}
    }catch(e){setError(e.message);if([409,404].includes(e.status))await reload().catch(()=>{});}
    finally{setBusy(false);onBusyChange(false);}
  }
  const choice=records?.find(r=>r.id===selected);
  return <div className="modal-body backup-manager">
    <p>Iedere eerste dag van de maand wordt automatisch een back-up gemaakt. De zeven nieuwste blijven bewaard; daarna vervalt de oudste.</p>
    {error&&<div className="alert error" role="alert">{error}</div>}
    {message&&<div className="alert backup-success" role="status">{message}</div>}
    {records===null&&!error?<p className="waiting-message"><BrandSpinner decorative/> Back-ups laden…</p>:<>
      <h3>Wilt u een back-up terugzetten?</h3>
      <p>Herstel leveranciers, prijzen, categorieën, bedrijven, extra velden, prijshistorie en appinstellingen. Uw beheerderstoegang blijft behouden.</p>
      <label className="backup-choice" htmlFor="backup-choice">Beschikbare back-ups ({records?.length||0} van 7)<select id="backup-choice" disabled={busy||!records?.length} value={selected} onChange={e=>{setSelected(e.target.value);setConfirmed(false);setMessage('')}}><option value="">Kies een back-up…</option>{records?.map(r=><option key={r.id} value={r.id}>{date(r.created_at)} · {kinds[r.kind]||r.kind}</option>)}</select></label>
      {!records?.length&&<p className="muted">Er zijn nog geen back-ups. Maak hieronder direct een eerste exemplaar.</p>}
      {choice&&<div className="backup-confirm"><p><strong>{kinds[choice.kind]}</strong> van {date(choice.created_at)}.</p><p>Voor het herstel maken we automatisch een veiligheidskopie van de huidige gegevens.</p><label className="check-label"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/> Ik wil de huidige gegevens vervangen door deze back-up.</label></div>}
      <Button className="danger" disabled={busy||!choice||!confirmed} onClick={()=>run(true)}>{busy&&<BrandSpinner size={18} decorative/>} Gekozen back-up terugzetten</Button>
      <div className="backup-extra"><h3>Nu een extra back-up maken</h3><p>Bewaar direct de huidige gegevens. Dit exemplaar telt mee bij de zeven bewaarde back-ups.</p><Button className="primary" disabled={busy||records===null} onClick={()=>run(false)}>{busy&&<BrandSpinner size={18} decorative/>} Extra back-up maken</Button></div>
    </>}
  </div>
}
