import os,tempfile
fd,path=tempfile.mkstemp(suffix='.db');os.close(fd)
os.environ['DATABASE_URL']='sqlite:///'+path
from fastapi.testclient import TestClient
from app.main import app
c=TestClient(app)

def call(method,url,actor=None,**kw):
    headers={'X-Member-Id':actor} if actor else {}
    return c.request(method,url,headers=headers,**kw)

def bootstrap():
    r=call('POST','/api/setup',json={'name':'Test Home','owner_name':'Owner','maid_name':'Sunita','cook_name':'Ramesh'})
    assert r.status_code==200
    owner,maid,cook=[x['id'] for x in r.json()['members']]
    return owner,maid,cook

def build_virtual_house(owner,maid,cook):
    prop=call('POST','/api/virtual-house/property',owner,json={'name':'Test Home','property_type':'independent_house','address_label':''})
    assert prop.status_code==200
    gf=call('POST','/api/virtual-house/floors',owner,json={'name':'Ground Floor','sort_order':0,'kind':'floor'}).json()['id']
    ff=call('POST','/api/virtual-house/floors',owner,json={'name':'First Floor','sort_order':1,'kind':'floor'}).json()['id']
    kitchen=call('POST','/api/rooms',owner,json={'floor_id':gf,'floor':0,'name':'Kitchen','kind':'kitchen'}).json()['id']
    bath=call('POST','/api/rooms',owner,json={'floor_id':ff,'floor':0,'name':'Guest Bathroom','kind':'bathroom'}).json()['id']
    zone=call('POST','/api/virtual-house/zones',owner,json={'room_id':kitchen,'name':'Sink','kind':'sink'}).json()['id']
    assert call('POST','/api/assets',owner,json={'room_id':kitchen,'zone_id':zone,'name':'Water purifier','asset_type':'appliance'}).status_code==200
    assert call('POST','/api/virtual-house/staff-scopes',owner,json={'member_id':maid,'floor_id':ff}).status_code==200
    assert call('POST','/api/virtual-house/staff-scopes',owner,json={'member_id':cook,'room_id':kitchen}).status_code==200
    done=call('POST','/api/setup/complete',owner,json={})
    assert done.status_code==200
    return gf,ff,kitchen,bath

def test_setup_mode_blocks_jarvis_tasks_until_virtual_house_complete():
    owner,maid,cook=bootstrap()
    state=call('GET','/api/setup-state',owner).json()
    assert state['mode']=='SETUP' and state['setup_completed'] is False
    r=call('POST','/api/chat',owner,json={'text':'Maid ko Guest Bathroom saaf karwa do'})
    assert r.status_code==200 and r.json()['intent']=='SETUP_REQUIRED'
    direct=call('POST','/api/tasks',owner,json={'title':'Should fail','assignee_id':maid})
    assert direct.status_code==409
    build_virtual_house(owner,maid,cook)
    state=call('GET','/api/setup-state',owner).json()
    assert state['mode']=='OPERATIONAL'
    assert state['counts']['floors']==2 and state['counts']['rooms']==2 and state['counts']['assets']==1

def test_virtual_house_tree_and_permissions():
    members=call('GET','/api/demo-members').json();owner=next(x['id'] for x in members if x['role']=='owner');maid=next(x['id'] for x in members if x['role']=='maid')
    tree=call('GET','/api/virtual-house',owner)
    assert tree.status_code==200
    prop=tree.json()['property'];assert prop['name']=='Test Home';assert len(prop['floors'])==2
    assert any(r['name']=='Guest Bathroom' for f in prop['floors'] for r in f['rooms'])
    assert call('GET','/api/virtual-house',maid).status_code==403
    assert call('POST','/api/rooms',maid,json={'floor':5,'name':'Terrace'}).status_code==403

