"""M3D: deterministic projection of HomeOS operational data to a household-scoped memory graph.

M2C tables remain authoritative. Projection is explicit, repeatable and transactional.
It never interprets an AI observation as a verified asset or overwrites a verified
physical location outside the legacy authority's current state.
"""
import os
import re
import uuid
from collections import Counter
from sqlalchemy import text
from fastapi import HTTPException

KEYWORDS={"fridge":"refrigerator","refrigerator":"refrigerator","ro":"water purifier",
          "geyser":"water heater","washer":"washing machine"}


def enabled():
    return os.getenv('HOMEOS_MEMORY_ENABLED','false').lower()=='true'


def supported(session):
    return enabled() and session.bind.dialect.name == 'postgresql'


def _uuid(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError):raise HTTPException(422,'Invalid household identifier for memory graph')


def _run(s, statement, **params):
    return s.execute(text(statement), params)


def _link(s, house, source, obj, kind, attrs):
    """Upsert a legacy record into memory_entities through a stable link mapping."""
    prior=_run(s,"""SELECT entity_id FROM memory_legacy_links
               WHERE household_id=:house AND legacy_type=:typ AND legacy_id=:legacy""",
               house=house,typ=source,legacy=obj.id).scalar_one_or_none()
    if prior:
        _run(s,"""UPDATE memory_entities SET canonical_name=:name,entity_type=:kind,
                attributes=attributes || CAST(:attrs AS jsonb) WHERE household_id=:house AND id=:id""",
             name=obj.name,kind=kind,attrs=attrs,house=house,id=prior)
        return prior,False
    entity=_run(s,"""INSERT INTO memory_entities(household_id,entity_type,canonical_name,attributes)
                   VALUES(:house,:kind,:name,CAST(:attrs AS jsonb)) RETURNING id""",
                house=house,kind=kind,name=obj.name,attrs=attrs).scalar_one()
    _run(s,"""INSERT INTO memory_legacy_links(household_id,legacy_type,legacy_id,entity_id)
               VALUES(:house,:typ,:legacy,:eid)""",
         house=house,typ=source,legacy=obj.id,eid=entity)
    return entity,True


def _relate(s,house,subject,predicate,parent,source_ref):
    if parent is None or subject==parent:return False
    old=_run(s,"""SELECT a.id,a.object_id,e.source_type,e.source_ref FROM memory_assertions a
          JOIN memory_evidence e ON e.id=a.evidence_id AND e.household_id=a.household_id
          WHERE a.household_id=:house AND subject_id=:subject AND predicate=:predicate
            AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL FOR UPDATE OF a""",
         house=house,subject=subject,predicate=predicate).mappings().all()
    if len(old)==1 and old[0]['object_id']==parent:return False
    if any(x['source_type']!='SYSTEM' or not (x['source_ref'] or '').startswith('M2C:') for x in old):
        # Do not discard an independently owner-verified physical location.
        pending=_run(s,"""SELECT 1 FROM memory_observations WHERE household_id=:house
          AND subject_id=:subject AND candidate_object_id=:parent
          AND predicate=:predicate AND status='PENDING'
          AND payload->>'reason'='M2C graph projection conflicts with verified memory' LIMIT 1""",
          house=house,subject=subject,parent=parent,predicate=predicate).first()
        if not pending:
            ev=_run(s,"""INSERT INTO memory_evidence(household_id,source_type,source_ref)
              VALUES(:house,'SYSTEM',:ref) RETURNING id""",house=house,ref=source_ref).scalar_one()
            _run(s,"""INSERT INTO memory_observations
             (household_id,subject_id,predicate,candidate_object_id,evidence_id,payload)
             VALUES(:house,:subject,:predicate,:parent,:evidence,CAST(:payload AS jsonb))""",
             house=house,subject=subject,predicate=predicate,parent=parent,evidence=ev,
             payload='{"reason":"M2C graph projection conflicts with verified memory"}')
        return False
    for row in old:
        _run(s,"""UPDATE memory_assertions SET verification_status='SUPERSEDED',valid_until=now()
                  WHERE household_id=:house AND id=:id""",house=house,id=row['id'])
    evidence=_run(s,"""INSERT INTO memory_evidence(household_id,source_type,source_ref)
              VALUES(:house,'SYSTEM',:ref) RETURNING id""",house=house,ref=source_ref).scalar_one()
    assertion=_run(s,"""INSERT INTO memory_assertions(household_id,subject_id,predicate,
                   object_id,evidence_id,verification_status,supersedes_id)
             VALUES(:house,:subject,:predicate,:parent,:evidence,'CONFIRMED',:supersedes) RETURNING id""",
              house=house,subject=subject,predicate=predicate,parent=parent,evidence=evidence,
              supersedes=old[0]['id'] if len(old)==1 else None).scalar_one()
    if predicate=='LOCATED_IN':
        payload={'previous_location_ids':[str(row['object_id']) for row in old],
                 'location_id':str(parent),'source':'M2C_LEGACY_PROJECTION'}
        _run(s,"""INSERT INTO memory_events(household_id,event_type,subject_id,payload,idempotency_key)
                 VALUES(:house,'LOCATION_PROJECTED',:subject,CAST(:payload AS jsonb),:key)
                 ON CONFLICT(household_id,idempotency_key) DO NOTHING""",
             house=house,subject=subject,payload=__import__('json').dumps(payload),key=f'm2c:projection:{assertion}')
    return True


