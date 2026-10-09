"""HomeOS JARVIS MVP — M2C Contextual JARVIS.

The virtual house / digital twin is mandatory before JARVIS becomes operational.
Development identities are NOT production authentication. Conversational intent
handling is deterministic in this build so domain authorization remains explicit.
"""
import os, re, uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, ForeignKey, Text, DateTime, Integer, Boolean, select, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.getenv('DATABASE_URL', 'sqlite:///' + str(ROOT / 'homeos.db'))
engine = create_engine(DB_URL, connect_args={'check_same_thread': False} if DB_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(bind=engine)

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid.uuid4())

class Base(DeclarativeBase): pass

class Household(Base):
    __tablename__='households'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    name:Mapped[str]=mapped_column(String)
    setup_completed:Mapped[bool]=mapped_column(Boolean,default=False)

class Property(Base):
    __tablename__='properties'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'),unique=True)
    name:Mapped[str]=mapped_column(String)
    property_type:Mapped[str]=mapped_column(String,default='independent_house')
    address_label:Mapped[str]=mapped_column(String,default='')

class Floor(Base):
    __tablename__='floors'
    __table_args__=(UniqueConstraint('property_id','sort_order',name='uq_floor_property_order'),)
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    property_id:Mapped[str]=mapped_column(ForeignKey('properties.id'))
    name:Mapped[str]=mapped_column(String)
    sort_order:Mapped[int]=mapped_column(Integer)
    kind:Mapped[str]=mapped_column(String,default='floor')

class Member(Base):
    __tablename__='members'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    name:Mapped[str]=mapped_column(String)
    role:Mapped[str]=mapped_column(String)
    language:Mapped[str]=mapped_column(String,default='hinglish')

class Room(Base):
    __tablename__='rooms'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    floor:Mapped[int]=mapped_column(Integer,default=0)  # legacy compatibility
    floor_id:Mapped[Optional[str]]=mapped_column(ForeignKey('floors.id'),nullable=True)
    name:Mapped[str]=mapped_column(String)
    kind:Mapped[str]=mapped_column(String,default='other')

class Zone(Base):
    __tablename__='zones'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    room_id:Mapped[str]=mapped_column(ForeignKey('rooms.id'))
    name:Mapped[str]=mapped_column(String)
    kind:Mapped[str]=mapped_column(String,default='area')

class Asset(Base):
    __tablename__='assets'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    room_id:Mapped[str]=mapped_column(ForeignKey('rooms.id'))
    zone_id:Mapped[Optional[str]]=mapped_column(ForeignKey('zones.id'),nullable=True)
    name:Mapped[str]=mapped_column(String)
    asset_type:Mapped[str]=mapped_column(String,default='appliance')
    status:Mapped[str]=mapped_column(String,default='OK')
    next_service:Mapped[Optional[str]]=mapped_column(String,nullable=True)

class StaffScope(Base):
    __tablename__='staff_scopes'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    member_id:Mapped[str]=mapped_column(ForeignKey('members.id'))
    floor_id:Mapped[Optional[str]]=mapped_column(ForeignKey('floors.id'),nullable=True)
    room_id:Mapped[Optional[str]]=mapped_column(ForeignKey('rooms.id'),nullable=True)
    can_view:Mapped[bool]=mapped_column(Boolean,default=True)
    can_execute_tasks:Mapped[bool]=mapped_column(Boolean,default=True)

class Task(Base):
    __tablename__='tasks'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    room_id:Mapped[Optional[str]]=mapped_column(ForeignKey('rooms.id'),nullable=True)
    assignee_id:Mapped[str]=mapped_column(ForeignKey('members.id'))
    title:Mapped[str]=mapped_column(String)
    category:Mapped[str]=mapped_column(String,default='CLEANING')
    status:Mapped[str]=mapped_column(String,default='ASSIGNED')
    due_date:Mapped[str]=mapped_column(String,default=lambda:now().date().isoformat())
    notes:Mapped[str]=mapped_column(Text,default='')
    priority:Mapped[str]=mapped_column(String,default='MEDIUM')
    source:Mapped[str]=mapped_column(String,default='MANUAL')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Message(Base):
    __tablename__='messages'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    member_id:Mapped[str]=mapped_column(ForeignKey('members.id'))
    content:Mapped[str]=mapped_column(Text)
    reply:Mapped[str]=mapped_column(Text)
    intent:Mapped[str]=mapped_column(String,default='GENERAL')
    action_ref:Mapped[Optional[str]]=mapped_column(String,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Evidence(Base):
    __tablename__='evidence'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    task_id:Mapped[str]=mapped_column(ForeignKey('tasks.id'))
    member_id:Mapped[str]=mapped_column(ForeignKey('members.id'))
    filename:Mapped[str]=mapped_column(String)
    content_type:Mapped[str]=mapped_column(String)
    review_status:Mapped[str]=mapped_column(String,default='PENDING_OWNER_REVIEW')

class Issue(Base):
    __tablename__='issues'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(ForeignKey('households.id'))
    reporter_id:Mapped[str]=mapped_column(ForeignKey('members.id'))
    description:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String,default='OPEN')

class Audit(Base):
    __tablename__='audit'
    id:Mapped[str]=mapped_column(String,primary_key=True,default=uid)
    household_id:Mapped[str]=mapped_column(String)
    member_id:Mapped[str]=mapped_column(String)
    action:Mapped[str]=mapped_column(String)
    detail:Mapped[str]=mapped_column(Text)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