def test_jarvis_resolves_configured_room_and_enforces_scope():
    members=call('GET','/api/demo-members').json();owner=next(x['id'] for x in members if x['role']=='owner');maid=next(x['id'] for x in members if x['role']=='maid');cook=next(x['id'] for x in members if x['role']=='cook')
    r=call('POST','/api/chat',owner,json={'text':'Maid ko Guest Bathroom saaf karwa do'})
    assert r.status_code==200 and r.json()['intent']=='CREATE_TASK'
    today=call('GET','/api/today',maid).json()['tasks']
    assert any(t['source']=='JARVIS' and t['room_name']=='Guest Bathroom' for t in today)
    denied=call('POST','/api/chat',owner,json={'text':'Maid ko Kitchen saaf karwa do'})
    assert denied.status_code==200 and denied.json()['intent']=='SCOPE_DENIED'
    cooking=call('POST','/api/chat',owner,json={'text':'Cook ko Kitchen mein dinner banao'})
    assert cooking.status_code==200 and cooking.json()['intent']=='CREATE_TASK'

def test_unconfigured_room_is_not_invented():
    members=call('GET','/api/demo-members').json();owner=next(x['id'] for x in members if x['role']=='owner')
    r=call('POST','/api/chat',owner,json={'text':'Maid ko Master Bathroom saaf karwa do'})
    assert r.status_code==200
    assert r.json()['intent']=='CLARIFY_ROOM'

def test_contextual_house_questions_are_grounded():
    members=call('GET','/api/demo-members').json();owner=next(x['id'] for x in members if x['role']=='owner')
    r=call('POST','/api/chat',owner,json={'text':'how many rooms do we have'})
    assert r.status_code==200
    assert r.json()['intent']=='HOUSE_QUERY_ROOM_COUNT'
    assert '2 configured rooms' in r.json()['reply']
    f=call('POST','/api/chat',owner,json={'text':'what do we have on First Floor?'})
    assert f.json()['intent']=='HOUSE_QUERY_FLOOR_CONTENTS'
    assert 'Guest Bathroom' in f.json()['reply']
    a=call('POST','/api/chat',owner,json={'text':'what assets are in Kitchen?'})
    assert a.json()['intent']=='HOUSE_QUERY_ROOM_ASSETS'
    assert 'Water purifier' in a.json()['reply']


def test_context_endpoint_and_missing_fact_does_not_hallucinate():
    members=call('GET','/api/demo-members').json();owner=next(x['id'] for x in members if x['role']=='owner')
    ctx=call('GET','/api/context',owner)
    assert ctx.status_code==200
    assert len(ctx.json()['rooms'])==2
    r=call('POST','/api/chat',owner,json={'text':'what assets are in Guest Bathroom?'})
    assert r.json()['intent']=='HOUSE_QUERY_ROOM_ASSETS'
    assert 'No assets are registered' in r.json()['reply']

def test_memory_projection_is_owner_only_and_requires_postgresql():
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    assert call('POST','/api/memory/sync',maid,json={}).status_code==403
    assert call('GET','/api/memory/overview',maid).status_code==403
    assert call('POST','/api/memory/sync',owner,json={}).status_code==503
    assert call('GET','/api/memory/overview',owner).status_code==503

def test_location_queries_never_invent_an_unregistered_asset():
    from app.memory_bridge import _subject
    assert _subject('Where is the fridge?')=='refrigerator'
    assert _subject('fridge kahan hai?')=='refrigerator'
    assert _subject('Where is the microwave?')=='microwave'
    assert _subject('Please assign the cook dinner') is None

def test_visual_review_requires_owner_and_configured_graph():
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    observation='11111111-1111-4111-8111-111111111111'
    assert call('GET','/api/memory/visual/pending',maid).status_code==403
    assert call('GET',f'/api/memory/visual/{observation}/evidence',maid).status_code==403
    assert call('POST',f'/api/memory/visual/{observation}/resolve',maid,
      json={'decision':'REJECT'}).status_code==403
    # SQLite is never used as an authoritative graph and cannot approve photos.
    assert call('GET','/api/memory/visual/pending',owner).status_code==503
    assert call('POST',f'/api/memory/visual/{observation}/resolve',owner,
      json={'decision':'REJECT'}).status_code==503


