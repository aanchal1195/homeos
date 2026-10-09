"""M4B disposable PostgreSQL check for owner-confirmed task planning and tracking.

Uses the operational household seeded in prior integration steps. Nothing is
executed against live household data or outside this CI test database.
"""
import io
import os
from datetime import date

import psycopg
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

assert os.getenv("HOMEOS_TEST_MODE")=="true","Do not run against a live household database"
from app.main import (
    app, SessionLocal, Member, Room, StaffScope, Task, HomeManagerPlan, Audit
)

house=os.environ["HOMEOS_HOUSEHOLD_ID"]
client=TestClient(app)

with SessionLocal() as session:
    owner=session.scalar(select(Member).where(Member.household_id==house,Member.role=="owner"))
    staff=session.scalar(select(Member).where(Member.household_id==house,Member.role=="maid"))
    kitchen=session.scalar(select(Room).where(Room.household_id==house,Room.name=="Kitchen"))
    assert owner and staff and kitchen
    owner_id,staff_id,kitchen_id=owner.id,staff.id,kitchen.id
owner_headers={"X-Member-Id":owner_id}
staff_headers={"X-Member-Id":staff_id}

def call(method,path,headers=owner_headers,**kwargs):
    return client.request(method,path,headers=headers,**kwargs)

before=call("GET","/api/today",headers=staff_headers).json()["tasks"]
draft=call("POST","/api/home-manager/plans",
           json={"room_id":kitchen_id,"assignee_id":staff_id,
                 "instruction":"Clean surfaces and upload evidence before owner verification."})
assert draft.status_code==201,draft.text
plan=draft.json()
assert plan["status"]=="PROPOSED" and plan["task_id"] is None
assert len(call("GET","/api/today",headers=staff_headers).json()["tasks"])==len(before)
assert call("POST",f"/api/home-manager/plans/{plan['id']}/confirm",
            headers=staff_headers,json={}).status_code==403

# Staff scopes can change between planning and confirmation: revalidation is required.
with SessionLocal() as session:
    guard=StaffScope(household_id=house,member_id=staff_id,room_id=kitchen_id,
                     can_execute_tasks=False,can_view=True)
    session.add(guard)
    session.commit()
    guard_id=guard.id
not_allowed=call("POST",f"/api/home-manager/plans/{plan['id']}/confirm",json={})
assert not_allowed.status_code==403,not_allowed.text
with SessionLocal() as session:
    guard=session.get(StaffScope,guard_id)
    assert guard
    guard.can_execute_tasks=True
    session.commit()
approved=call("POST",f"/api/home-manager/plans/{plan['id']}/confirm",json={})
assert approved.status_code==200,approved.text
task_id=approved.json()["task_id"]
assert task_id and approved.json()["task_status"]=="ASSIGNED"
repeat=call("POST",f"/api/home-manager/plans/{plan['id']}/confirm",json={})
assert repeat.status_code==200 and repeat.json()["task_id"]==task_id
assert call("POST",f"/api/home-manager/plans/{plan['id']}/cancel",json={}).status_code==409

for state in ("IN_PROGRESS","SUBMITTED"):
    moved=call("POST",f"/api/tasks/{task_id}/status",headers=staff_headers,
               json={"status":state})
    assert moved.status_code==200,moved.text
status=call("GET",f"/api/home-manager/plans/{plan['id']}")
assert status.status_code==200,status.text
assert status.json()["task_status"]=="SUBMITTED"
assert "inspect evidence" in status.json()["follow_up"]
no_evidence=call("POST",f"/api/tasks/{task_id}/status",json={"status":"VERIFIED"})
assert no_evidence.status_code==409,no_evidence.text
img=Image.new("RGB",(8,8),(60,140,95))
data=io.BytesIO();img.save(data,format="PNG")
evidence=call("POST",f"/api/tasks/{task_id}/evidence",headers=staff_headers,
              files={"file":("cleaned.png",data.getvalue(),"image/png")})
assert evidence.status_code==200,evidence.text
assert call("POST",f"/api/tasks/{task_id}/status",headers=staff_headers,
            json={"status":"VERIFIED"}).status_code==403
assert call("POST",f"/api/tasks/{task_id}/status",
            json={"status":"VERIFIED"}).status_code==200
closed=call("POST",f"/api/tasks/{task_id}/status",json={"status":"CLOSED"})
assert closed.status_code==200,closed.text
finished=call("GET",f"/api/home-manager/plans/{plan['id']}")
assert finished.json()["task_status"]=="CLOSED"
assert finished.json()["evidence_count"]==1
assert finished.json()["follow_up"]=="Completed and closed."
with SessionLocal() as session:
    tasks=session.scalars(select(Task).where(
       Task.household_id==house,Task.source=="HOME_MANAGER",
       Task.id==task_id)).all()
    assert len(tasks)==1
    events=session.scalars(select(Audit).where(
       Audit.household_id==house,Audit.action=="home_manager.task.assigned",
       Audit.detail.like("%"+task_id+"%"))).all()
    assert len(events)==1
    plan_db=session.get(HomeManagerPlan,plan["id"])
    assert plan_db.task_id==task_id
print("PASS: PostgreSQL owner plan -> revalidated staff scope -> one assignment ->")
print("      staff submission + evidence -> owner verification/closure + follow-up.")
