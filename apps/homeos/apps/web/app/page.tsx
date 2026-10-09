'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

type Member={id:string;name:string;role:string;language:string};
type Zone={id:string;name:string;kind:string};
type Asset={id:string;name:string;asset_type:string;zone_id?:string|null;status:string;next_service?:string|null};
type Room={id:string;name:string;kind:string;zones:Zone[];assets:Asset[]};
type Floor={id:string;name:string;sort_order:number;kind:string;rooms:Room[]};
type Property={id:string;name:string;property_type:string;address_label:string;floors:Floor[]};
type SetupState={mode:'SETUP'|'OPERATIONAL';setup_completed:boolean;household:{id:string;name:string};property:Property|null;counts:Record<string,number>};
type Task={id:string;title:string;status:string;assignee_name?:string;room_name?:string;source:string};
type ChatMessage={who:'user'|'jarvis';text:string;intent?:string};
type MemoryEntity={id:string;type:string;name:string;location?:string|null;source?:string|null};
type MemoryOverview={entities:MemoryEntity[];counts:Record<string,number>;authoritative_source:string};
type VisualLocation={id:string;name:string;type:string};
type VisualFinding={id:string;label:string;description:string;confidence:number|null;media_id:string;model_version:string|null;frame_timestamp_ms:number|null;inspected_location:string;matched_legacy_asset_id:string|null;locations:VisualLocation[];observed_at:string};
type VisualReviewData={observations:VisualFinding[];assets:{id:string;name:string}[]};
type VisualDecision='REJECT'|'VERIFY_ONLY'|'REGISTER_ASSET'|'CONFIRM_LOCATION';
type VisualDraft={action:VisualDecision;name:string;asset:string;location:string;note:string;assetType:'appliance'|'furniture'|'fixture'|'equipment'|'other'};

const api=async(path:string,memberId?:string,init:RequestInit={})=>{
  const headers=new Headers(init.headers||{});if(memberId)headers.set('X-Member-Id',memberId);
  if(!(init.body instanceof FormData))headers.set('Content-Type','application/json');
  const res=await fetch(path,{...init,headers});if(!res.ok)throw new Error((await res.text())||`HTTP ${res.status}`);return res.json();
};

export default function Home(){
  const [members,setMembers]=useState<Member[]>([]);const [memberId,setMemberId]=useState('');const [state,setState]=useState<SetupState|null>(null);
  const [boot,setBoot]=useState({name:'My Home',owner_name:'Owner',maid_name:'Maid',cook_name:'Cook'});const [loading,setLoading]=useState(true);const [error,setError]=useState('');
  const current=useMemo(()=>members.find(x=>x.id===memberId),[members,memberId]);

  const refreshMembers=async()=>{const m:Member[]=await api('/api/demo-members');setMembers(m);if(m.length&&!memberId)setMemberId(m[0].id);return m};
  const refreshState=async(id=memberId)=>{if(!id)return;setState(await api('/api/setup-state',id));};
  useEffect(()=>{(async()=>{try{const m=await refreshMembers();if(m[0]){setMemberId(m[0].id);setState(await api('/api/setup-state',m[0].id));}}catch(e){setError(String(e))}finally{setLoading(false)}})()},[]);
  useEffect(()=>{if(memberId)refreshState(memberId).catch(e=>setError(String(e)))},[memberId]);

  const initialize=async(e:FormEvent)=>{e.preventDefault();setError('');try{await api('/api/setup',undefined,{method:'POST',body:JSON.stringify(boot)});const m=await refreshMembers();if(m[0]){setMemberId(m[0].id);setState(await api('/api/setup-state',m[0].id));}}catch(e){setError(String(e))}};
  if(loading)return <main className="center">Loading HomeOS…</main>;
  if(!members.length)return <main className="onboard"><section className="heroCard"><div className="eyebrow">HomeOS</div><h1>Meet your household JARVIS.</h1><p>First create the local household identities. The virtual house comes next.</p><form onSubmit={initialize} className="stack"><label>Home name<input value={boot.name} onChange={e=>setBoot({...boot,name:e.target.value})}/></label><div className="twocol"><label>Owner<input value={boot.owner_name} onChange={e=>setBoot({...boot,owner_name:e.target.value})}/></label><label>Maid<input value={boot.maid_name} onChange={e=>setBoot({...boot,maid_name:e.target.value})}/></label></div><label>Cook<input value={boot.cook_name} onChange={e=>setBoot({...boot,cook_name:e.target.value})}/></label><button className="primary">Initialize HomeOS</button>{error&&<div className="error">{error}</div>}</form></section><GlobalStyles/></main>;
  if(state?.mode==='SETUP')return <SetupWizard members={members} memberId={memberId} current={current} state={state} onIdentity={setMemberId} onRefresh={()=>refreshState()} error={error} setError={setError}/>;
  return <Operational members={members} memberId={memberId} current={current} state={state} onIdentity={setMemberId} onRefreshState={()=>refreshState()} error={error} setError={setError}/>;
}