def test_grounded_intent_parser_is_read_only_and_handles_paraphrases(monkeypatch):
    from app.grounded_jarvis import norm, _extract_unknown, MUTATING, _asset_candidates, optional_intent
    assert norm('  Fridge...  Kahan? ')=='fridge kahan'
    from app.grounded_jarvis import _hinglish
    assert _hinglish('Electric kettle kahan hai?') is True
    assert _hinglish('फ्रिज कहाँ है?') is True
    assert _hinglish('Is it still there?') is False
    assert _extract_unknown('Where did we put the microwave?')=='microwave'
    assert _extract_unknown('Fridge kahan hai?')=='refrigerator'
    assert _extract_unknown('Where is it now?') is None
    assert MUTATING.search('Please move the microwave to the kitchen')
    assert MUTATING.search('assign someone to clean the bathroom')
    assert _asset_candidates([
        {'id':'1','canonical_name':'Ceiling Fan','aliases':[]},
        {'id':'2','canonical_name':'Window Fan','aliases':[]},
    ],'fan')
    monkeypatch.delenv('HOMEOS_CHAT_EXTERNAL_ENABLED',raising=False)
    assert optional_intent('Where is it?',[],[],{}) is None


def test_home_manager_requires_owner_and_confirmation_then_tracks_evidence():
    import base64
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    cook=next(x['id'] for x in members if x['role']=='cook')
    tree=call('GET','/api/virtual-house',owner).json()['property']
    rooms={r['name']:r['id'] for f in tree['floors'] for r in f['rooms']}
    kitchen=rooms['Kitchen']
    bathroom=rooms['Guest Bathroom']
    draft={'room_id':bathroom,'assignee_id':maid,
           'instruction':'Wipe surfaces; submit photographic evidence.'}
    assert call('POST','/api/home-manager/plans',maid,json=draft).status_code==403
    assert call('POST','/api/home-manager/plans',owner,
                json={**draft,'room_id':kitchen}).status_code==403
    assert call('POST','/api/home-manager/plans',owner,
                json={**draft,'assignee_id':cook}).status_code==422
    before=call('GET','/api/today',maid).json()['tasks']
    created=call('POST','/api/home-manager/plans',owner,json=draft)
    assert created.status_code==201,created.text
    plan=created.json()
    assert plan['status']=='PROPOSED'
    assert plan['task_id'] is None
    assert len(call('GET','/api/today',maid).json()['tasks'])==len(before)
    assert call('GET',f"/api/home-manager/plans/{plan['id']}",maid).status_code==403

    approved=call('POST',f"/api/home-manager/plans/{plan['id']}/confirm",owner,json={})
    assert approved.status_code==200,approved.text
    assigned=approved.json()
    task_id=assigned['task_id']
    assert task_id and assigned['task_status']=='ASSIGNED'
    assert assigned['owner_confirmed']
    assert call('POST',f"/api/home-manager/plans/{plan['id']}/confirm",owner,
                json={}).json()['task_id']==task_id
    assert call('POST',f"/api/home-manager/plans/{plan['id']}/cancel",owner,
                json={}).status_code==409
    assert call('POST',f"/api/home-manager/plans/{plan['id']}/confirm",maid,
                json={}).status_code==403
    after=call('GET','/api/today',maid).json()['tasks']
    assert len(after)==len(before)+1
    assert after[-1]['source']=='HOME_MANAGER'

    for state in ('IN_PROGRESS','SUBMITTED'):
        result=call('POST',f'/api/tasks/{task_id}/status',maid,json={'status':state})
        assert result.status_code==200,result.text
    pending=call('GET',f"/api/home-manager/plans/{plan['id']}",owner)
    assert pending.status_code==200
    assert 'inspect evidence' in pending.json()['follow_up']
    assert call('POST',f'/api/tasks/{task_id}/status',owner,
                json={'status':'VERIFIED'}).status_code==409
    sample=base64.b64decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pLUAAAAASUVORK5CYII=')
    evidence=call('POST',f'/api/tasks/{task_id}/evidence',maid,
       files={'file':('completed.png',sample,'image/png')})
    assert evidence.status_code==200,evidence.text
    assert call('POST',f'/api/tasks/{task_id}/status',maid,
                json={'status':'VERIFIED'}).status_code==403
    assert call('POST',f'/api/tasks/{task_id}/status',owner,
                json={'status':'VERIFIED'}).status_code==200
    assert call('POST',f'/api/tasks/{task_id}/status',owner,
                json={'status':'CLOSED'}).status_code==200
    finished=call('GET',f"/api/home-manager/plans/{plan['id']}",owner).json()
    assert finished['task_status']=='CLOSED'
    assert finished['evidence_count']==1
    assert finished['follow_up']=='Completed and closed.'


