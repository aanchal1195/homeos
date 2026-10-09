"""Authorized, bounded household tools for the M4C reasoning agent.

All tools are explicit functions of the active SQLAlchemy session and current
member. They never accept SQL, file paths, external URLs, or arbitrary code.
The existing M2C tables remain authoritative for operations; only confirmed
Memory Graph assertions supply recorded locations/provenance.
"""
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select

from app.grounded_jarvis import _place_path
from app.memory_bridge import _run, _uuid, supported


class Args(BaseModel):
    model_config=ConfigDict(extra="forbid")


class FindArgs(Args):
    query:str=Field(min_length=2,max_length=110)


class IdArgs(Args):
    id:str=Field(min_length=16,max_length=80)


class PlanArgs(Args):
    room_id:str=Field(min_length=16,max_length=80)
    assignee_id:str=Field(min_length=16,max_length=80)
    instruction:str=Field(default="",max_length=450)


class ReviseArgs(Args):
    plan_id:str=Field(min_length=16,max_length=80)
    room_id:str|None=None
    assignee_id:str|None=None
    instruction:str|None=None


def _owner(m):
    if m.role!="owner":
        raise HTTPException(403,"Household reasoning tools are owner-only in this local MVP")


def _scoped(s,cls,id,m):
    from app.main import scoped
    try:
        return scoped(s,cls,str(UUID(id)),m)
    except (ValueError,TypeError):
        raise HTTPException(422,"Select an entity ID returned by a household tool")


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def find_entities(s,m,arg:FindArgs):
    from app.main import Room, Asset, Member
    _owner(m)
    q=arg.query.casefold().strip()
    # Match recorded names, not speculative embeddings; ambiguity is explicit.
    result=[]
    classes=((Room,"room"),(Asset,"asset"),(Member,"staff"))
    for cls,kind in classes:
        if kind=="staff" and q in ("everyone","everything"):
            continue
        entries=s.scalars(select(cls).where(cls.household_id==m.household_id).order_by(cls.name).limit(400)).all()
        for item in entries:
            if q in item.name.casefold() or (kind=="asset" and
                 q in item.name.casefold().split()):
                data={"id":item.id,"kind":kind,"name":item.name}
                if kind=="staff":data["role"]=item.role
                result.append(data)
    # Registered but unresolved does not mean physically absent.
    return {"query":arg.query,"matches":result[:14],"truncated":len(result)>14,
            "unknown_if_empty":"No matching registered entity; physical presence is unverified.",
            "instructions":"If multiple matches, ask the owner which exact item/room. Do not guess."}


def get_room(s,m,arg:IdArgs):
    from app.main import Room, Floor, Zone, Asset
    _owner(m)
    room=_scoped(s,Room,arg.id,m)
    floor=s.get(Floor,room.floor_id) if room.floor_id else None
    assets=s.scalars(select(Asset).where(Asset.household_id==m.household_id,Asset.room_id==room.id)
                    .order_by(Asset.name).limit(45)).all()
    zones=s.scalars(select(Zone).where(Zone.household_id==m.household_id,Zone.room_id==room.id)
                   .order_by(Zone.name).limit(30)).all()
    return {"room":{"id":room.id,"name":room.name,"kind":room.kind,
                    "floor_name":floor.name if floor and floor.household_id==m.household_id else None},
            "registered_assets":[{"id":a.id,"name":a.name,"status":a.status} for a in assets],
            "registered_zones":[{"id":z.id,"name":z.name} for z in zones],
            "quantity_note":"This is a count of registered records, not a verified physical inventory.",
            "registered_asset_count_shown":len(assets),"truncated":len(assets)>=45}


def get_asset(s,m,arg:IdArgs):
    from app.main import Asset, Room
    _owner(m)
    asset=_scoped(s,Asset,arg.id,m)
    operational_room=_scoped(s,Room,asset.room_id,m)
    memory={"status":"NOT_AVAILABLE","location":None,"provenance":None}
    if supported(s):
        link=_run(s,"""SELECT entity_id FROM memory_legacy_links
          WHERE household_id=:house AND legacy_type='asset' AND legacy_id=:id""",
          house=_uuid(m.household_id),id=asset.id).scalar_one_or_none()
        if link:
            path=_place_path(s,_uuid(m.household_id),link)
            if path:
                step=path[0]
                memory={"status":"LAST_RECORDED","entity_id":str(link),
                        "location":" → ".join(p["canonical_name"] for p in path),
                        "source_type":step["source_type"],"source_ref":step["source_ref"],
                        "last_recorded_at":_iso(step["recorded_at"]),
                        "owner_verified":step["source_type"]=="OWNER",
                        "observation_id":(step["source_ref"].removeprefix("visual-review:")
                                          if (step["source_ref"] or "").startswith("visual-review:") else None)}
            else:
                memory={"status":"NO_CONFIRMED_LOCATION","entity_id":str(link),
                        "location":None}
    return {"asset":{"id":asset.id,"name":asset.name,"asset_type":asset.asset_type,
             "status":asset.status,"next_service":asset.next_service},
            "operational_room_record":operational_room.name,
            "memory_location":memory,
            "quantity":"UNKNOWN: HomeOS has no physical quantity ledger for this asset.",
            "caveat":"Recorded position is not a live sensor. Do not infer location from operational room when graph has no confirmed assertion."}