def project(s, household_id):
    """Transaction-bound graph projection. Caller commits on success; otherwise rollback."""
    if not supported(s):raise HTTPException(503,'Home Memory is not configured for this database')
    from app.main import Property, Floor, Room, Zone, Asset
    from sqlalchemy import select
    house=_uuid(household_id)
    # Prevent concurrent writers from creating duplicate legacy links.
    _run(s,'SELECT pg_advisory_xact_lock(hashtext(:key))',key='homeos:memory:'+str(house))
    prop=s.scalar(select(Property).where(Property.household_id==household_id))
    floors=s.scalars(select(Floor).where(Floor.household_id==household_id).order_by(Floor.sort_order)).all()
    rooms=s.scalars(select(Room).where(Room.household_id==household_id)).all()
    zones=s.scalars(select(Zone).where(Zone.household_id==household_id)).all()
    assets=s.scalars(select(Asset).where(Asset.household_id==household_id)).all()
    totals=Counter();linked={}
    def put(source,obj,kind,attrs):
        import json
        ref,new=_link(s,house,source,obj,kind,json.dumps(attrs))
        linked[(source,obj.id)]=ref
        totals['created' if new else 'updated']+=1
        totals[kind]+=1
        return ref
    if prop:put('property',prop,'HOME',{'source':'M2C','property_type':prop.property_type,'address_label':prop.address_label})
    for item in floors:put('floor',item,'FLOOR' if item.kind=='floor' else 'SPACE',{'source':'M2C','kind':item.kind,'sort_order':item.sort_order})
    for item in rooms:put('room',item,'ROOM',{'source':'M2C','kind':item.kind,'floor':item.floor})
    for item in zones:put('zone',item,'ZONE',{'source':'M2C','kind':item.kind})
    for item in assets:put('asset',item,'ASSET',{'source':'M2C','asset_type':item.asset_type,'status':item.status,'next_service':item.next_service})
    def relation(kind,obj,pred,parent_kind,parent_id):
        if parent_id and (parent_kind,parent_id) in linked:
            if _relate(s,house,linked[(kind,obj.id)],pred,linked[(parent_kind,parent_id)],f'M2C:{kind}:{obj.id}'):
                totals['relationships_changed']+=1
    for f in floors:relation('floor',f,'PART_OF','property',f.property_id)
    for r in rooms:relation('room',r,'PART_OF','floor',r.floor_id)
    for z in zones:relation('zone',z,'PART_OF','room',z.room_id)
    for a in assets:relation('asset',a,'LOCATED_IN','zone' if a.zone_id else 'room',a.zone_id or a.room_id)
    return {'household_id':str(house),'counts':dict(totals),'mode':'M2C_AUTHORITATIVE_PROJECTION'}


def _clean_name(value):
    value=re.sub(r'[^\w\s]',' ',value.casefold())
    return ' '.join(value.split())


def _subject(text):
    """Read-only whereabouts detection, not an open-ended LLM or action parser."""
    query=text.strip()
    prefix=re.match(r'^(where\s+(?:is|are|was)\s+|where\x27s\s+|find\s+|locate\s+)(?:the\s+)?(.+?)\s*[?.!]*$',query,re.I)
    if prefix:name=prefix.group(2)
    else:
        suffix=re.match(r'^(?:the\s+)?(.+?)\s+(?:kahan|kahaan|kaha|kidhar|कहाँ|कहा)\s+(?:hai|hain|है|हैं)\s*[?.!]*$',query,re.I)
        if not suffix:return None
        name=suffix.group(1)
    n=_clean_name(name)
    return KEYWORDS.get(n,n) or None