def test_optional_model_cannot_substitute_a_previous_asset_for_unknown_subject(monkeypatch):
    import app.grounded_jarvis as router
    class FakeResponse:
        def raise_for_status(self):pass
        def json(self):
            return {'choices':[{'message':{'content':
              '{"intent":"location","subject":"Refrigerator","room":"Kitchen"}'}}]}
    class FakeClient:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def post(self,*args,**kwargs):return FakeResponse()
    monkeypatch.setattr(router.httpx,'Client',FakeClient)
    monkeypatch.setenv('HOMEOS_CHAT_EXTERNAL_ENABLED','true')
    monkeypatch.setenv('HOMEOS_CHAT_API_KEY','ci-fake-no-network')
    previous={'ref_name':'Refrigerator','ref_type':'asset'}
    guessed=router.optional_intent('Where is the toaster?',[],[],previous)
    assert guessed and guessed.subject is None and guessed.room is None
    referred=router.optional_intent('Where is it now?',[],[],previous)
    assert referred and referred.subject=='Refrigerator' and referred.room is None


def test_chat_can_draft_but_not_auto_assign_a_cleaning_plan():
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    before=len(call('GET','/api/today',maid).json()['tasks'])
    message=call('POST','/api/chat',owner,
       json={'text':'Please plan cleaning Guest Bathroom for maid'})
    assert message.status_code==200,message.text
    reply=message.json()
    assert reply['intent']=='HOME_MANAGER_PLAN_DRAFTED',reply
    assert 'No task has been assigned yet' in reply['reply']
    assert len(call('GET','/api/today',maid).json()['tasks'])==before
    drafted=call('GET',f"/api/home-manager/plans/{reply['action_ref']}",owner)
    assert drafted.status_code==200 and drafted.json()['status']=='PROPOSED'
    assert drafted.json()['task_id'] is None
    assert call('POST',f"/api/home-manager/plans/{reply['action_ref']}/confirm",
                maid,json={}).status_code==403
    confirmed=call('POST',f"/api/home-manager/plans/{reply['action_ref']}/confirm",
                   owner,json={})
    assert confirmed.status_code==200 and confirmed.json()['task_id']
    assert len(call('GET','/api/today',maid).json()['tasks'])==before+1
    question=call('POST','/api/chat',owner,
       json={'text':'What is the plan for cleaning Guest Bathroom for maid?'})
    assert question.status_code==200
    assert question.json()['intent']=='HOME_MANAGER_PLAN_QUERY'
    ambiguous=call('POST','/api/chat',owner,
       json={'text':'Plan cleaning the imaginary sun room for maid'})
    assert ambiguous.status_code==200
    assert ambiguous.json()['intent']=='HOME_MANAGER_CLARIFY_ROOM'


