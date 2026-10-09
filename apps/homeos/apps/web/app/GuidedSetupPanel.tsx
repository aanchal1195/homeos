'use client';

import {useEffect,useRef,useState} from 'react';

type Kind='FLOORPLAN'|'ROOM_PHOTO'|'ROOM_VIDEO';
type Suggestion={
  id:string;kind:'FLOOR'|'ROOM'|'ASSET';name:string;floor_hint:string;
  room_hint:string;room_kind:string;asset_type:string;evidence_summary:string;
  status:'PENDING'|'ACCEPTED'|'REJECTED';applied_id:string|null;
};
type GuidedEvidence={
  id:string;media_kind:Kind;room_id:string|null;floor_hint:string;room_hint:string;
  content_type:string;bytes:number;status:string;consent_recorded:boolean;
  pending_count:number;suggestions:Suggestion[];
  notes:{unresolved?:string[];suggested_next_capture?:string};
};
type Advice={step:string;room_id:string|null;question:string;reason:string;source:string};
type Status={
  evidence:GuidedEvidence[];guidance:Advice;provider_configured:boolean;
  counts:{floors:number;rooms:number;media:number;pending_review:number};
};
type Place={id:string;name:string};
type Floor={id:string;name:string;rooms:Place[]};
type Draft={name:string;floor_id:string;room_id:string};