function SetupWizard({members,memberId,current,state,onIdentity,onRefresh,error,setError}:{members:Member[];memberId:string;current?:Member;state:SetupState;onIdentity:(x:string)=>void;onRefresh:()=>Promise<void>;error:string;setError:(x:string)=>void}){
  const owner=members.find(m=>m.role==='owner');const [step,setStep]=useState(state.property?2:1);const [home,setHome]=useState({name:state.household.name||'My Home',property_type:'independent_house',address_label:''});
  const [floorCount,setFloorCount]=useState(4);const [extras,setExtras]=useState({terrace:true,parking:true,utility:true});const [room,setRoom]=useState({floor_id:'',name:'',kind:'bedroom'});
  const [zone,setZone]=useState({room_id:'',name:'',kind:'area'});const [asset,setAsset]=useState({room_id:'',zone_id:'',name:'',asset_type:'appliance',next_service:''});
  const [scope,setScope]=useState({member_id:'',floor_id:'',room_id:''});const property=state.property;const floors=property?.floors||[];const rooms=floors.flatMap(f=>f.rooms.map(r=>({...r,floorId:f.id,floorName:f.name})));
  const staff=members.filter(m=>m.role!=='owner');
  useEffect(()=>{if(owner&&memberId!==owner.id)onIdentity(owner.id)},[]);
  useEffect(()=>{if(floors[0]&&!room.floor_id)setRoom(r=>({...r,floor_id:floors[0].id}));if(rooms[0]&&!zone.room_id){setZone(z=>({...z,room_id:rooms[0].id}));setAsset(a=>({...a,room_id:rooms[0].id}))}if(staff[0]&&!scope.member_id)setScope(s=>({...s,member_id:staff[0].id}));},[state]);
  const act=async(fn:()=>Promise<any>)=>{setError('');try{await fn();await onRefresh()}catch(e){setError(String(e))}};
  const saveProperty=()=>act(async()=>{await api('/api/virtual-house/property',memberId,{method:'POST',body:JSON.stringify(home)});setStep(2)});
  const createStructure=()=>act(async()=>{let order=0;const names=['Ground Floor','First Floor','Second Floor','Third Floor','Fourth Floor','Fifth Floor','Sixth Floor','Seventh Floor'];for(let i=0;i<floorCount;i++)await api('/api/virtual-house/floors',memberId,{method:'POST',body:JSON.stringify({name:names[i]||`Floor ${i}`,sort_order:order++,kind:'floor'})});if(extras.terrace)await api('/api/virtual-house/floors',memberId,{method:'POST',body:JSON.stringify({name:'Terrace',sort_order:order++,kind:'terrace'})});if(extras.parking)await api('/api/virtual-house/floors',memberId,{method:'POST',body:JSON.stringify({name:'Parking',sort_order:order++,kind:'parking'})});if(extras.utility)await api('/api/virtual-house/floors',memberId,{method:'POST',body:JSON.stringify({name:'Utility Area',sort_order:order++,kind:'utility'})});setStep(3)});
  const addRoom=(e:FormEvent)=>{e.preventDefault();act(async()=>{await api('/api/rooms',memberId,{method:'POST',body:JSON.stringify({...room,floor:0})});setRoom({...room,name:''})})};
  const addZone=(e:FormEvent)=>{e.preventDefault();act(async()=>{await api('/api/virtual-house/zones',memberId,{method:'POST',body:JSON.stringify(zone)});setZone({...zone,name:''})})};
  const addAsset=(e:FormEvent)=>{e.preventDefault();act(async()=>{await api('/api/assets',memberId,{method:'POST',body:JSON.stringify({...asset,zone_id:asset.zone_id||null,next_service:asset.next_service||null})});setAsset({...asset,name:'',next_service:''})})};
  const addScope=(e:FormEvent)=>{e.preventDefault();act(async()=>{await api('/api/virtual-house/staff-scopes',memberId,{method:'POST',body:JSON.stringify({...scope,floor_id:scope.floor_id||null,room_id:scope.room_id||null})});})};
  const complete=()=>act(async()=>{await api('/api/setup/complete',memberId,{method:'POST',body:'{}'});await onRefresh()});
  return <main className="onboard wide"><section className="wizardHead"><div><div className="eyebrow">HomeOS · Virtual House</div><h1>Build the house JARVIS will manage.</h1><p>Tasks, maintenance and inspections will resolve against this digital twin.</p></div><div className="modeBadge">SETUP MODE</div></section>
    <section className="stepper">{['Property','Structure','Rooms','Zones & assets','Staff access','Review'].map((s,i)=><button key={s} onClick={()=>setStep(i+1)} className={step===i+1?'active':''}><span>{i+1}</span>{s}</button>)}</section>
    <section className="wizardGrid"><div className="wizardCard">
      {step===1&&<><h2>1. Property</h2><p className="muted">Create the top-level property record.</p><div className="stack"><label>House name<input value={home.name} onChange={e=>setHome({...home,name:e.target.value})}/></label><label>Property type<select value={home.property_type} onChange={e=>setHome({...home,property_type:e.target.value})}><option value="independent_house">Independent house</option><option value="apartment">Apartment</option><option value="villa">Villa</option></select></label><label>Address label (optional)<input placeholder="e.g. Meerut home" value={home.address_label} onChange={e=>setHome({...home,address_label:e.target.value})}/></label><button className="primary" onClick={saveProperty}>Save & continue</button></div></>}
      {step===2&&<><h2>2. Floors & spaces</h2>{floors.length?<><p className="ok">Structure already created: {floors.length} levels/spaces.</p><div className="chips">{floors.map(f=><span key={f.id}>{f.name}</span>)}</div><button className="primary" onClick={()=>setStep(3)}>Continue</button></>:<div className="stack"><label>Number of main floors<input type="number" min={1} max={8} value={floorCount} onChange={e=>setFloorCount(Number(e.target.value))}/></label><div className="checks"><label><input type="checkbox" checked={extras.terrace} onChange={e=>setExtras({...extras,terrace:e.target.checked})}/> Terrace</label><label><input type="checkbox" checked={extras.parking} onChange={e=>setExtras({...extras,parking:e.target.checked})}/> Parking</label><label><input type="checkbox" checked={extras.utility} onChange={e=>setExtras({...extras,utility:e.target.checked})}/> Utility area</label></div><button className="primary" onClick={createStructure}>Create structure</button></div>}</>}
      {step===3&&<><h2>3. Rooms</h2><p className="muted">Add real room names. JARVIS will use these names when resolving instructions.</p><form className="stack" onSubmit={addRoom}><label>Floor / space<select value={room.floor_id} onChange={e=>setRoom({...room,floor_id:e.target.value})}>{floors.map(f=><option value={f.id} key={f.id}>{f.name}</option>)}</select></label><div className="twocol"><label>Room name<input required placeholder="Guest Bedroom" value={room.name} onChange={e=>setRoom({...room,name:e.target.value})}/></label><label>Type<select value={room.kind} onChange={e=>setRoom({...room,kind:e.target.value})}>{['bedroom','bathroom','kitchen','living','dining','pooja','store','gym','balcony','other'].map(x=><option key={x}>{x}</option>)}</select></label></div><button className="secondary">+ Add room</button></form><div className="treeMini">{floors.map(f=><div key={f.id}><b>{f.name}</b>{f.rooms.length?f.rooms.map(r=><span key={r.id}>{r.name}</span>):<em>No rooms yet</em>}</div>)}</div><button className="primary" disabled={!rooms.length} onClick={()=>setStep(4)}>Continue</button></>}
      {step===4&&<><h2>4. Zones & assets</h2><p className="muted">Zones make a room more precise: sink, pantry, wardrobe, shower, TV wall, etc.</p><form className="stack subcard" onSubmit={addZone}><h3>Add zone</h3><label>Room<select value={zone.room_id} onChange={e=>setZone({...zone,room_id:e.target.value})}>{rooms.map(r=><option value={r.id} key={r.id}>{r.floorName} · {r.name}</option>)}</select></label><div className="twocol"><label>Zone name<input required placeholder="Sink" value={zone.name} onChange={e=>setZone({...zone,name:e.target.value})}/></label><label>Type<input value={zone.kind} onChange={e=>setZone({...zone,kind:e.target.value})}/></label></div><button className="secondary">+ Add zone</button></form><form className="stack subcard" onSubmit={addAsset}><h3>Add asset</h3><label>Room<select value={asset.room_id} onChange={e=>setAsset({...asset,room_id:e.target.value,zone_id:''})}>{rooms.map(r=><option value={r.id} key={r.id}>{r.floorName} · {r.name}</option>)}</select></label><label>Zone (optional)<select value={asset.zone_id} onChange={e=>setAsset({...asset,zone_id:e.target.value})}><option value="">No zone</option>{rooms.find(r=>r.id===asset.room_id)?.zones.map(z=><option key={z.id} value={z.id}>{z.name}</option>)}</select></label><div className="twocol"><label>Asset name<input required placeholder="Water purifier" value={asset.name} onChange={e=>setAsset({...asset,name:e.target.value})}/></label><label>Type<input value={asset.asset_type} onChange={e=>setAsset({...asset,asset_type:e.target.value})}/></label></div><label>Next service (optional)<input type="date" value={asset.next_service} onChange={e=>setAsset({...asset,next_service:e.target.value})}/></label><button className="secondary">+ Add asset</button></form><button className="primary" onClick={()=>setStep(5)}>Continue</button></>}
      {step===5&&<><h2>5. Staff access</h2><p className="muted">Limit where each staff member can receive assignments. No scope means unrestricted in this local MVP; once scopes exist, JARVIS enforces them.</p><form className="stack" onSubmit={addScope}><label>Staff<select value={scope.member_id} onChange={e=>setScope({...scope,member_id:e.target.value})}>{staff.map(s=><option key={s.id} value={s.id}>{s.name} · {s.role}</option>)}</select></label><label>Floor scope<select value={scope.floor_id} onChange={e=>setScope({...scope,floor_id:e.target.value,room_id:''})}><option value="">Select floor (optional)</option>{floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label><label>Specific room<select value={scope.room_id} onChange={e=>setScope({...scope,room_id:e.target.value})}><option value="">Whole selected floor / choose room</option>{rooms.filter(r=>!scope.floor_id||r.floorId===scope.floor_id).map(r=><option key={r.id} value={r.id}>{r.floorName} · {r.name}</option>)}</select></label><button className="secondary">+ Add access scope</button></form><button className="primary" onClick={()=>setStep(6)}>Continue</button></>}
      {step===6&&<><h2>6. Review</h2><div className="summary"><div><strong>{state.counts.floors}</strong><span>Floors / spaces</span></div><div><strong>{state.counts.rooms}</strong><span>Rooms</span></div><div><strong>{state.counts.zones}</strong><span>Zones</span></div><div><strong>{state.counts.assets}</strong><span>Assets</span></div><div><strong>{state.counts.staff_scopes}</strong><span>Staff scopes</span></div></div><div className="treeMini large">{floors.map(f=><div key={f.id}><b>{f.name}</b>{f.rooms.map(r=><span key={r.id}>{r.name}{r.assets.length?` · ${r.assets.length} assets`:''}</span>)}</div>)}</div><button className="primary big" onClick={complete}>Launch JARVIS</button><p className="muted">After launch, location-specific tasks can only resolve to rooms in this virtual house.</p></>}
      {error&&<div className="error">{error}</div>}
    </div><aside className="housePreview"><div className="previewTop"><span>Virtual House</span><b>{property?.name||'Not created'}</b></div>{property?<div className="houseTree">{floors.map(f=><div className="floorNode" key={f.id}><div className="floorTitle"><span>{f.kind==='terrace'?'☀':f.kind==='parking'?'P':f.kind==='utility'?'⚙':'⌂'}</span><b>{f.name}</b><small>{f.rooms.length} rooms</small></div>{f.rooms.map(r=><div className="roomNode" key={r.id}><span>{r.name}</span><small>{r.zones.length} zones · {r.assets.length} assets</small></div>)}</div>)}</div>:<div className="empty">Create the property to begin.</div>}{current?.role==='owner'&&<MemoryPanel memberId={memberId}/>}</aside></section><GlobalStyles/></main>
}

function Operational({members,memberId,current,state,onIdentity,onRefreshState,error,setError}:{members:Member[];memberId:string;current?:Member;state:SetupState|null;onIdentity:(x:string)=>void;onRefreshState:()=>Promise<void>;error:string;setError:(x:string)=>void}){
  const [tasks,setTasks]=useState<Task[]>([]);const [history,setHistory]=useState<ChatMessage[]>([]);const [text,setText]=useState('');const [busy,setBusy]=useState(false);const [analysisRevision,setAnalysisRevision]=useState(0);const property=state?.property;
  const load=async(id:string)=>{const [today,hist]=await Promise.all([api('/api/today',id),api('/api/chat/history',id)]);setTasks(today.tasks||[]);const h:ChatMessage[]=[];for(const m of hist){h.push({who:'user',text:m.text});h.push({who:'jarvis',text:m.reply,intent:m.intent})}setHistory(h)};
  useEffect(()=>{if(memberId)load(memberId).catch(e=>setError(String(e)))},[memberId]);
  const send=async(e?:FormEvent)=>{e?.preventDefault();const msg=text.trim();if(!msg||!memberId)return;setBusy(true);setError('');setText('');setHistory(h=>[...h,{who:'user',text:msg}]);try{const out=await api('/api/chat',memberId,{method:'POST',body:JSON.stringify({text:msg})});setHistory(h=>[...h,{who:'jarvis',text:out.reply,intent:out.intent}]);await load(memberId)}catch(e){setError(String(e))}finally{setBusy(false)}};
  const editHouse=async()=>{try{await api('/api/setup/reopen',memberId,{method:'POST',body:'{}'});await onRefreshState()}catch(e){setError(String(e))}};
  return <main className="shell"><section className="topbar"><div><div className="eyebrow">HomeOS</div><h1>JARVIS</h1><p>{property?.name} · household operating assistant</p></div><div className="topActions"><button className="ghost" onClick={editHouse} disabled={current?.role!=='owner'}>Edit virtual house</button><div className="identity"><label>Acting as</label><select value={memberId} onChange={e=>onIdentity(e.target.value)}>{members.map(m=><option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}</select></div></div></section><section className="grid"><div className="panel conversation"><div className="panelHead"><div><span className="statusDot"/>JARVIS is operational</div><span className="pill">{current?.role}</span></div><div className="quickRow">{(current?.role==='owner'?['How many rooms do we have?','Aaj ghar mein kya pending hai?','Maid ko Kitchen saaf karwa do']:['Aaj kya kaam hai?','Kaam kaise karna hai?','Kitchen ho gaya']).map(q=><button key={q} onClick={()=>setText(q)}>{q}</button>)}</div><div className="messages">{history.length===0&&<div className="welcome"><strong>Virtual house ready.</strong><br/>I answer from your configured virtual house, tasks, staff, assets and open issues, and I preserve recent conversation context.</div>}{history.map((m,i)=><div key={i} className={`bubble ${m.who}`}><div>{m.text}</div>{m.intent&&<small>{m.intent.replaceAll('_',' ')}</small>}</div>)}</div><form className="composer" onSubmit={send}><input value={text} onChange={e=>setText(e.target.value)} placeholder={current?.role==='owner'?'Tell JARVIS what needs to happen…':'Hindi, English ya Hinglish mein baat karein…'}/><button disabled={busy}>{busy?'…':'Send'}</button></form>{error&&<div className="error">{error}</div>}</div><aside className="rightRail"><div className="panel today"><div className="panelHead"><strong>Today</strong><span className="count">{tasks.length}</span></div><div className="taskList">{tasks.length===0&&<div className="empty">No pending tasks.</div>}{tasks.map(t=><div className="task" key={t.id}><div className="taskTop"><span>{t.title}</span><span className="state">{t.status.replaceAll('_',' ')}</span></div><div className="meta">{t.assignee_name&&<span>{t.assignee_name}</span>}{t.room_name&&<span>{t.room_name}</span>}<span>{t.source}</span></div></div>)}</div></div>{current?.role==='owner'&&<div className="panel miniHouse"><div className="panelHead"><strong>Virtual house</strong><span className="count">{state?.counts.rooms||0}</span></div><div className="miniTree">{property?.floors.map(f=><div key={f.id}><b>{f.name}</b><span>{f.rooms.map(r=>r.name).join(' · ')||'No rooms'}</span></div>)}</div></div>}{current?.role==='owner'&&<><MemoryPanel memberId={memberId}/><PhotoInspectionPanel memberId={memberId} onAnalyzed={()=>setAnalysisRevision(n=>n+1)}/><VisualReviewPanel memberId={memberId} revision={analysisRevision}/></>}</aside></section><GlobalStyles/></main>
}


function MemoryPanel({memberId}:{memberId:string}){
  const [state,setState]=useState<MemoryOverview|null>(null);
  const [message,setMessage]=useState('Memory graph is not yet synchronized.');
  const [busy,setBusy]=useState(false);
  const load=async()=>{try{const value:MemoryOverview=await api('/api/memory/overview',memberId);setState(value);setMessage('');}catch{setState(null);setMessage('Memory unavailable. Configure Home Memory and apply its migrations first.')}};
  useEffect(()=>{load()},[memberId]);
  const synchronize=async()=>{
    setBusy(true);setMessage('');
    try{const result=await api('/api/memory/sync',memberId,{method:'POST',body:'{}'});
        setMessage(`Synchronized ${result.counts.created||0} new and ${result.counts.updated||0} existing entities.`);
        const next:MemoryOverview=await api('/api/memory/overview',memberId);setState(next);
    }catch(e){setMessage('Sync failed: '+String(e));}finally{setBusy(false)}
  };
  return <div className="panel miniHouse"><div className="panelHead"><strong>Home Memory</strong><span className="pill">Verified graph</span></div>
    <div className="memoryContent"><p className="muted">Linked to the existing virtual house. Sync never deletes your operational records.</p>
      <button className="secondary" disabled={busy} onClick={synchronize}>{busy?'Synchronizing…':'Sync virtual house'}</button>
      {message&&<p className="memoryNote" role="status">{message}</p>}
      {state&&<><p className="memoryNote">{state.entities.length} registered entities: {Object.entries(state.counts).map(([k,v])=>`${k}: ${v}`).join(' · ')}</p>
      <div className="memoryList">{state.entities.slice(0,24).map(x=><div key={x.id}><b>{x.name}</b><small>{x.type} · {x.location||'No verified location'} · {x.source||'M2C source'}</small></div>)}</div></>}
    </div></div>;
}


function EvidencePreview({memberId,observationId}:{memberId:string;observationId:string}){
  const [open,setOpen]=useState(false),[url,setUrl]=useState(''),[kind,setKind]=useState('');
  const [error,setError]=useState('');
  useEffect(()=>{
    if(!open)return;
    let active=true;let objectUrl='';
    const controller=new AbortController();
    (async()=>{
      try{
        setError('');
        const response=await fetch('/api/memory/visual/'+observationId+'/evidence',
          {headers:{'X-Member-Id':memberId},signal:controller.signal,cache:'no-store'});
        if(!response.ok)throw new Error('Evidence unavailable (HTTP '+response.status+').');
        const blob=await response.blob();
        if(!active)return;
        objectUrl=URL.createObjectURL(blob);
        setKind(blob.type);
        setUrl(objectUrl);
      }catch(e){if(active)setError(String(e));}
    })();
    return ()=>{active=false;controller.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);setUrl('')};
  },[open,memberId,observationId]);
  return <div className="visualEvidence">
    <button className="ghost" type="button" onClick={()=>setOpen(v=>!v)}>{open?'Hide evidence':'View original evidence'}</button>
    {open&&<div className="visualEvidenceBody">{error&&<p className="memoryNote">{error}</p>}
      {url&&(kind.startsWith('image/')?<img alt="Original inspection evidence — verify before deciding" src={url} />:
        <video controls preload="metadata" src={url} aria-label="Original inspection video"/>)}
      {!url&&!error&&<p className="memoryNote">Loading private evidence…</p>}
    </div>}
  </div>;
}


type UploadedInspection={session_id:string;media_id:string;location:string;bytes:number;status:string};
function PhotoInspectionPanel({memberId,onAnalyzed}:{memberId:string;onAnalyzed:()=>void}){
  const [locations,setLocations]=useState<VisualLocation[]>([]);
  const [locationId,setLocationId]=useState(''),[file,setFile]=useState<File|null>(null);
  const [uploaded,setUploaded]=useState<UploadedInspection|null>(null);
  const [consent,setConsent]=useState(false),[loading,setLoading]=useState(false),[analyzing,setAnalyzing]=useState(false);
  const [message,setMessage]=useState(''),[error,setError]=useState('');
  const load=async()=>{
    try{
      const result:{locations:VisualLocation[]}=await api('/api/memory/visual/inspection-locations',memberId);
      setLocations(result.locations);
      setLocationId(v=>result.locations.some(loc=>loc.id===v)?v:(result.locations[0]?.id||''));
      setError('');
    }catch(e){setLocations([]);setError('Photo inspections unavailable: '+String(e))}
  };
  useEffect(()=>{if(memberId){setFile(null);setUploaded(null);setConsent(false);void load()}},[memberId]);
  const upload=async()=>{
    if(!file||!locationId){setError('Choose a registered room and JPEG, PNG or WebP photo.');return}
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>15*1024*1024){
      setError('Only JPEG, PNG or WebP photos up to 15 MiB are supported.');return;
    }
    setLoading(true);setError('');setMessage('');
    try{
      const data=new FormData();
      data.append('file',file);data.append('location_entity_id',locationId);
      const result:UploadedInspection=await api('/api/memory/visual/inspection-upload',memberId,
        {method:'POST',body:data});
      setUploaded(result);setConsent(false);
      setMessage('Photo uploaded privately. It has NOT been sent to AI.');
    }catch(e){setError('Upload failed: '+String(e))}
    finally{setLoading(false)}
  };
  const analyze=async()=>{
    if(!uploaded||!consent){setError('Explicitly consent before requesting external AI analysis.');return}
    setAnalyzing(true);setError('');setMessage('');
    try{
      const result:{summary?:{observations?:number};status:string}=await api('/api/memory/visual/inspection-analyze',
        memberId,{method:'POST',body:JSON.stringify({
          session_id:uploaded.session_id,media_id:uploaded.media_id,
          consent_to_external_ai_processing:true
        })});
      const count=result.summary?.observations??0;
      setMessage('Analysis completed: '+count+' proposed observations. Review and verify findings below.');
      onAnalyzed();
    }catch(e){
      setError('Analysis failed (photo remains privately uploaded): '+String(e));
    }finally{setAnalyzing(false)}
  };
  return <section className="panel inspectionPanel">
    <div className="panelHead"><strong>Inspect a room</strong><span className="pill">Owner</span></div>
    <div className="memoryContent">
      <p className="muted">Upload a photo first. AI recognition starts only after separate consent. No detected item is added automatically.</p>
      <button type="button" className="ghost inspectionRefresh" disabled={loading||analyzing} onClick={load}>Refresh rooms</button>
      <label>Inspected room or area
        <select value={locationId} disabled={loading||analyzing||!!uploaded} onChange={e=>setLocationId(e.target.value)}>
          {locations.length===0&&<option value="">Synchronize the virtual house first</option>}
          {locations.map(loc=><option key={loc.id} value={loc.id}>{loc.name} ({loc.type})</option>)}
        </select>
      </label>
      <label>Room photo
        <input type="file" accept="image/jpeg,image/png,image/webp" disabled={loading||analyzing||!!uploaded}
          onChange={e=>{setFile(e.target.files?.[0]||null);setMessage('');setError('');}}/>
      </label>
      {file&&<p className="memoryNote">Selected: {file.name} · {(file.size/1024/1024).toFixed(1)} MiB</p>}
      {!uploaded&&<button className="secondary" type="button" disabled={!file||!locationId||loading||analyzing} onClick={upload}>
        {loading?'Uploading privately…':'1. Upload privately'}
      </button>}
      {uploaded&&<>
        <p className="memoryNote">Saved in {uploaded.location}. No external AI processing has occurred yet.</p>
        <label className="inspectionConsent">
          <input type="checkbox" checked={consent} disabled={analyzing} onChange={e=>setConsent(e.target.checked)}/>
          <span>I agree to send this household photo to the configured external AI provider (OpenAI) for object recognition.</span>
        </label>
        <button className="primary" type="button" disabled={!consent||analyzing} onClick={analyze}>
          {analyzing?'Analyzing photo…':'2. Analyze with AI'}
        </button>
        <button className="ghost" type="button" disabled={analyzing} onClick={()=>{setUploaded(null);setFile(null);setConsent(false);setError('');setMessage('')}}>
          Start another inspection
        </button>
      </>}
      {error&&<p role="alert" className="error">{error}</p>}
      {message&&<p role="status" className="memoryNote">{message}</p>}
    </div>
  </section>;
}