def test_guided_floorplan_photo_workflow_requires_review(monkeypatch,tmp_path):
    import io
    from PIL import Image
    from app import guided_setup
    from app.main import SessionLocal, Floor, Room, Asset, GuidedEvidence
    from sqlalchemy import select
    monkeypatch.setenv("HOMEOS_GUIDED_MEDIA_ROOT",str(tmp_path))
    monkeypatch.delenv("HOMEOS_GUIDED_SETUP_AI_ENABLED",raising=False)
    monkeypatch.delenv("HOMEOS_GUIDED_SETUP_API_KEY",raising=False)
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    # Owner can supply evidence before any AI key/consent; staff cannot inspect.
    image=Image.new('RGB',(240,160),(220,220,220))
    buf=io.BytesIO();image.save(buf,format='PNG');raw=buf.getvalue()
    payload={'media_kind':'FLOORPLAN','floor_hint':'Terrace'}
    forbidden=call('POST','/api/guided/upload',maid,data=payload,
                   files={'file':('layout.png',raw,'image/png')})
    assert forbidden.status_code==403,forbidden.text
    uploaded=call('POST','/api/guided/upload',owner,data=payload,
                  files={'file':('layout.png',raw,'image/png')})
    assert uploaded.status_code==201,uploaded.text
    evidence=uploaded.json()['evidence']
    assert evidence['status']=='UPLOADED' and not evidence['consent_recorded']
    assert evidence['pending_count']==0
    assert call('GET',f"/api/guided/evidence/{evidence['id']}/media",
                maid).status_code==403
    preview=call('GET',f"/api/guided/evidence/{evidence['id']}/media",owner)
    assert preview.status_code==200 and preview.content==raw
    assert 'no-store' in preview.headers.get('cache-control','')
    with SessionLocal() as db:
        item=db.get(GuidedEvidence,evidence['id'])
        assert item and item.storage_key.startswith(item.household_id+'/')
    assert call('POST','/api/guided/analyze',owner,json={
        'evidence_id':evidence['id'],'consent_to_external_ai_processing':False
    }).status_code==422
    assert call('POST','/api/guided/analyze',owner,json={
        'evidence_id':evidence['id'],'consent_to_external_ai_processing':True
    }).status_code==503
    with SessionLocal() as db:
        assert db.get(GuidedEvidence,evidence['id']).status=='UPLOADED'

    def scripted(item,path):
        assert item.media_kind=='FLOORPLAN'
        assert path.read_bytes()==raw
        return guided_setup.VisionReadout.model_validate({
            'findings':[
               {'kind':'FLOOR','name':'Terrace','evidence_summary':'Label visible on synthetic plan'},
               {'kind':'ROOM','name':'Store Room','floor_hint':'Terrace',
                 'room_kind':'store','evidence_summary':'Synthetic annotated room on plan'},
            ],
            'unresolved':['Is the store accessible from the terrace?'],
            'suggested_next_capture':'Photograph the store doorway.'})
    monkeypatch.setattr(guided_setup,'_infer',scripted)
    monkeypatch.setenv('HOMEOS_GUIDED_SETUP_AI_ENABLED','true')
    monkeypatch.setenv('HOMEOS_GUIDED_SETUP_API_KEY','CI_SCRIPTED_KEY')
    analyzed=call('POST','/api/guided/analyze',owner,json={
        'evidence_id':evidence['id'],'consent_to_external_ai_processing':True
    })
    assert analyzed.status_code==200,analyzed.text
    assert analyzed.json()['evidence']['status']=='ANALYZED'
    proposals=analyzed.json()['evidence']['suggestions']
    assert {x['kind'] for x in proposals}=={'FLOOR','ROOM'}
    with SessionLocal() as db:
        assert db.scalar(select(Floor.id).where(Floor.name=='Terrace')) is None
        assert db.scalar(select(Room.id).where(Room.name=='Store Room')) is None
    # Accept rooms only after their real floor is owner verified.
    requested=call('POST',f"/api/guided/evidence/{evidence['id']}/decide",owner,
      json={'suggestion_id':proposals[1]['id'],'decision':'ACCEPT'})
    assert requested.status_code==422,requested.text
    registered=call('POST',f"/api/guided/evidence/{evidence['id']}/decide",owner,
      json={'suggestion_id':proposals[0]['id'],'decision':'ACCEPT'})
    assert registered.status_code==200,registered.text
    floor_id=registered.json()['applied_id']
    assert floor_id
    room=call('POST',f"/api/guided/evidence/{evidence['id']}/decide",owner,
       json={'suggestion_id':proposals[1]['id'],'decision':'ACCEPT',
             'floor_id':floor_id,'corrected_name':'Store room'})
    assert room.status_code==200,room.text
    assert room.json()['applied_id']
    assert call('POST',f"/api/guided/evidence/{evidence['id']}/decide",owner,
       json={'suggestion_id':proposals[1]['id'],'decision':'ACCEPT',
             'floor_id':floor_id}).status_code==409
    with SessionLocal() as db:
        assert db.get(Room,room.json()['applied_id']).name=='Store room'