def memory_location_answer(s,m,text_input,hi=False):
    """Owner-only graph lookup. Missing assets must never receive invented locations."""
    subject=_subject(text_input)
    if not subject or m.role!='owner':return None
    if not supported(s):return None  # caller uses existing non-memory logic when disabled
    house=_uuid(m.household_id)
    assets=_run(s,"""SELECT e.id,e.canonical_name
       FROM memory_entities e LEFT JOIN memory_aliases a
       ON a.entity_id=e.id AND a.household_id=e.household_id
       WHERE e.household_id=:house AND e.entity_type='ASSET' AND e.status='ACTIVE'
       AND (lower(e.canonical_name)=:name OR lower(a.alias)=:name OR lower(e.canonical_name) LIKE :part)
       ORDER BY e.canonical_name LIMIT 10""",house=house,name=subject,part="%"+subject+"%").mappings().all()
    unique={str(row['id']):row for row in assets}
    if not unique:
        answer=(f'{subject} Home Memory mein registered nahi hai.' if hi else
                f'{subject} is not registered in Home Memory.')
        return (answer,None,'MEMORY_NOT_REGISTERED')
    if len(unique)>1:
        return (f'Multiple assets match {subject}. Please specify which one.',None,'MEMORY_AMBIGUOUS')
    entity=next(iter(unique.values()))
    found=[];visited={entity['id']};cursor=entity['id']
    for step in range(12):
        path=_run(s,"""SELECT e.id,e.canonical_name,a.recorded_at,v.source_type
           FROM memory_assertions a
           JOIN memory_entities e ON e.id=a.object_id AND e.household_id=a.household_id
           JOIN memory_evidence v ON v.id=a.evidence_id AND v.household_id=a.household_id
           WHERE a.household_id=:house AND a.subject_id=:subject
             AND a.predicate IN ('LOCATED_IN','PART_OF')
             AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
           ORDER BY CASE WHEN a.predicate='LOCATED_IN' THEN 0 ELSE 1 END LIMIT 1""",
           house=house,subject=cursor).mappings().first()
        if not path or path['id'] in visited:break
        found.append(path);visited.add(path['id']);cursor=path['id']
    if not found:
        return (f'{entity["canonical_name"]} is registered, but its location has not been verified.',
                str(entity['id']),'MEMORY_LOCATION_UNKNOWN')
    label=' → '.join(p['canonical_name'] for p in found)
    answer=(f'{entity["canonical_name"]} ka recorded location: {label}. Source: verified Home Memory.' if hi
            else f'{entity["canonical_name"]} is recorded in {label} (verified Home Memory).')
    return (answer,str(entity['id']),'MEMORY_LOCATION')


def overview(s,household_id,limit=150):
    if not supported(s):raise HTTPException(503,'Home Memory is not configured')
    house=_uuid(household_id)
    rows=_run(s,"""SELECT e.id,e.entity_type,e.canonical_name,e.created_at,
          parent.canonical_name AS location_name, v.source_type AS location_source
          FROM memory_entities e LEFT JOIN memory_assertions a
            ON a.household_id=e.household_id AND a.subject_id=e.id
            AND a.predicate IN ('PART_OF','LOCATED_IN') AND a.verification_status='CONFIRMED' AND a.valid_until IS NULL
          LEFT JOIN memory_entities parent ON parent.household_id=e.household_id AND parent.id=a.object_id
          LEFT JOIN memory_evidence v ON v.household_id=e.household_id AND v.id=a.evidence_id
          WHERE e.household_id=:house AND e.status='ACTIVE'
          ORDER BY CASE e.entity_type WHEN 'HOME' THEN 0 WHEN 'FLOOR' THEN 1 WHEN 'SPACE' THEN 2 WHEN 'ROOM' THEN 3 WHEN 'ZONE' THEN 4 ELSE 5 END,
                   e.canonical_name LIMIT :limit""",house=house,limit=limit).mappings().all()
    return {'entities':[{'id':str(row['id']),'type':row['entity_type'],'name':row['canonical_name'],
                         'location':row['location_name'],'source':row['location_source']} for row in rows],
            'counts':dict(Counter(row['entity_type'] for row in rows)),'authoritative_source':'M2C'}
