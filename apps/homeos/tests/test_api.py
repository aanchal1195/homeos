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