def test_guided_room_photo_rejection_and_adaptive_next(monkeypatch,tmp_path):
    import io
    from PIL import Image
    from app import guided_setup
    from app.main import SessionLocal, Asset, Room, GuidedDecision
    from sqlalchemy import select
    monkeypatch.setenv('HOMEOS_GUIDED_MEDIA_ROOT',str(tmp_path))
    monkeypatch.setenv('HOMEOS_GUIDED_SETUP_AI_ENABLED','true')
    monkeypatch.setenv('HOMEOS_GUIDED_SETUP_API_KEY','CI_SCRIPTED_KEY')
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    home=call('GET','/api/setup-state',owner).json()['property']
    kitchen=next(r['id'] for f in home['floors'] for r in f['rooms'] if r['name']=='Kitchen')
    image=Image.new('RGB',(50,50),(20,120,60))
    buf=io.BytesIO();image.save(buf,format='PNG')
    uploaded=call('POST','/api/guided/upload',owner,data={
       'media_kind':'ROOM_PHOTO','room_id':kitchen,'room_hint':'Kitchen'},
       files={'file':('test.png',buf.getvalue(),'image/png')})
    assert uploaded.status_code==201,uploaded.text
    evidence=uploaded.json()['evidence']['id']
    monkeypatch.setattr(guided_setup,'_infer',lambda *_:guided_setup.VisionReadout.model_validate({
      'findings':[
        {'kind':'ASSET','name':'Electric Kettle','asset_type':'appliance',
         'evidence_summary':'Synthetic model recognized countertop object'},
        {'kind':'ASSET','name':'Bread Toaster','asset_type':'appliance',
         'evidence_summary':'Synthetic false positive to reject'},
      ],
      'unresolved':['Counter behind fridge not visible'] }))
    analyzed=call('POST','/api/guided/analyze',owner,json={
      'evidence_id':evidence,'consent_to_external_ai_processing':True})
    assert analyzed.status_code==200,analyzed.text
    suggestions=analyzed.json()['evidence']['suggestions']
    assert call('POST',f'/api/guided/evidence/{evidence}/decide',maid,
      json={'suggestion_id':suggestions[0]['id'],'decision':'ACCEPT'}).status_code==403
    assert call('POST',f'/api/guided/evidence/{evidence}/decide',owner,
      json={'suggestion_id':suggestions[1]['id'],'decision':'REJECT'}).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(Asset.id).where(Asset.name=='Bread Toaster')) is None
    assert call('POST',f'/api/guided/evidence/{evidence}/decide',owner,json={
      'suggestion_id':suggestions[0]['id'],'decision':'ACCEPT',
      'corrected_name':'Electric Kettle','room_id':kitchen}).status_code==200
    with SessionLocal() as db:
        kettle=db.scalar(select(Asset).where(Asset.name=='Electric Kettle'))
        assert kettle and kettle.room_id==kitchen
    # A second room photo naming the existing kettle cannot silently register a
    # duplicate or turn an observation into a guessed relocation.
    bathroom=next(r['id'] for f in home['floors'] for r in f['rooms']
                  if r['name']=='Guest Bathroom')
    duplicate=call('POST','/api/guided/upload',owner,data={
       'media_kind':'ROOM_PHOTO','room_id':bathroom,'room_hint':'Guest Bathroom'},
       files={'file':('another.png',buf.getvalue(),'image/png')})
    assert duplicate.status_code==201,duplicate.text
    duplicate_id=duplicate.json()['evidence']['id']
    monkeypatch.setattr(guided_setup,'_infer',
       lambda *_:guided_setup.VisionReadout.model_validate({
         'findings':[{'kind':'ASSET','name':'Electric Kettle',
            'asset_type':'appliance','evidence_summary':'Synthetic duplicate label'}]}))
    seen=call('POST','/api/guided/analyze',owner,json={
        'evidence_id':duplicate_id,'consent_to_external_ai_processing':True})
    assert seen.status_code==200,seen.text
    repeated=seen.json()['evidence']['suggestions'][0]
    conflict=call('POST',f'/api/guided/evidence/{duplicate_id}/decide',owner,
        json={'suggestion_id':repeated['id'],'decision':'ACCEPT',
              'room_id':bathroom})
    assert conflict.status_code==409,conflict.text
    with SessionLocal() as db:
        assets=db.scalars(select(Asset).where(Asset.name=='Electric Kettle')).all()
        assert len(assets)==1 and assets[0].room_id==kitchen
    # Close the ambiguous finding so adaptive guidance does not treat it as fact.
    assert call('POST',f'/api/guided/evidence/{duplicate_id}/decide',owner,
       json={'suggestion_id':repeated['id'],'decision':'REJECT'}).status_code==200
    status=call('GET','/api/guided/status',owner)
    assert status.status_code==200,status.text
    assert status.json()['counts']['pending_review']==0
    # Without consent next-step planning remains entirely local.
    decision=call('POST','/api/guided/next',owner,json={
      'consent_to_external_ai_processing':False})
    assert decision.status_code==200
    assert decision.json()['guidance']['source']=='DETERMINISTIC_FALLBACK'
    # A model may choose among server-validated evidence requests, never create rooms.
    monkeypatch.setattr(guided_setup,'_provider',lambda *_,**__: {
      'step':'CAPTURE_ROOM','room_id':kitchen,
      'question':'Could you show the kitchen pantry with a second image?',
      'reason':'The registered pantry has not been inspected from this angle.'})
    ai=call('POST','/api/guided/next',owner,json={
      'consent_to_external_ai_processing':True})
    assert ai.status_code==200,ai.text
    assert ai.json()['guidance']['source']=='AI_GUIDED'
    assert ai.json()['guidance']['room_id']==kitchen
    with SessionLocal() as db:
        stored=db.get(GuidedDecision,ai.json()['decision_id'])
        assert stored.source=='AI_GUIDED'
    # Fabricated room IDs and unjustified 'READY' decisions fall back safely.
    monkeypatch.setattr(guided_setup,'_provider',lambda *_,**__: {
      'step':'READY_TO_LAUNCH','room_id':None,
      'question':'Finished all rooms and inventory?',
      'reason':'AI guessing completeness without sufficient evidence.'})
    unsafe=call('POST','/api/guided/next',owner,json={
      'consent_to_external_ai_processing':True})
    assert unsafe.status_code==200
    assert unsafe.json()['guidance']['source']=='DETERMINISTIC_FALLBACK'