def get_asset_history(s,m,arg:IdArgs):
    from app.main import Asset
    _owner(m)
    asset=_scoped(s,Asset,arg.id,m)
    if not supported(s):
        return {"asset":asset.name,"history":[],"unavailable":"Home Memory Graph is disabled"}
    house=_uuid(m.household_id)
    link=_run(s,"""SELECT entity_id FROM memory_legacy_links
         WHERE household_id=:house AND legacy_type='asset' AND legacy_id=:id""",
         house=house,id=asset.id).scalar_one_or_none()
    if not link:return {"asset":asset.name,"history":[],"unknown":"Not yet synchronized"}
    rows=_run(s,"""SELECT a.id,a.verification_status,a.recorded_at,a.valid_until,
        e.canonical_name AS location_name,v.source_type,v.source_ref
        FROM memory_assertions a
        JOIN memory_entities e ON e.id=a.object_id AND e.household_id=a.household_id
        JOIN memory_evidence v ON v.id=a.evidence_id AND v.household_id=a.household_id
        WHERE a.household_id=:house AND a.subject_id=:asset AND a.predicate IN ('LOCATED_IN','STORED_IN')
          AND a.verification_status IN ('CONFIRMED','SUPERSEDED')
        ORDER BY a.recorded_at DESC,a.id DESC LIMIT 15""",
        house=house,asset=link).mappings().all()
    return {"asset":asset.name,"memory_entity_id":str(link),
        "location_history":[{
          "location":x["location_name"],"state":x["verification_status"],
          "source":x["source_type"],"evidence_ref":x["source_ref"],
          "recorded_at":_iso(x["recorded_at"]),"superseded_at":_iso(x["valid_until"])
        } for x in rows],
        "caveat":"Chronological recorded evidence, not a real-time physical verification."}


def get_tasks_for_room(s,m,arg:IdArgs):
    from app.main import Room,Task,Member
    _owner(m)
    room=_scoped(s,Room,arg.id,m)
    records=s.scalars(select(Task).where(Task.household_id==m.household_id,
              Task.room_id==room.id,Task.status!="CLOSED")
              .order_by(Task.due_date,Task.created_at).limit(25)).all()
    names={x.id:x.name for x in s.scalars(select(Member).where(
             Member.household_id==m.household_id)).all()}
    return {"room_id":room.id,"room_name":room.name,
      "open_tasks":[{"id":t.id,"title":t.title,"status":t.status,
                     "assigned_to":names.get(t.assignee_id,"UNKNOWN"),
                     "due_date":t.due_date,
                     "notes_untrusted_data":(t.notes or "")[:180]}
                     for t in records],
      "limit":25,"truncated":len(records)>=25,
      "unknown":"An empty list means no open task was recorded, not that the room is clean."}


def eligible_staff_for_room(s,m,arg:IdArgs):
    from app.main import Room,Member,StaffScope
    from app.home_manager import _permission
    _owner(m)
    room=_scoped(s,Room,arg.id,m)
    maids=s.scalars(select(Member).where(Member.household_id==m.household_id,
                      Member.role=="maid").order_by(Member.name)).all()
    eligible=[]
    for person in maids:
        try:
            _permission(s,m,room,person)
            eligible.append({"id":person.id,"name":person.name,"role":person.role,
                 "scope":"allowed for room cleaning",
                 "availability":"UNKNOWN — HomeOS has no staff calendar or shift roster"})
        except HTTPException:
            continue
    return {"room_id":room.id,"room_name":room.name,"eligible":eligible[:20],
            "truncated":len(eligible)>20,
            "caveat":"Execution permission is not staff availability. Do not claim a staff member is free."}


def read_plan(s,m,arg:IdArgs):
    from app.main import HomeManagerPlan
    from app.home_manager import _present
    _owner(m)
    plan=_scoped(s,HomeManagerPlan,arg.id,m)
    return _present(s,plan)


def propose_cleaning(s,m,arg:PlanArgs):
    from app.main import HomeManagerPlan
    from app.home_manager import RoomCleaningPlanIn,propose_room_cleaning
    _owner(m)
    # Reuse an existing unconfirmed proposal for identical scope instead of
    # manufacturing duplicates on model retries.
    prior=s.scalar(select(HomeManagerPlan).where(
        HomeManagerPlan.household_id==m.household_id,
        HomeManagerPlan.owner_id==m.id,
        HomeManagerPlan.room_id==arg.room_id,
        HomeManagerPlan.assignee_id==arg.assignee_id,
        HomeManagerPlan.status=="PROPOSED"
    ).order_by(HomeManagerPlan.created_at.desc()))
    if prior:
        from app.home_manager import _present
        return {"plan":_present(s,prior),"reused":True,
                "next_step":"OWNER MUST CONFIRM IN HOME MANAGER UI. No task assigned."}
    plan=propose_room_cleaning(RoomCleaningPlanIn(room_id=arg.room_id,
          assignee_id=arg.assignee_id,instruction=arg.instruction),m,s)
    return {"plan":plan,"reused":False,
            "next_step":"OWNER MUST CONFIRM IN HOME MANAGER UI. No task assigned."}