const jsonRequest=async<T,>(path:string,memberId:string,init:RequestInit={}):Promise<T>=>{
  const headers=new Headers(init.headers);
  headers.set('X-Member-Id',memberId);
  if(!(init.body instanceof FormData))headers.set('Content-Type','application/json');
  const res=await fetch(path,{...init,headers,cache:'no-store'});
  if(!res.ok){
    const detail=await res.text();
    throw new Error(detail.slice(0,260)||`Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
};

const labels:Record<Kind,string>={
  FLOORPLAN:'Floor plan photo',ROOM_PHOTO:'Room photographs',ROOM_VIDEO:'Room walkthrough video'
};

export default function GuidedSetupPanel({memberId,floors,onUpdated}:{
  memberId:string;floors:Floor[];onUpdated:()=>Promise<void>|void;
}){
  const [data,setData]=useState<Status|null>(null);
  const [kind,setKind]=useState<Kind>('FLOORPLAN');
  const [roomId,setRoomId]=useState('');
  const [floorHint,setFloorHint]=useState('');
  const [roomHint,setRoomHint]=useState('');
  const [file,setFile]=useState<File|null>(null);
  const [aiConsent,setAiConsent]=useState(false);
  const [plannerConsent,setPlannerConsent]=useState(false);
  const [guidance,setGuidance]=useState<Advice|null>(null);
  const [drafts,setDrafts]=useState<Record<string,Draft>>({});
  const [preview,setPreview]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const inputRef=useRef<HTMLInputElement>(null);
  const previewUrls=useRef<string[]>([]);
  const rooms=floors.flatMap(f=>f.rooms.map(r=>({...r,floorName:f.name})));
  const load=async()=>{
    const result=await jsonRequest<Status>('/api/guided/status',memberId);
    setData(result);
    setGuidance(result.guidance);
  };
  useEffect(()=>{
    if(memberId)void load().catch(e=>setError(String(e)));
  },[memberId]);
  useEffect(()=>()=>{previewUrls.current.forEach(url=>URL.revokeObjectURL(url))},[]);

  const run=async(operation:()=>Promise<void>)=>{
    setBusy(true);setError('');setNotice('');
    try{await operation()}catch(e){setError(String(e))}
    finally{setBusy(false)}
  };
  const upload=()=>run(async()=>{
    if(!file)throw new Error('Choose a photograph or a short video first.');
    const body=new FormData();
    body.set('file',file);
    body.set('media_kind',kind);
    body.set('room_id',roomId);
    body.set('floor_hint',floorHint);
    body.set('room_hint',roomHint);
    const response=await jsonRequest<{evidence:GuidedEvidence;message:string}>(
      '/api/guided/upload',memberId,{method:'POST',body});
    setFile(null);if(inputRef.current)inputRef.current.value='';
    setAiConsent(false);setNotice(response.message);
    await load();
  });
  const analyze=(evidence:GuidedEvidence)=>run(async()=>{
    if(!aiConsent)throw new Error('Consent is required for this specific external AI analysis.');
    await jsonRequest('/api/guided/analyze',memberId,{
      method:'POST',body:JSON.stringify({
        evidence_id:evidence.id,consent_to_external_ai_processing:true
      })});
    setNotice('New findings are suggestions only. Review and correct before applying.');
    setAiConsent(false);await load();
  });
  const next=()=>run(async()=>{
    const result=await jsonRequest<{guidance:Advice}>('/api/guided/next',memberId,{
      method:'POST',body:JSON.stringify({
        consent_to_external_ai_processing:plannerConsent
      })});
    setGuidance(result.guidance);
    setPlannerConsent(false);
    setNotice(result.guidance.source==='AI_GUIDED'?
      'AI selected a next question from recorded coverage. Nothing was changed.':
      'Next step uses the local coverage rules. No household data was sent to AI.');
  });
  const resolve=(evidence:GuidedEvidence,suggestion:Suggestion,decision:'ACCEPT'|'REJECT')=>
    run(async()=>{
      const choice=drafts[suggestion.id];
      await jsonRequest(`/api/guided/evidence/${evidence.id}/decide`,memberId,{
        method:'POST',body:JSON.stringify({
          suggestion_id:suggestion.id,decision,
          corrected_name:choice?.name||suggestion.name,
          floor_id:choice?.floor_id||null,
          room_id:choice?.room_id||null
        })
      });
      setNotice(decision==='ACCEPT'?
        `${choice?.name||suggestion.name} confirmed in the virtual house.`:
        'Rejected. No household fact was created.');
      await onUpdated();
      await load();
    });
  const showMedia=(item:GuidedEvidence)=>run(async()=>{
    if(preview[item.id]){
      setPreview(old=>{const next={...old};delete next[item.id];return next});
      return;
    }
    const res=await fetch(`/api/guided/evidence/${item.id}/media`,{
      headers:{'X-Member-Id':memberId},cache:'no-store'
    });
    if(!res.ok)throw new Error('Private preview could not be loaded.');
    const url=URL.createObjectURL(await res.blob());
    previewUrls.current.push(url);
    setPreview(old=>({...old,[item.id]:url}));
  });
  const setDraft=(id:string,patch:Partial<Draft>,suggestion:Suggestion)=>{
    setDrafts(old=>({...old,[id]:{
      ...(old[id]||{name:suggestion.name,floor_id:'',room_id:''}),...patch
    }}));
  };
  const acceptTypes='image/jpeg,image/png,image/webp';
  return <section className="guidedSetup" aria-label="AI guided home setup">
    <div className="guidedHeading"><div><strong>JARVIS · Guided home discovery</strong>
      <p>Show me the house. I will decide what evidence is missing, then ask one question at a time.</p>
    </div><span className="guidedBadge">Owner-reviewed memory</span></div>
    <p className="guidedNote">Start with a floor-plan photo if you have one—or skip it. Add a room photo or a video walkthrough even before rooms are registered. Nothing is added to the household until you approve it.</p>
    <div className="guidedProgress">
      <span><b>{data?.counts.floors??0}</b> floors</span>
      <span><b>{data?.counts.rooms??0}</b> rooms</span>
      <span><b>{data?.counts.media??0}</b> media</span>
      <span><b>{data?.counts.pending_review??0}</b> awaiting review</span>
    </div>
    <section className="guidedAdvice" aria-live="polite">
      <div className="guidedSubhead">What JARVIS needs next · {guidance?.source==='AI_GUIDED'?'AI-guided': 'Local guidance'}</div>
      <b>{guidance?.question||'Checking evidence coverage…'}</b>
      <p>{guidance?.reason}</p>
      <label className="guidedCheck"><input type="checkbox" checked={plannerConsent}
        disabled={!data?.provider_configured} onChange={e=>setPlannerConsent(e.target.checked)}/>
        Allow external AI to examine room names and coverage metadata for this next-step decision
      </label>
      <button className="guidedSecondary" disabled={busy} type="button" onClick={next}>
        Decide the next useful step
      </button>
    </section>

    <div className="guidedCapture">
      <h3>1 · Provide evidence</h3>
      <label>What are you showing JARVIS?
        <select value={kind} onChange={e=>{setKind(e.target.value as Kind);setFile(null);
          if(inputRef.current)inputRef.current.value=''}}>
          {Object.entries(labels).map(([value,label])=><option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {kind!=='FLOORPLAN'&&<label>Already registered room (optional)
        <select value={roomId} onChange={e=>setRoomId(e.target.value)}>
          <option value="">Not registered yet — describe below</option>
          {rooms.map(r=><option value={r.id} key={r.id}>{r.floorName} · {r.name}</option>)}
        </select>
      </label>}
      <div className="guidedTwo">
        <label>Floor / level name (optional)<input value={floorHint}
          placeholder="e.g. Ground Floor" maxLength={100}
          onChange={e=>setFloorHint(e.target.value)}/></label>
        {kind!=='FLOORPLAN'&&<label>Room label (optional)<input value={roomHint}
          placeholder="e.g. Guest Bedroom" maxLength={100}
          onChange={e=>setRoomHint(e.target.value)}/></label>}
      </div>
      <label>Private {kind==='ROOM_VIDEO'?'video (MP4/MOV/WebM, max 35 MB, 90 seconds)':'image (JPEG/PNG/WebP, max 15 MB)'}
        <input ref={inputRef} type="file"
          accept={kind==='ROOM_VIDEO'?'video/mp4,video/quicktime,video/webm':acceptTypes}
          onChange={e=>setFile(e.target.files?.[0]||null)}/>
      </label>
      <button className="guidedPrimary" disabled={busy||!file} onClick={upload} type="button">
        {busy?'Working…':'Upload privately'}
      </button>
      <p className="guidedNote">Uploading stores the original in the sandbox's private uploads volume. It never starts AI analysis.</p>
    </div>

    {data?.evidence.length? <section className="guidedLibrary">
      <h3>2 · Analyze and review what was actually seen</h3>
      <label className="guidedCheck"><input type="checkbox" checked={aiConsent}
        disabled={!data.provider_configured}
        onChange={e=>setAiConsent(e.target.checked)}/>
        I consent to sending the selected image or video frames to OpenAI for this analysis
      </label>
      {!data.provider_configured&&<p className="guidedNote">AI analysis is disabled. Uploads and local coverage guidance work; enable the separate guided-setup provider in your sandbox to analyze media.</p>}
      {data.evidence.map(item=><details key={item.id} className="guidedMedia" open={false}>
        <summary><b>{labels[item.media_kind]}</b> · {item.room_hint||item.floor_hint||'Unassigned area'}
          <small> {item.status} · {item.pending_count} pending · {(item.bytes/1048576).toFixed(1)} MB</small>
        </summary>
        <div className="guidedMediaInside">
          <button className="guidedSecondary" disabled={busy}
            type="button" onClick={()=>showMedia(item)}>
            {preview[item.id]?'Hide preview':'View private evidence'}
          </button>
          {preview[item.id]&&(item.media_kind==='ROOM_VIDEO'?
            <video src={preview[item.id]} controls preload="metadata" className="guidedPreview"/>:
            <img src={preview[item.id]} alt="Private owner-uploaded setup evidence" className="guidedPreview"/>)}
          {item.status!=='ANALYZED'&&<button className="guidedPrimary"
            type="button" disabled={busy||!aiConsent||!data.provider_configured}
            onClick={()=>analyze(item)}>Analyze this evidence with AI</button>}
          {item.notes?.unresolved?.map((text,i)=><p key={i} className="guidedNote">Unresolved: {text}</p>)}
          {item.notes?.suggested_next_capture&&<p className="guidedNote">Suggested capture: {item.notes.suggested_next_capture}</p>}
          {item.status==='ANALYZED'&&!item.suggestions.length&&
            <p className="guidedNote">No reliable structure or objects identified. Describe the room or provide clearer evidence.</p>}
          {item.suggestions.map(suggestion=>{
            const values=drafts[suggestion.id]||{name:suggestion.name,floor_id:'',room_id:''};
            return <article className="guidedSuggestion" key={suggestion.id}>
              <div><strong>{suggestion.kind} · {suggestion.status}</strong>
                <small>{suggestion.evidence_summary}</small></div>
              {suggestion.status==='PENDING'?<>
                <label>Correct the detected name<input value={values.name} maxLength={110}
                  onChange={e=>setDraft(suggestion.id,{name:e.target.value},suggestion)}/></label>
                {suggestion.kind==='ROOM'&&<label>Verified floor for this room
                  <select value={values.floor_id} onChange={e=>setDraft(suggestion.id,{floor_id:e.target.value},suggestion)}>
                    <option value="">Use matching floor name: {suggestion.floor_hint||item.floor_hint||'none'}</option>
                    {floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}
                  </select>
                </label>}
                {suggestion.kind==='ASSET'&&<label>Verified room for this asset
                  <select value={values.room_id} onChange={e=>setDraft(suggestion.id,{room_id:e.target.value},suggestion)}>
                    <option value="">Use attached/labelled room: {suggestion.room_hint||item.room_hint||'none'}</option>
                    {rooms.map(r=><option key={r.id} value={r.id}>{r.floorName} · {r.name}</option>)}
                  </select>
                </label>}
                <div className="guidedActions">
                  <button className="guidedPrimary" type="button" disabled={busy}
                    onClick={()=>resolve(item,suggestion,'ACCEPT')}>Approve &amp; register</button>
                  <button className="guidedSecondary" type="button" disabled={busy}
                    onClick={()=>resolve(item,suggestion,'REJECT')}>Reject detection</button>
                </div>
              </>:<p className="guidedNote">Decision saved. {suggestion.applied_id?'Linked to a confirmed record.':'No record created.'}</p>}
            </article>;
          })}
        </div>
      </details>)}
    </section>:<p className="guidedNote">No walkthroughs or photographs uploaded yet.</p>}
    {notice&&<p className="guidedOk" role="status">{notice}</p>}
    {error&&<p className="guidedError" role="alert">{error}</p>}
    <p className="guidedNote"><b>Limits:</b> Images and video cannot prove hidden objects, complete inventory, exact dimensions or room connections. Confirm detected facts before letting JARVIS use them.</p>
    <style jsx>{`
      .guidedSetup{background:#f8fbf9;border:1px solid #bfd5cb;border-radius:18px;padding:18px;
        margin:0 0 18px;display:flex;flex-direction:column;gap:14px;color:#173b2e}
      .guidedHeading{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
      .guidedHeading strong{font-size:18px}.guidedHeading p{font-size:13px;margin:5px 0;line-height:1.4}
      .guidedBadge{font-size:11px;border-radius:30px;padding:6px 10px;background:#d8eee3;white-space:nowrap}
      .guidedNote{font-size:12px;line-height:1.5;color:#5f756b;margin:0}
      .guidedProgress{display:flex;flex-wrap:wrap;gap:8px}.guidedProgress span{font-size:12px;
        background:white;border:1px solid #dbe9e0;padding:8px 10px;border-radius:9px}
      .guidedProgress b{font-size:17px}.guidedAdvice{padding:14px;background:#e9f4ee;border-radius:12px}
      .guidedAdvice>b{display:block;font-size:15px;margin:8px 0}
      .guidedAdvice p{font-size:12px;color:#506c60}
      .guidedSubhead{font-size:11px;font-weight:650;letter-spacing:.03em}
      .guidedCapture,.guidedLibrary{padding:14px;background:#fff;border-radius:12px;border:1px solid #d9e7df}
      h3{font-size:15px;margin:0 0 10px}
      label{display:block;font-size:12px;font-weight:600;margin:9px 0;color:#2a5140}
      input:not([type=checkbox]),select{display:block;max-width:100%;width:100%;
        padding:9px;margin-top:5px;border:1px solid #bdcec3;border-radius:8px;
        background:white;color:#173b2e;font:inherit}
      .guidedCheck{display:flex;align-items:flex-start;gap:8px;font-weight:500;line-height:1.5}
      .guidedCheck input{margin-top:3px;accent-color:#145441}
      .guidedTwo{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
      .guidedPrimary,.guidedSecondary{display:inline-block;min-height:34px;padding:8px 12px;
        border-radius:8px;border:1px solid #145441;font-size:12px;font-weight:650;cursor:pointer}
      .guidedPrimary{background:#145441;color:white}.guidedSecondary{background:white;color:#145441}
      button:disabled{opacity:.45;cursor:not-allowed}
      .guidedMedia{padding:11px 0;border-bottom:1px solid #e1eae4}
      .guidedMedia summary{cursor:pointer;line-height:1.6;font-size:12px}
      .guidedMedia small{font-size:11px;color:#718578;display:block}
      .guidedMediaInside{padding:12px 0;display:flex;flex-direction:column;gap:10px}
      .guidedPreview{max-width:100%;max-height:360px;object-fit:contain;border-radius:9px}
      .guidedSuggestion{border:1px solid #e0e8e2;padding:12px;border-radius:10px}
      .guidedSuggestion small{display:block;margin-top:4px}
      .guidedActions{display:flex;gap:8px;flex-wrap:wrap}
      .guidedOk{color:#145441;font-size:12px}.guidedError{color:#b12929;font-size:12px;overflow-wrap:anywhere}
      @media(max-width:700px){.guidedHeading{flex-direction:column}.guidedBadge{white-space:normal}}
    `}</style>
  </section>;
}