def test_guided_video_validates_real_frames_and_size(monkeypatch,tmp_path):
    import shutil,subprocess
    from app import guided_setup
    import pytest
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg not available on this test runner')
    monkeypatch.setenv('HOMEOS_GUIDED_MEDIA_ROOT',str(tmp_path))
    members=call('GET','/api/demo-members').json()
    owner=next(x['id'] for x in members if x['role']=='owner')
    maid=next(x['id'] for x in members if x['role']=='maid')
    movie=tmp_path/'test.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi',
      '-i','color=c=blue:s=160x120:d=1.5','-pix_fmt','yuv420p',
      '-y',str(movie)],check=True,timeout=15)
    raw=movie.read_bytes()
    bad=call('POST','/api/guided/upload',owner,data={'media_kind':'ROOM_VIDEO'},
       files={'file':('fake.mp4',b'not-a-video','video/mp4')})
    assert bad.status_code==415,bad.text
    permitted=call('POST','/api/guided/upload',owner,data={
       'media_kind':'ROOM_VIDEO','room_hint':'New Guest Room'},
       files={'file':('walk.mp4',raw,'video/mp4')})
    assert permitted.status_code==201,permitted.text
    eid=permitted.json()['evidence']['id']
    assert call('GET',f'/api/guided/evidence/{eid}/media',maid).status_code==403
    from app.main import SessionLocal, GuidedEvidence
    with SessionLocal() as db:
        item=db.get(GuidedEvidence,eid)
        image_frames=guided_setup._encode(guided_setup._file_of(item),'video/mp4')
    assert len(image_frames)>=1 and len(image_frames)<=3
    assert call('POST','/api/guided/analyze',owner,json={
      'evidence_id':eid,'consent_to_external_ai_processing':False}).status_code==422