def revise_cleaning(s,m,arg:ReviseArgs):
    from app.home_manager import revise_room_cleaning,RoomCleaningPlanPatch
    _owner(m)
    result=revise_room_cleaning(arg.plan_id,RoomCleaningPlanPatch(
        room_id=arg.room_id,assignee_id=arg.assignee_id,instruction=arg.instruction),m,s)
    return {"plan":result,"next_step":"Draft only; OWNER confirmation still required."}


TOOL_ARGS={
    "find_entities":FindArgs,
    "get_room":IdArgs,
    "get_asset":IdArgs,
    "get_asset_history":IdArgs,
    "get_room_tasks":IdArgs,
    "eligible_staff_for_room":IdArgs,
    "read_plan":IdArgs,
    "propose_cleaning":PlanArgs,
    "revise_cleaning":ReviseArgs,
}
READ_TOOLS={"find_entities","get_room","get_asset","get_asset_history",
            "get_room_tasks","eligible_staff_for_room","read_plan"}
WRITABLE_PROPOSALS={"propose_cleaning","revise_cleaning"}
HANDLERS={"find_entities":find_entities,"get_room":get_room,"get_asset":get_asset,
          "get_asset_history":get_asset_history,"get_room_tasks":get_tasks_for_room,
          "eligible_staff_for_room":eligible_staff_for_room,"read_plan":read_plan,
          "propose_cleaning":propose_cleaning,"revise_cleaning":revise_cleaning}
DESCRIPTIONS={
    "find_entities":"Find registered rooms, objects and staff by partial name; returns IDs and ambiguity, not physical presence.",
    "get_room":"Get a registered room's floor, zones and recorded assets. Requires a real room ID from find_entities.",
    "get_asset":"Get an asset's operational condition, maintenance date, and recorded Memory Graph location/provenance. Requires an asset ID.",
    "get_asset_history":"Get temporal verified and superseded location assertions and evidence for an asset ID.",
    "get_room_tasks":"Get outstanding recorded operational tasks in a specific room, with status, due dates and assignees.",
    "eligible_staff_for_room":"Find maids permitted to clean a room; actual schedule availability is NOT tracked.",
    "read_plan":"Fetch existing cleaning plan and follow-up by plan ID. Owner-only.",
    "propose_cleaning":"Create a PROPOSED room-cleaning draft after checking room, open tasks and eligible staff. NEVER assigns a task; owner must confirm in UI.",
    "revise_cleaning":"Revise an existing unconfirmed cleaning-plan draft after the owner requests a change. Never assigns work.",
}
PROPERTIES={
    "find_entities":{"query":{"type":"string"}},
    "get_room":{"id":{"type":"string"}},"get_asset":{"id":{"type":"string"}},
    "get_asset_history":{"id":{"type":"string"}},
    "get_room_tasks":{"id":{"type":"string"}},
    "eligible_staff_for_room":{"id":{"type":"string"}},
    "read_plan":{"id":{"type":"string"}},
    "propose_cleaning":{"room_id":{"type":"string"},"assignee_id":{"type":"string"},
                        "instruction":{"type":"string"}},
    "revise_cleaning":{"plan_id":{"type":"string"},"room_id":{"type":"string"},
                       "assignee_id":{"type":"string"},"instruction":{"type":"string"}},
}
REQUIRED={
    "find_entities":["query"],"get_room":["id"],"get_asset":["id"],
    "get_asset_history":["id"],"get_room_tasks":["id"],
    "eligible_staff_for_room":["id"],"read_plan":["id"],
    "propose_cleaning":["room_id","assignee_id"],
    "revise_cleaning":["plan_id"],
}


def openai_tool_specs(*,allow_proposals):
    selected=READ_TOOLS | (WRITABLE_PROPOSALS if allow_proposals else set())
    return [{"type":"function","function":{
        "name":name,"description":DESCRIPTIONS[name],
        "parameters":{"type":"object","properties":PROPERTIES[name],
                      "required":REQUIRED[name],"additionalProperties":False}
    }} for name in HANDLERS if name in selected]


def execute(s,m,name,payload,*,allow_proposals):
    _owner(m)
    if name not in HANDLERS or (name in WRITABLE_PROPOSALS and not allow_proposals):
        raise HTTPException(403,"Tool not permitted for this request")
    model=TOOL_ARGS[name].model_validate(payload)
    return HANDLERS[name](s,m,model)