function VisualReviewPanel({memberId,revision=0}:{memberId:string;revision?:number}){
  const [data,setData]=useState<VisualReviewData|null>(null);
  const [drafts,setDrafts]=useState<Record<string,VisualDraft>>({});
  const [error,setError]=useState(''),[busy,setBusy]=useState(''),[loading,setLoading]=useState(false);
  const load=async()=>{
    setLoading(true);try{
      const result:VisualReviewData=await api('/api/memory/visual/pending',memberId);
      setData(result);setError('');
    }catch(e){setData(null);setError('Visual review unavailable: '+String(e));}
    finally{setLoading(false)}
  };
  useEffect(()=>{if(memberId)void load()},[memberId,revision]);
  const empty:VisualDraft={action:'VERIFY_ONLY',name:'',asset:'',location:'',note:'',assetType:'appliance'};
  const update=(id:string,change:Partial<VisualDraft>)=>setDrafts(x=>({...x,[id]:{...(x[id]||empty),...change}}));
  const submit=async(item:VisualFinding,decision:VisualDecision)=>{
    const d=drafts[item.id]||empty;
    if(decision==='REGISTER_ASSET'&&d.name.trim().length<2){
      setError('Enter the verified asset name before registering it.');return;
    }
    if((decision==='REGISTER_ASSET'||decision==='CONFIRM_LOCATION')&&!d.location){
      setError('Select the room or zone seen in the inspection.');return;
    }
    if(decision==='CONFIRM_LOCATION'&&!d.asset){
      setError('Select the existing asset to verify or move.');return;
    }
    setBusy(item.id);setError('');
    try{
      await api('/api/memory/visual/'+item.id+'/resolve',memberId,{
        method:'POST',body:JSON.stringify({
          decision,corrected_name:d.name.trim()||null,location_entity_id:d.location||null,
          asset_id:d.asset||null,note:d.note,asset_type:d.assetType
        })
      });
      await load();
    }catch(e){setError('Review failed: '+String(e))}
    finally{setBusy('')}
  };
  return <div className="panel visualReview">
    <div className="panelHead"><strong>Visual review</strong><span className="count">{data?.observations.length??'—'} pending</span></div>
    <div className="memoryContent">
      <p className="muted">AI findings are suggestions. Inspect evidence before approving a household change.</p>
      <button type="button" className="secondary" disabled={loading||!!busy} onClick={load}>{loading?'Refreshing…':'Refresh findings'}</button>
      {error&&<p role="alert" className="error">{error}</p>}
      {data?.observations.length===0&&<p className="memoryNote">No pending visual observations. Analyze a photo or video in an inspection session to create proposals.</p>}
      {data?.observations.map(item=>{
        const d=drafts[item.id]||empty;
        return <article className="visualCard" key={item.id}>
          <strong>{item.label}</strong>
          <small>{item.inspected_location} · {item.confidence==null?'Confidence not supplied':Math.round(item.confidence*100)+'% model score'}</small>
          {item.description&&<p>{item.description}</p>}
          <small>Model: {item.model_version||'Unknown'} · Frame: {item.frame_timestamp_ms==null?'—':(item.frame_timestamp_ms/1000)+'s'}</small>
          <EvidencePreview memberId={memberId} observationId={item.id}/>
          {item.matched_legacy_asset_id&&<p className="memoryNote">Existing asset suggested by graph matching; verify the match yourself.</p>}
          <label>Review action
            <select value={d.action} onChange={e=>update(item.id,{action:e.target.value as VisualDecision})}>
              <option value="VERIFY_ONLY">Accept evidence only (no asset change)</option>
              <option value="REGISTER_ASSET">Register a new asset</option>
              <option value="CONFIRM_LOCATION">Confirm or correct existing asset location</option>
            </select>
          </label>
          {d.action==='REGISTER_ASSET'&&<label>Verified asset name
            <input value={d.name} placeholder="Type the correct object name" maxLength={120} onChange={e=>update(item.id,{name:e.target.value})}/>
          </label>}
          {d.action==='REGISTER_ASSET'&&<label>Asset category
            <select value={d.assetType} onChange={e=>update(item.id,{assetType:e.target.value as VisualDraft['assetType']})}>
              <option value="appliance">Appliance</option><option value="furniture">Furniture</option>
              <option value="fixture">Fixture</option><option value="equipment">Equipment</option>
              <option value="other">Other</option>
            </select>
          </label>}
          {d.action==='CONFIRM_LOCATION'&&<label>Registered asset
            <select value={d.asset} onChange={e=>update(item.id,{asset:e.target.value})}>
              <option value="">Select the correct asset</option>
              {data.assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>}
          {(d.action==='REGISTER_ASSET'||d.action==='CONFIRM_LOCATION')&&<label>Verified inspection location
            <select value={d.location} onChange={e=>update(item.id,{location:e.target.value})}>
              <option value="">Select room or zone</option>
              {item.locations.map(loc=><option key={loc.id} value={loc.id}>{loc.name} ({loc.type})</option>)}
            </select>
          </label>}
          <label>Owner note (optional)
            <input value={d.note} maxLength={600} placeholder="What did you verify or correct?" onChange={e=>update(item.id,{note:e.target.value})}/>
          </label>
          <div className="visualActions">
            <button type="button" className="ghost" disabled={!!busy} onClick={()=>submit(item,'REJECT')}>Reject</button>
            <button type="button" className="primary" disabled={!!busy} onClick={()=>submit(item,d.action)}>
              {busy===item.id?'Saving…':'Confirm review'}
            </button>
          </div>
        </article>
      })}
    </div>
  </div>;
}

function GlobalStyles(){return <style jsx global>{`
*{box-sizing:border-box}body{margin:0;background:#eef4f1;color:#12352c;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,select{font:inherit}.center{min-height:100vh;display:grid;place-items:center}.onboard{min-height:100vh;padding:40px;max-width:1180px;margin:auto}.onboard.wide{max-width:1450px}.heroCard,.wizardCard,.housePreview,.panel{background:white;border:1px solid #dce8e2;border-radius:20px;box-shadow:0 8px 30px rgba(18,53,44,.05)}.heroCard{max-width:720px;margin:8vh auto;padding:38px}.eyebrow{text-transform:uppercase;letter-spacing:.18em;font-size:12px;font-weight:800;color:#628278}.heroCard h1,.wizardHead h1,.topbar h1{font-size:38px;margin:7px 0}.heroCard p,.wizardHead p,.topbar p,.muted{color:#61786f}.stack{display:flex;flex-direction:column;gap:14px;margin-top:22px}.twocol{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{font-size:13px;font-weight:700;display:flex;flex-direction:column;gap:7px}input,select{width:100%;padding:12px 13px;border:1px solid #cfe0d8;border-radius:11px;background:white;color:#12352c;outline:none}input:focus,select:focus{border-color:#145441;box-shadow:0 0 0 3px rgba(20,84,65,.08)}button{cursor:pointer}.primary,.secondary,.ghost{border:0;border-radius:11px;padding:12px 16px;font-weight:800}.primary{background:#145441;color:white}.primary:disabled{opacity:.4}.primary.big{padding:15px 20px;font-size:16px}.secondary{background:#e9f3ee;color:#145441;border:1px solid #cfe0d8}.ghost{background:white;color:#315c50;border:1px solid #d8e6df}.error{margin-top:14px;padding:11px 13px;background:#fff0f0;color:#9d3030;border-radius:10px;font-size:13px}.wizardHead{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.modeBadge{background:#dff1e8;color:#145441;padding:9px 12px;border-radius:999px;font-size:12px;font-weight:900}.stepper{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:18px}.stepper button{border:1px solid #dce8e2;background:#f8fbfa;color:#61786f;border-radius:12px;padding:10px 8px;font-size:12px;font-weight:700}.stepper button span{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:50%;background:#e7efeb;margin-right:6px}.stepper button.active{background:#145441;color:white}.stepper button.active span{background:white;color:#145441}.wizardGrid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.75fr);gap:18px}.wizardCard{padding:26px;min-height:620px}.wizardCard h2{margin-top:0;font-size:26px}.subcard{border:1px solid #e0ebe6;border-radius:14px;padding:16px}.subcard h3{margin:0}.checks{display:flex;gap:18px;flex-wrap:wrap}.checks label{display:flex;flex-direction:row;align-items:center}.checks input{width:auto}.chips{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.chips span{background:#eef5f1;border-radius:999px;padding:7px 10px;font-size:12px}.ok{background:#e8f5ed;padding:12px;border-radius:10px}.housePreview{overflow:hidden;align-self:start;position:sticky;top:20px}.previewTop{padding:18px;border-bottom:1px solid #e8efec;display:flex;justify-content:space-between}.houseTree{padding:12px}.floorNode{border:1px solid #e0ebe6;border-radius:13px;margin:9px 0;overflow:hidden}.floorTitle{display:grid;grid-template-columns:28px 1fr auto;align-items:center;padding:11px;background:#f4f8f6}.floorTitle small,.roomNode small{color:#6b8279}.roomNode{display:flex;justify-content:space-between;padding:9px 12px 9px 40px;border-top:1px solid #edf3f0;font-size:13px}.treeMini{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0}.treeMini>div{border:1px solid #e0ebe6;border-radius:12px;padding:12px}.treeMini b{display:block;margin-bottom:7px}.treeMini span,.treeMini em{display:block;font-size:12px;color:#61786f;padding:2px 0}.treeMini.large{grid-template-columns:repeat(3,1fr)}.summary{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:20px 0}.summary div{padding:15px;background:#f2f7f4;border-radius:12px}.summary strong{display:block;font-size:25px}.summary span{font-size:11px;color:#61786f}.shell{max-width:1440px;margin:auto;padding:28px}.topbar{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}.topActions{display:flex;gap:10px;align-items:center}.identity{display:flex;gap:10px;align-items:center;background:#fff;padding:10px 12px;border:1px solid #dce8e2;border-radius:14px}.identity label{display:block;color:#61786f}.identity select{border:0;padding:0;background:transparent;font-weight:700}.grid{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(320px,.75fr);gap:18px;min-height:calc(100vh - 150px)}.conversation{display:flex;flex-direction:column;overflow:hidden}.panelHead{height:58px;padding:0 20px;border-bottom:1px solid #edf3f0;display:flex;align-items:center;justify-content:space-between}.statusDot{display:inline-block;width:8px;height:8px;background:#2f9e72;border-radius:50%;margin-right:9px}.pill,.count{font-size:12px;font-weight:800;background:#e8f4ee;padding:6px 9px;border-radius:999px}.quickRow{display:flex;gap:8px;overflow:auto;padding:12px 18px;border-bottom:1px solid #edf3f0}.quickRow button{white-space:nowrap;border:1px solid #d8e6df;background:#f8fbfa;border-radius:999px;padding:8px 12px;color:#315c50}.messages{flex:1;padding:22px;overflow:auto;min-height:420px;max-height:62vh}.welcome{background:#f1f7f4;border:1px solid #deebe5;border-radius:16px;padding:18px;max-width:540px;line-height:1.55}.bubble{max-width:75%;padding:12px 14px;border-radius:16px;margin:9px 0;line-height:1.45}.bubble.user{margin-left:auto;background:#145441;color:white}.bubble.jarvis{background:#f0f5f2;border:1px solid #dbe8e1}.bubble small{display:block;margin-top:6px;opacity:.65;font-size:10px}.composer{display:flex;gap:10px;padding:16px;border-top:1px solid #edf3f0}.composer input{flex:1}.composer button{border:0;background:#145441;color:white;border-radius:12px;padding:0 22px;font-weight:800}.rightRail{display:flex;flex-direction:column;gap:18px}.taskList{padding:14px;display:flex;flex-direction:column;gap:10px}.task{border:1px solid #e0ebe6;border-radius:14px;padding:13px}.taskTop{display:flex;justify-content:space-between;gap:10px;font-weight:700}.state{font-size:10px;padding:5px 7px;border-radius:999px;background:#edf3f0}.meta{display:flex;gap:8px;margin-top:8px;font-size:11px;color:#698078}.empty{padding:18px;color:#6b8279;text-align:center}.miniTree{padding:12px}.miniTree>div{padding:10px;border-bottom:1px solid #edf3f0}.miniTree b,.miniTree span{display:block}.miniTree span{font-size:11px;color:#698078;margin-top:4px}.memoryContent{padding:14px}.memoryContent .secondary{width:100%}.memoryNote{font-size:12px;color:#547468;line-height:1.45}.memoryList{max-height:280px;overflow:auto;margin-top:10px}.memoryList>div{padding:8px 0;border-bottom:1px solid #edf3f0}.memoryList b,.memoryList small{display:block}.memoryList small{font-size:11px;color:#698078;margin-top:4px}.inspectionPanel .memoryContent{display:flex;flex-direction:column;gap:10px}.inspectionPanel .memoryContent>p{margin:0;font-size:12px}.inspectionPanel label{font-size:12px}.inspectionPanel .inspectionRefresh{align-self:flex-end;font-size:11px;padding:7px 10px}.inspectionPanel .inspectionConsent{flex-direction:row;align-items:start;gap:9px;font-weight:500;line-height:1.4}.inspectionPanel .inspectionConsent input{width:auto;margin-top:2px;flex:none}.inspectionPanel .memoryContent>.primary,.inspectionPanel .memoryContent>.secondary{width:100%}.inspectionPanel .memoryContent>.ghost:last-of-type{font-size:12px}.visualReview .memoryContent>.secondary{margin-bottom:12px}.visualCard{border:1px solid #deebe4;border-radius:14px;margin:12px 0;padding:12px;display:flex;flex-direction:column;gap:9px}.visualCard>small{font-size:11px;color:#647f74}.visualCard p{font-size:12px;line-height:1.5;margin:2px 0}.visualCard label{font-size:12px}.visualCard select,.visualCard input{padding:9px}.visualEvidence .ghost{padding:8px 10px;font-size:12px}.visualEvidenceBody img,.visualEvidenceBody video{width:100%;max-height:280px;object-fit:contain;border-radius:10px;background:#ecf1ed}.visualActions{display:flex;gap:8px}.visualActions button{flex:1;padding:9px}.visualReview .error{word-break:break-word}@media(max-width:900px){.onboard,.shell{padding:16px}.wizardHead,.topbar{align-items:flex-start;flex-direction:column;gap:12px}.stepper{grid-template-columns:repeat(3,1fr)}.wizardGrid,.grid{grid-template-columns:1fr}.housePreview{position:static}.treeMini.large,.summary{grid-template-columns:repeat(2,1fr)}.topActions{width:100%;flex-wrap:wrap}.identity{flex:1}.twocol{grid-template-columns:1fr}.messages{min-height:360px}.bubble{max-width:88%}}
`}</style>}