def test_guided_iphone_jpeg_and_png_mime_mismatch(monkeypatch,tmp_path):
    """Safari/Photos MIME is metadata, not the decoded image type."""
    import io
    from PIL import Image
    from app.main import SessionLocal,GuidedEvidence
    monkeypatch.setenv('HOMEOS_GUIDED_MEDIA_ROOT',str(tmp_path))
    members=call('GET','/api/demo-members').json()
    owner=next(m['id'] for m in members if m['role']=='owner')
    maid=next(m['id'] for m in members if m['role']=='maid')
    for actual_format,wrong_mime,canonical_mime,extension in [
        ('JPEG','image/png','image/jpeg','.jpg'),
        ('PNG','image/jpeg','image/png','.png'),
        ('JPEG','application/octet-stream','image/jpeg','.jpg'),
    ]:
        buf=io.BytesIO()
        Image.new('RGB',(72,48),(75,120,170)).save(buf,format=actual_format)
        raw=buf.getvalue()
        result=call('POST','/api/guided/upload',owner,
          data={'media_kind':'ROOM_PHOTO','room_hint':'iPhone test room'},
          files={'file':('IMG_0061.jpeg',raw,wrong_mime)})
        assert result.status_code==201,result.text
        item=result.json()['evidence']
        assert item['content_type']==canonical_mime,item
        assert not item['consent_recorded']
        with SessionLocal() as s:
            record=s.get(GuidedEvidence,item['id'])
            assert record.content_type==canonical_mime
            assert record.storage_key.endswith(extension)
        preview=call('GET',f"/api/guided/evidence/{item['id']}/media",owner)
        assert preview.status_code==200
        assert preview.content==raw
        assert canonical_mime in preview.headers['content-type']
        assert call('GET',f"/api/guided/evidence/{item['id']}/media",maid).status_code==403
    # A MIME type or .jpg suffix cannot smuggle an SVG, HTML or script into preview.
    forged=call('POST','/api/guided/upload',owner,
      data={'media_kind':'ROOM_PHOTO'},
      files={'file':('IMG_0061.jpg',b'<svg><script>alert(1)</script></svg>','image/jpeg')})
    assert forged.status_code==415,forged.text


def test_guided_native_iphone_heic_from_real_decoder(monkeypatch,tmp_path):
    """Encode/decode actual HEIF bytes, not a renamed .jpg fixture."""
    import base64,io
    from PIL import Image
    from app.main import SessionLocal,GuidedEvidence
    from app import guided_setup
    monkeypatch.setenv('HOMEOS_GUIDED_MEDIA_ROOT',str(tmp_path))
    members=call('GET','/api/demo-members').json()
    owner=next(m['id'] for m in members if m['role']=='owner')
    picture=Image.new('RGB',(80,60),(25,90,150))
    heic=io.BytesIO()
    # register_heif_opener() also registers the HEIF encoder on Pillow.
    picture.save(heic,format='HEIF',quality=76)
    raw=heic.getvalue()
    assert len(raw)>50 and raw[4:8]==b'ftyp',raw[:16]
    # Safari may report an HEIC payload as JPEG or generic binary.
    for misreported in ('image/jpeg','application/octet-stream','image/heic'):
        created=call('POST','/api/guided/upload',owner,
          data={'media_kind':'ROOM_PHOTO','room_hint':'Kitchen'},
          files={'file':('IMG_0061.HEIC',raw,misreported)})
        assert created.status_code==201,created.text
        item=created.json()['evidence']
        assert item['content_type'] in ('image/heic','image/heif'),item
        with SessionLocal() as s:
            evidence=s.get(GuidedEvidence,item['id'])
            assert evidence.storage_key.endswith(('.heic','.heif'))
            original=guided_setup._file_of(evidence).read_bytes()
            assert original==raw,'Original HEIC must not be overwritten'
            encoded=guided_setup._encode(guided_setup._file_of(evidence),evidence.content_type)
            decoded=base64.b64decode(encoded[0])
            assert decoded.startswith(bytes.fromhex('ffd8'))
        preview=call('GET',f"/api/guided/evidence/{item['id']}/media",owner)
        assert preview.status_code==200,preview.text[:120]
        assert preview.headers['content-type'].startswith('image/jpeg')
        with Image.open(io.BytesIO(preview.content)) as image:
            assert image.format=='JPEG'
            assert image.size==(80,60)