if DB_URL.startswith('sqlite') and os.getenv('HOMEOS_AUTO_CREATE_SQLITE', 'true').lower() == 'true':
    Base.metadata.create_all(engine)

app=FastAPI(title='HomeOS JARVIS',version='0.4.0')
app.mount('/static',StaticFiles(directory=str(ROOT/'web')),name='static')
@app.get('/')
def index(): return FileResponse(ROOT/'web'/'index.html')

def db():
    with SessionLocal() as s: yield s

def actor(s:Session=Depends(db), x_member_id:Optional[str]=Header(default=None)):
    if not x_member_id: raise HTTPException(401,'Select a local demo identity')
    m=s.get(Member,x_member_id)
    if not m: raise HTTPException(401,'Unknown identity')
    return m

def audit(s,m,action,detail): s.add(Audit(household_id=m.household_id,member_id=m.id,action=action,detail=detail))
def require_owner(m):
    if m.role!='owner': raise HTTPException(403,'Owner permission required')
def scoped(s,cls,id,m):
    obj=s.get(cls,id)
    if not obj or getattr(obj,'household_id',None)!=m.household_id: raise HTTPException(404,'Not found')
    return obj

def household_for(s,m): return s.get(Household,m.household_id)
def ensure_operational(s,m):
    if not household_for(s,m).setup_completed:
        raise HTTPException(409,'Virtual house setup must be completed before JARVIS can manage tasks')

def task_json(t:Task):
    return {'id':t.id,'title':t.title,'status':t.status,'assignee_id':t.assignee_id,'room_id':t.room_id,
            'due_date':t.due_date,'notes':t.notes,'category':t.category,'priority':t.priority,'source':t.source}

# --- Initial identity bootstrap -------------------------------------------
class InitIn(BaseModel):
    name:str='My Home'; owner_name:str='Owner'; maid_name:str='Maid'; cook_name:str='Cook'

@app.post('/api/setup')
def setup(p:InitIn,s:Session=Depends(db)):
    if s.scalar(select(Household.id).limit(1)): raise HTTPException(409,'Demo already initialized')
    h=Household(name=p.name,setup_completed=False);s.add(h);s.flush();members=[]
    for name,role in [(p.owner_name,'owner'),(p.maid_name,'maid'),(p.cook_name,'cook')]:
        m=Member(household_id=h.id,name=name,role=role);s.add(m);s.flush();members.append({'id':m.id,'name':m.name,'role':m.role})
    s.commit();return {'household_id':h.id,'members':members,'mode':'SETUP'}

@app.get('/api/demo-members')
def demo_members(s:Session=Depends(db)):
    return [{'id':m.id,'name':m.name,'role':m.role,'language':m.language} for m in s.scalars(select(Member)).all()]

# --- Virtual house / digital twin ----------------------------------------
def virtual_tree(s:Session, household_id:str):
    prop=s.scalar(select(Property).where(Property.household_id==household_id))
    if not prop:return None
    floors=s.scalars(select(Floor).where(Floor.household_id==household_id).order_by(Floor.sort_order)).all()
    rooms=s.scalars(select(Room).where(Room.household_id==household_id)).all()
    zones=s.scalars(select(Zone).where(Zone.household_id==household_id)).all()
    assets=s.scalars(select(Asset).where(Asset.household_id==household_id)).all()
    zones_by_room={}
    for z in zones:zones_by_room.setdefault(z.room_id,[]).append(z)
    assets_by_room={}
    for a in assets:assets_by_room.setdefault(a.room_id,[]).append(a)
    return {'id':prop.id,'name':prop.name,'property_type':prop.property_type,'address_label':prop.address_label,
            'floors':[{'id':f.id,'name':f.name,'sort_order':f.sort_order,'kind':f.kind,'rooms':[
                {'id':r.id,'name':r.name,'kind':r.kind,
                 'zones':[{'id':z.id,'name':z.name,'kind':z.kind} for z in zones_by_room.get(r.id,[])],
                 'assets':[{'id':a.id,'name':a.name,'asset_type':a.asset_type,'zone_id':a.zone_id,'status':a.status,'next_service':a.next_service} for a in assets_by_room.get(r.id,[])]}
                for r in rooms if r.floor_id==f.id]} for f in floors]}

@app.get('/api/setup-state')
def setup_state(m:Member=Depends(actor),s:Session=Depends(db)):
    h=household_for(s,m);tree=virtual_tree(s,m.household_id)
    counts={'floors':0,'rooms':0,'assets':0,'zones':0,'staff_scopes':0}
    for cls,key in [(Floor,'floors'),(Room,'rooms'),(Asset,'assets'),(Zone,'zones'),(StaffScope,'staff_scopes')]:
        counts[key]=len(s.scalars(select(cls).where(cls.household_id==m.household_id)).all())
    return {'mode':'OPERATIONAL' if h.setup_completed else 'SETUP','setup_completed':h.setup_completed,
            'household':{'id':h.id,'name':h.name},'property':tree,'counts':counts}

class PropertyIn(BaseModel):
    name:str=Field(min_length=1,max_length=120)
    property_type:str='independent_house'
    address_label:str=Field(default='',max_length=200)

@app.post('/api/virtual-house/property')
def upsert_property(p:PropertyIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);h=household_for(s,m)
    prop=s.scalar(select(Property).where(Property.household_id==m.household_id))
    if prop:
        prop.name=p.name;prop.property_type=p.property_type;prop.address_label=p.address_label
    else:
        prop=Property(household_id=m.household_id,**p.model_dump());s.add(prop);s.flush()
    h.name=p.name;audit(s,m,'virtual_house.property_saved',prop.id);s.commit()
    return {'id':prop.id,'name':prop.name}

class FloorIn(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    sort_order:int=Field(ge=0,le=100)
    kind:str='floor'

@app.post('/api/virtual-house/floors')
def add_floor(p:FloorIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);prop=s.scalar(select(Property).where(Property.household_id==m.household_id))
    if not prop:raise HTTPException(409,'Create property first')
    existing=s.scalar(select(Floor).where(Floor.property_id==prop.id,Floor.sort_order==p.sort_order))
    if existing:raise HTTPException(409,'A floor/space already uses this order')
    f=Floor(household_id=m.household_id,property_id=prop.id,**p.model_dump());s.add(f);s.flush();audit(s,m,'virtual_house.floor_created',f.id);s.commit()
    return {'id':f.id,'name':f.name,'sort_order':f.sort_order,'kind':f.kind}

@app.delete('/api/virtual-house/floors/{floor_id}')
def delete_floor(floor_id:str,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);f=scoped(s,Floor,floor_id,m)
    if s.scalar(select(Room.id).where(Room.floor_id==f.id).limit(1)):raise HTTPException(409,'Remove rooms from this floor first')
    audit(s,m,'virtual_house.floor_deleted',f.id);s.delete(f);s.commit();return {'ok':True}

class RoomIn(BaseModel):
    floor:int=Field(default=0,ge=0,le=100)
    floor_id:Optional[str]=None
    name:str=Field(min_length=1,max_length=100)
    kind:str='other'

@app.post('/api/rooms')
def add_room(p:RoomIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    data=p.model_dump()
    if p.floor_id:
        f=scoped(s,Floor,p.floor_id,m);data['floor']=f.sort_order
    r=Room(household_id=m.household_id,**data);s.add(r);s.flush();audit(s,m,'room.created',r.id);s.commit();return {'id':r.id}

class ZoneIn(BaseModel):
    room_id:str
    name:str=Field(min_length=1,max_length=100)
    kind:str='area'
@app.post('/api/virtual-house/zones')
def add_zone(p:ZoneIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);scoped(s,Room,p.room_id,m);z=Zone(household_id=m.household_id,**p.model_dump());s.add(z);s.flush();audit(s,m,'virtual_house.zone_created',z.id);s.commit();return {'id':z.id}

class AssetIn(BaseModel):
    room_id:str
    zone_id:Optional[str]=None
    name:str=Field(min_length=1,max_length=150)
    asset_type:str='appliance'
    next_service:Optional[str]=None
@app.post('/api/assets')
def add_asset(p:AssetIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);scoped(s,Room,p.room_id,m)
    if p.zone_id:
        z=scoped(s,Zone,p.zone_id,m)
        if z.room_id!=p.room_id:raise HTTPException(422,'Zone does not belong to selected room')
    a=Asset(household_id=m.household_id,**p.model_dump());s.add(a);s.flush();audit(s,m,'asset.created',a.id);s.commit();return {'id':a.id}

class ScopeIn(BaseModel):
    member_id:str
    floor_id:Optional[str]=None
    room_id:Optional[str]=None
    can_view:bool=True
    can_execute_tasks:bool=True
@app.post('/api/virtual-house/staff-scopes')
def add_scope(p:ScopeIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);staff=scoped(s,Member,p.member_id,m)
    if staff.role=='owner':raise HTTPException(422,'Scopes are for staff members')
    if not p.floor_id and not p.room_id:raise HTTPException(422,'Select a floor or room')
    if p.floor_id:scoped(s,Floor,p.floor_id,m)
    if p.room_id:
        room=scoped(s,Room,p.room_id,m)
        if p.floor_id and room.floor_id!=p.floor_id:raise HTTPException(422,'Room does not belong to selected floor')
    scope=StaffScope(household_id=m.household_id,**p.model_dump());s.add(scope);s.flush();audit(s,m,'virtual_house.staff_scope_created',scope.id);s.commit();return {'id':scope.id}

@app.get('/api/virtual-house')
def get_virtual_house(m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);return {'property':virtual_tree(s,m.household_id)}

@app.post('/api/setup/complete')
def complete_setup(m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);h=household_for(s,m);prop=s.scalar(select(Property).where(Property.household_id==m.household_id))
    floors=s.scalars(select(Floor).where(Floor.household_id==m.household_id)).all()
    rooms=s.scalars(select(Room).where(Room.household_id==m.household_id,Room.floor_id.is_not(None))).all()
    if not prop:raise HTTPException(422,'Property details are required')
    if not floors:raise HTTPException(422,'Add at least one floor or space')
    if not rooms:raise HTTPException(422,'Add at least one room')
    h.setup_completed=True;audit(s,m,'virtual_house.setup_completed',prop.id);s.commit()
    return {'mode':'OPERATIONAL','setup_completed':True,'property':virtual_tree(s,m.household_id)}

@app.post('/api/setup/reopen')
def reopen_setup(m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);h=household_for(s,m);h.setup_completed=False;audit(s,m,'virtual_house.setup_reopened',h.id);s.commit();return {'mode':'SETUP'}

@app.get('/api/overview')
def overview(m:Member=Depends(actor),s:Session=Depends(db)):
    q=lambda cls:s.scalars(select(cls).where(cls.household_id==m.household_id)).all()
    tasks=q(Task)
    if m.role!='owner':tasks=[t for t in tasks if t.assignee_id==m.id]
    h=household_for(s,m)
    return {'home':h.name,'role':m.role,'mode':'OPERATIONAL' if h.setup_completed else 'SETUP',
            'virtual_house':virtual_tree(s,m.household_id) if m.role=='owner' else None,
            'rooms':[{'id':r.id,'name':r.name,'floor':r.floor,'floor_id':r.floor_id,'kind':r.kind} for r in q(Room)] if m.role=='owner' else [],
            'assets':[{'id':a.id,'name':a.name,'status':a.status,'next_service':a.next_service} for a in q(Asset)] if m.role=='owner' else [],
            'tasks':[task_json(t) for t in tasks],
            'issues':[{'id':i.id,'description':i.description,'status':i.status} for i in q(Issue)] if m.role=='owner' else []}

# --- Tasks and evidence ---------------------------------------------------
class TaskIn(BaseModel):
    title:str=Field(min_length=1,max_length=250); assignee_id:str; room_id:Optional[str]=None
    category:str='CLEANING'; notes:str=''; priority:str='MEDIUM'; source:str='MANUAL'
@app.post('/api/tasks')
def add_task(p:TaskIn,m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m);ensure_operational(s,m);assignee=scoped(s,Member,p.assignee_id,m)
    if assignee.role=='owner': raise HTTPException(422,'Assign household work to staff')
    if p.room_id:scoped(s,Room,p.room_id,m)
    t=Task(household_id=m.household_id,**p.model_dump());s.add(t);s.flush();audit(s,m,'task.assigned',t.id);s.commit();return task_json(t)

class StatusIn(BaseModel): status:str
@app.post('/api/tasks/{task_id}/status')
def status(task_id:str,p:StatusIn,m:Member=Depends(actor),s:Session=Depends(db)):
    ensure_operational(s,m);t=scoped(s,Task,task_id,m)
    if m.role!='owner' and t.assignee_id!=m.id:raise HTTPException(403,'Not assigned to you')
    allowed={'ASSIGNED':{'IN_PROGRESS','BLOCKED'},'IN_PROGRESS':{'SUBMITTED','BLOCKED'},'BLOCKED':{'IN_PROGRESS'},'SUBMITTED':{'REWORK_REQUIRED','VERIFIED'},'REWORK_REQUIRED':{'IN_PROGRESS'},'VERIFIED':{'CLOSED'}}
    if p.status not in allowed.get(t.status,set()):raise HTTPException(409,'Invalid transition')
    if m.role!='owner' and p.status in {'VERIFIED','CLOSED','REWORK_REQUIRED'}:raise HTTPException(403,'Owner review required')
    if p.status=='VERIFIED' and not s.scalar(select(Evidence.id).where(Evidence.task_id==t.id).limit(1)):raise HTTPException(409,'Evidence required')
    t.status=p.status;audit(s,m,'task.status',f'{t.id}:{p.status}');s.commit();return task_json(t)

@app.get('/api/today')
def today(m:Member=Depends(actor),s:Session=Depends(db)):
    if not household_for(s,m).setup_completed:return {'date':date.today().isoformat(),'role':m.role,'mode':'SETUP','tasks':[]}
    stmt=select(Task).where(Task.household_id==m.household_id,Task.due_date==date.today().isoformat(),Task.status.notin_(['CLOSED']))
    if m.role!='owner': stmt=stmt.where(Task.assignee_id==m.id)
    tasks=s.scalars(stmt.order_by(Task.created_at.asc())).all()
    members={x.id:x for x in s.scalars(select(Member).where(Member.household_id==m.household_id)).all()}
    rooms={x.id:x for x in s.scalars(select(Room).where(Room.household_id==m.household_id)).all()}
    return {'date':date.today().isoformat(),'role':m.role,'mode':'OPERATIONAL','tasks':[
        {**task_json(t),'assignee_name':members.get(t.assignee_id).name if members.get(t.assignee_id) else None,
         'room_name':rooms.get(t.room_id).name if t.room_id and rooms.get(t.room_id) else None} for t in tasks]}

class IssueIn(BaseModel): description:str=Field(min_length=3,max_length=2000)
@app.post('/api/issues')
def issue(p:IssueIn,m:Member=Depends(actor),s:Session=Depends(db)):
    x=Issue(household_id=m.household_id,reporter_id=m.id,description=p.description);s.add(x);s.flush();audit(s,m,'issue.reported',x.id);s.commit();return {'id':x.id,'status':x.status}

UPLOAD_DIR=ROOT/'uploads';UPLOAD_DIR.mkdir(exist_ok=True)
@app.post('/api/tasks/{task_id}/evidence')
async def upload(task_id:str,file:UploadFile=File(...),m:Member=Depends(actor),s:Session=Depends(db)):
    ensure_operational(s,m);t=scoped(s,Task,task_id,m)
    if m.role!='owner' and t.assignee_id!=m.id:raise HTTPException(403,'Not assigned to you')
    if file.content_type not in {'image/jpeg','image/png','image/webp'}:raise HTTPException(415,'Only JPEG PNG or WebP supported')
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise HTTPException(413,'Max 5 MB')
    signatures={'image/jpeg':raw.startswith(b'\xff\xd8\xff'),'image/png':raw.startswith(b'\x89PNG\r\n\x1a\n'),'image/webp':raw.startswith(b'RIFF') and raw[8:12]==b'WEBP'}
    if not signatures[file.content_type]:raise HTTPException(415,'Invalid image signature')
    ext={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp'}[file.content_type]
    ev=Evidence(household_id=m.household_id,task_id=t.id,member_id=m.id,filename=uid()+ext,content_type=file.content_type)
    (UPLOAD_DIR/ev.filename).write_bytes(raw);s.add(ev);s.flush();audit(s,m,'evidence.uploaded',ev.id);s.commit();return {'id':ev.id,'review_status':ev.review_status}

@app.get('/api/evidence/{evidence_id}')
def get_evidence(evidence_id:str,m:Member=Depends(actor),s:Session=Depends(db)):
    ev=scoped(s,Evidence,evidence_id,m);t=scoped(s,Task,ev.task_id,m)
    if m.role!='owner' and t.assignee_id!=m.id:raise HTTPException(403,'Not permitted')
    return FileResponse(UPLOAD_DIR/ev.filename,media_type=ev.content_type,headers={'Cache-Control':'no-store'})

# --- Conversational JARVIS -----------------------------------------------
HI_HINTS={'aaj','kya','karna','ho gaya','saaf','paani','bhej','kal','kaam','nahi','karwa','lagao','bana do','kar do','chahiye'}
def is_hinglish(text:str)->bool:
    low=text.lower();return bool(re.search('[\u0900-\u097f]',text)) or any(w in low for w in HI_HINTS)

def active_tasks(s,m):
    stmt=select(Task).where(Task.household_id==m.household_id,Task.status.notin_(['CLOSED','VERIFIED']))
    if m.role!='owner':stmt=stmt.where(Task.assignee_id==m.id)
    return s.scalars(stmt.order_by(Task.created_at.asc())).all()

def find_member(s,m,text):
    staff=s.scalars(select(Member).where(Member.household_id==m.household_id,Member.role.in_(['maid','cook']))).all();low=text.lower()
    by_role=[x for x in staff if x.role in low]
    if len(by_role)==1:return by_role[0]
    by_name=[x for x in staff if x.name.lower() in low]
    return by_name[0] if len(by_name)==1 else None

def find_room(s,m,text):
    rooms=s.scalars(select(Room).where(Room.household_id==m.household_id)).all();low=text.lower()
    exact=[r for r in rooms if r.name.lower() in low]
    if len(exact)==1:return exact[0]
    # Do not collapse a specific but unknown room phrase (e.g. "Master Bathroom")
    # to the only configured generic room of that type (e.g. "Guest Bathroom").
    specific=re.findall(r'\b([a-z][a-z0-9_-]+)\s+(bathroom|washroom|bedroom|room)\b',low)
    generic_prefixes={'the','a','this','that','one','my','our'}
    if any(prefix not in generic_prefixes and not any(f'{prefix} {kind}' in r.name.lower() for r in rooms) for prefix,kind in specific):
        return None
    aliases={'kitchen':['kitchen','rasoi','रसोई'],'bathroom':['bathroom','washroom','toilet','बाथरूम'],
             'terrace':['terrace','roof','chhat','छत'],'bedroom':['bedroom','बेडरूम'],'living':['living','drawing']}
    hits=[]
    for r in rooms:
        values=[r.kind.lower(),r.name.lower()]+aliases.get(r.kind.lower(),[])
        if any(v and v in low for v in values):hits.append(r)
    return hits[0] if len(hits)==1 else None

def create_task_from_owner(s,m,text,hi):
    if not household_for(s,m).setup_completed:
        return ('Pehle virtual house setup complete karte hain. Rooms aur staff scope define hone ke baad hi main location-based tasks assign karunga.' if hi else
                'First complete the virtual house setup. I will only assign location-based work after rooms and staff scopes are defined.'),None,'SETUP_REQUIRED'
    staff=find_member(s,m,text);room=find_room(s,m,text);low=text.lower()
    if not staff:return ('Kisko assign karna hai — maid ya cook?' if hi else 'Who should I assign this to — maid or cook?'),None,'CLARIFY_ASSIGNEE'
    room_words=['kitchen','bathroom','washroom','bedroom','terrace','room','rasoi','chhat','रसोई','बाथरूम','छत','living']
    mentions_room=any(w in low for w in room_words)
    if mentions_room and not room:return ('Room clear nahi hai. Virtual house mein configured exact room naam batayein.' if hi else 'I need the exact configured room name before assigning this task.'),None,'CLARIFY_ROOM'
    if room:
        scopes=s.scalars(select(StaffScope).where(StaffScope.household_id==m.household_id,StaffScope.member_id==staff.id,StaffScope.can_execute_tasks==True)).all()
        if scopes and not any((x.room_id==room.id) or (x.floor_id and x.floor_id==room.floor_id) for x in scopes):
            return (f'{staff.name} ko {room.name} ka access scope nahi diya gaya hai.' if hi else f'{staff.name} is not permitted to execute tasks in {room.name}.'),None,'SCOPE_DENIED'
    category='COOKING' if staff.role=='cook' or any(w in low for w in ['cook','dinner','lunch','breakfast','khana','खाना']) else 'CLEANING'
    action='Prepare meal' if category=='COOKING' else 'Clean';title=f'{action} {room.name}' if room else text.strip()[:180]
    if category=='COOKING' and room is None:title='Prepare requested meal / kitchen task'
    t=Task(household_id=m.household_id,room_id=room.id if room else None,assignee_id=staff.id,title=title,category=category,
           notes=f'Created by JARVIS from: {text}',source='JARVIS');s.add(t);s.flush();audit(s,m,'jarvis.task.created',t.id)
    return ((f'Task bana diya: {staff.name} ko “{title}”. Aaj ke plan mein add ho gaya.' if hi else f'Assigned “{title}” to {staff.name}. It is now in today’s plan.')),t.id,'CREATE_TASK'

def household_context(s:Session,m:Member):
    """Assemble a permission-scoped, factual household context for JARVIS.

    This is the grounding layer. Conversational responses may summarize these
    records, but must not invent household entities that are absent here.
    """
    h=household_for(s,m)
    prop=s.scalar(select(Property).where(Property.household_id==m.household_id))
    floors=s.scalars(select(Floor).where(Floor.household_id==m.household_id).order_by(Floor.sort_order)).all()
    rooms=s.scalars(select(Room).where(Room.household_id==m.household_id)).all()
    zones=s.scalars(select(Zone).where(Zone.household_id==m.household_id)).all()
    assets=s.scalars(select(Asset).where(Asset.household_id==m.household_id)).all()
    members=s.scalars(select(Member).where(Member.household_id==m.household_id)).all()
    tasks=active_tasks(s,m)
    issues=s.scalars(select(Issue).where(Issue.household_id==m.household_id,Issue.status!='CLOSED')).all()
    recent=s.scalars(select(Message).where(Message.household_id==m.household_id,Message.member_id==m.id).order_by(Message.created_at.desc()).limit(8)).all()[::-1]
    floor_map={f.id:f for f in floors}; room_map={r.id:r for r in rooms}
    return {
        'household':{'id':h.id,'name':h.name,'mode':'OPERATIONAL' if h.setup_completed else 'SETUP'},
        'property':{'id':prop.id,'name':prop.name,'property_type':prop.property_type} if prop else None,
        'floors':[{'id':f.id,'name':f.name,'kind':f.kind,'sort_order':f.sort_order} for f in floors],
        'rooms':[{'id':r.id,'name':r.name,'kind':r.kind,'floor_id':r.floor_id,'floor_name':floor_map.get(r.floor_id).name if floor_map.get(r.floor_id) else None} for r in rooms],
        'zones':[{'id':z.id,'name':z.name,'kind':z.kind,'room_id':z.room_id,'room_name':room_map.get(z.room_id).name if room_map.get(z.room_id) else None} for z in zones],
        'assets':[{'id':a.id,'name':a.name,'asset_type':a.asset_type,'status':a.status,'room_id':a.room_id,'room_name':room_map.get(a.room_id).name if room_map.get(a.room_id) else None} for a in assets],
        'staff':[{'id':x.id,'name':x.name,'role':x.role} for x in members if x.role!='owner'],
        'tasks':[task_json(t) for t in tasks],
        'issues':[{'id':x.id,'description':x.description,'status':x.status} for x in issues],
        'recent_messages':[{'text':x.content,'reply':x.reply,'intent':x.intent} for x in recent],
        'viewer':{'id':m.id,'name':m.name,'role':m.role},
    }

def _norm(text:str)->str:
    return re.sub(r'[^a-z0-9\u0900-\u097f ]+',' ',text.lower()).strip()

def _mentioned_floor(ctx,text):
    low=_norm(text)
    matches=[f for f in ctx['floors'] if _norm(f['name']) and _norm(f['name']) in low]
    if len(matches)==1:return matches[0]
    # common ordinal aliases
    aliases={'ground':['ground floor','ground','gf'],'first':['first floor','1st floor'],'second':['second floor','2nd floor'],'third':['third floor','3rd floor'],'fourth':['fourth floor','4th floor']}
    for key,vals in aliases.items():
        if any(v in low for v in vals):
            hits=[f for f in ctx['floors'] if key in _norm(f['name'])]
            if len(hits)==1:return hits[0]
    return None

def _mentioned_room(ctx,text):
    low=_norm(text)
    hits=[r for r in ctx['rooms'] if _norm(r['name']) and _norm(r['name']) in low]
    return hits[0] if len(hits)==1 else None

def _format_names(items,limit=12):
    names=[x['name'] for x in items]
    if not names:return ''
    if len(names)<=limit:return ', '.join(names)
    return ', '.join(names[:limit])+f', and {len(names)-limit} more'

def answer_household_question(s,m,text,hi):
    """Answer factual household questions from the digital twin and live state.

    Returns (reply, action_ref, intent) or None when the message is not a
    household-information question.
    """
    ctx=household_context(s,m);low=_norm(text)
    rooms=ctx['rooms'];floors=ctx['floors'];assets=ctx['assets'];tasks=ctx['tasks'];issues=ctx['issues']

    # Room / space counts
    asks_count=any(x in low for x in ['how many','count','kitne','kitni','कितने','कितनी'])
    if asks_count and any(x in low for x in ['room','rooms','kamre','कमरे']):
        by_floor={}
        for r in rooms: by_floor[r['floor_name'] or 'Unassigned']=by_floor.get(r['floor_name'] or 'Unassigned',0)+1
        breakdown=', '.join(f'{k}: {v}' for k,v in by_floor.items())
        if hi:return f'HomeOS mein {len(rooms)} configured rooms hain. Breakdown: {breakdown}.',None,'HOUSE_QUERY_ROOM_COUNT'
        return f'You have {len(rooms)} configured rooms in HomeOS. Breakdown: {breakdown}.',None,'HOUSE_QUERY_ROOM_COUNT'

    # Bathroom count/list
    if ('bathroom' in low or 'washroom' in low or 'toilet' in low or 'बाथरूम' in low) and (asks_count or any(x in low for x in ['which','list','kaun','कौन'])):
        baths=[r for r in rooms if r['kind'].lower() in {'bathroom','washroom','toilet'} or any(k in r['name'].lower() for k in ['bathroom','washroom','toilet'])]
        if not baths:return ('Koi bathroom configured nahi hai.' if hi else 'No bathroom is currently configured in the digital twin.'),None,'HOUSE_QUERY_BATHROOMS'
        names=_format_names(baths)
        return ((f'{len(baths)} bathrooms configured hain: {names}.' if hi else f'{len(baths)} bathrooms are configured: {names}.')),None,'HOUSE_QUERY_BATHROOMS'

    # Floors / spaces
    if any(x in low for x in ['how many floor','floors','kitne floor','कितने फ्लोर']):
        physical=[f for f in floors if f['kind']=='floor'];spaces=[f for f in floors if f['kind']!='floor']
        extra=f" Additional spaces: {_format_names(spaces)}." if spaces else ''
        return ((f'{len(physical)} floors configured hain. {_format_names(physical)}.{extra}' if hi else f'{len(physical)} floors are configured: {_format_names(physical)}.{extra}')),None,'HOUSE_QUERY_FLOORS'

    floor=_mentioned_floor(ctx,text)
    if floor and any(x in low for x in ['what','which','kya','kaun','क्या','कौन','have','hai','hain','rooms']):
        rs=[r for r in rooms if r['floor_id']==floor['id']]
        if not rs:return (f'{floor["name"]} mein abhi koi room configured nahi hai.' if hi else f'No rooms are configured under {floor["name"]}.'),floor['id'],'HOUSE_QUERY_FLOOR_CONTENTS'
        return ((f'{floor["name"]} mein {len(rs)} configured spaces/rooms hain: {_format_names(rs)}.' if hi else f'{floor["name"]} has {len(rs)} configured rooms/spaces: {_format_names(rs)}.')),floor['id'],'HOUSE_QUERY_FLOOR_CONTENTS'

    room=_mentioned_room(ctx,text)
    if room and any(x in low for x in ['asset','assets','appliance','appliances','kya hai','what is','what are','what do','configured']):
        aa=[a for a in assets if a['room_id']==room['id']]
        if not aa:return (f'{room["name"]} mein koi asset registered nahi hai.' if hi else f'No assets are registered in {room["name"]}.'),room['id'],'HOUSE_QUERY_ROOM_ASSETS'
        return ((f'{room["name"]} mein {len(aa)} assets registered hain: {_format_names(aa)}.' if hi else f'{room["name"]} has {len(aa)} registered assets: {_format_names(aa)}.')),room['id'],'HOUSE_QUERY_ROOM_ASSETS'

    if any(x in low for x in ['pending','open task','current task','aaj kya','today task','what is pending','what s pending']):
        if not tasks:return ('Abhi koi pending task nahi hai.' if hi else 'There are no pending tasks right now.'),None,'HOUSE_QUERY_TASKS'
        staff={x['id']:x['name'] for x in ctx['staff']}
        detail=[]
        for t in tasks[:10]: detail.append(f"{t['title']} — {staff.get(t['assignee_id'],'Unassigned')} ({t['status']})")
        prefix=f'{len(tasks)} pending tasks hain: ' if hi else f'{len(tasks)} pending tasks: '
        return prefix+'; '.join(detail),None,'HOUSE_QUERY_TASKS'

    if any(x in low for x in ['open issue','repair issue','issues','problems','problem open','koi issue','koi problem']):
        if not issues:return ('Koi open issue nahi hai.' if hi else 'There are no open household issues.'),None,'HOUSE_QUERY_ISSUES'
        return ((f'{len(issues)} open issues hain: ' if hi else f'{len(issues)} open issues: ')+ '; '.join(x['description'] for x in issues[:8])),None,'HOUSE_QUERY_ISSUES'

    # Contextual follow-up: "which one is outside?" after bathroom discussion.
    if any(x in low for x in ['outside','bahar','बाहर']) and any(x in low for x in ['which','kaun','कौन','one']):
        recent=' '.join((x['text']+' '+x['reply']).lower() for x in ctx['recent_messages'][-4:])
        if 'bathroom' in recent or 'washroom' in recent:
            baths=[r for r in rooms if r['kind'].lower() in {'bathroom','washroom','toilet'} or 'bathroom' in r['name'].lower()]
            outside=[r for r in baths if any(k in r['name'].lower() for k in ['outside','outdoor','external','bahar'])]
            if outside:return ((f'Outside bathroom: {_format_names(outside)}.' if hi else f'The outside bathroom is: {_format_names(outside)}.')),outside[0]['id'],'HOUSE_QUERY_FOLLOWUP'
            return ('Bathroom list mein koi room explicitly outside mark nahi hai.' if hi else 'None of the configured bathrooms is explicitly marked as outside.'),None,'HOUSE_QUERY_FOLLOWUP'
    return None

def interpret(m,text,s):
    low=text.lower().strip();hi=is_hinglish(text);h=household_for(s,m)
    if not h.setup_completed:
        return ('Virtual house setup abhi complete nahi hai. Pehle property, floors, rooms aur staff access configure karein.' if hi else
                'Virtual house setup is not complete yet. Configure the property, floors, rooms, and staff access first.'),None,'SETUP_REQUIRED'

    # Read-only questions are answered first from the actual household context.
    from app.memory_bridge import memory_location_answer
    graph_fact=memory_location_answer(s,m,text,hi)
    if graph_fact:return graph_fact
    factual=answer_household_question(s,m,text,hi)
    if factual:return factual

    if any(w in low for w in ['leak','paani','tapak','टपक','लीक','पानी','broken','kharab','खराब']):
        x=Issue(household_id=m.household_id,reporter_id=m.id,description=text);s.add(x);s.flush();audit(s,m,'issue.reported.chat',x.id)
        return (('Issue note kar liya. Safe distance se photo bhejein. Bijli/gas ka risk ho toh kaam rok dein.' if hi else 'Issue recorded. Share a safe photo and stop work if electricity or gas is involved.')),x.id,'REPORT_ISSUE'
    if m.role=='owner' and any(w in low for w in ['assign','lagao','karwa','करवा','kar do','कर दो','clean','saaf','साफ','cook','banao','बनाओ']):return create_task_from_owner(s,m,text,hi)
    if any(w in low for w in ['today','tasks','aaj','kaam','आज','काम']):
        ts=active_tasks(s,m)
        if not ts:return ('Aaj koi pending task nahi hai.' if hi else 'No pending tasks right now.'),None,'LIST_TASKS'
        body='; '.join(f'{i+1}. {t.title} ({t.status})' for i,t in enumerate(ts[:10]));return (('Aaj ke tasks: ' if hi else 'Current tasks: ')+body),None,'LIST_TASKS'
    if any(w in low for w in ['done','complete','ho gaya','हो गया','finished']):
        ts=active_tasks(s,m)
        if m.role=='owner':return ('Owner view mein task select karke verify karein.' if hi else 'Select the submitted task to verify it.'),None,'COMPLETE_TASK'
        candidates=[t for t in ts if t.status in {'ASSIGNED','IN_PROGRESS','REWORK_REQUIRED'}]
        if len(candidates)!=1:return ('Kaunsa task complete hua? Task ka naam batayein.' if hi else 'Which task did you complete? Please mention the task name.'),None,'CLARIFY_TASK'
        t=candidates[0]
        if t.status=='ASSIGNED':t.status='IN_PROGRESS'
        t.status='SUBMITTED';audit(s,m,'jarvis.task.submitted',t.id)
        return ('Task submit kar diya. Ab completion photo bhejiye.' if hi else 'Task submitted. Please attach a completion photo.'),t.id,'SUBMIT_TASK'
    if any(w in low for w in ['how','kaise','कैसे','guide','help','madad','मदद']):
        ts=active_tasks(s,m)
        if not ts:return ('Abhi koi active task nahi hai.' if hi else 'There is no active task right now.'),None,'GUIDANCE'
        t=ts[0];guidance=('Pehle area clear karein, suitable cleaning material use karein, unsafe chemical mixing na karein, aur completion ke baad photo bhejein.' if hi else 'Clear the area first, use the appropriate cleaning material, never mix unsafe chemicals, and send a completion photo when done.')
        return f'{t.title}: {guidance}',t.id,'GUIDANCE'
    return ('Main aapke configured virtual house, tasks, staff aur issues ke context se answer karta hoon. Specific household question poochiye ya task assign kijiye.' if hi else 'I can answer from your configured virtual house, tasks, staff, and open issues. Ask a specific household question or assign work.'),None,'GENERAL_CONTEXTUAL'

class ChatIn(BaseModel): text:str=Field(min_length=1,max_length=2000)
@app.post('/api/chat')
def chat(p:ChatIn,m:Member=Depends(actor),s:Session=Depends(db)):
    reply,action_ref,intent=interpret(m,p.text,s);x=Message(household_id=m.household_id,member_id=m.id,content=p.text,reply=reply,intent=intent,action_ref=action_ref)
    s.add(x);s.flush();audit(s,m,'chat.message',x.id);s.commit();return {'id':x.id,'reply':reply,'mode':'JARVIS_DETERMINISTIC','language':'mixed','intent':intent,'action_ref':action_ref}

@app.get('/api/chat/history')
def history(m:Member=Depends(actor),s:Session=Depends(db)):
    xs=s.scalars(select(Message).where(Message.household_id==m.household_id,Message.member_id==m.id).order_by(Message.created_at.desc()).limit(50)).all()[::-1]
    return [{'id':x.id,'text':x.content,'reply':x.reply,'intent':x.intent,'action_ref':x.action_ref,'at':x.created_at.isoformat()} for x in xs]

@app.get('/api/context')
def context(m:Member=Depends(actor),s:Session=Depends(db)):
    return household_context(s,m)

@app.post('/api/memory/sync')
def sync_memory(m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    from app.memory_bridge import project
    result=project(s,m.household_id)
    audit(s,m,'memory.projection.completed',str(result['counts']))
    s.commit()
    return result

@app.get('/api/memory/overview')
def get_memory_overview(m:Member=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    from app.memory_bridge import overview
    return overview(s,m.household_id)

@app.get('/api/health')
def health():return {'status':'ok','mode':'homeos-jarvis-m2c-contextual','version':'0.4.0'}

# M3E owner-review endpoints are imported after demo actor and ORM definitions.
from importlib import import_module as _import_review_module
_import_review_module('app.visual_review')
