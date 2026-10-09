"""M4B first bounded Home Manager action: owner-confirmed room cleaning.

A plan is not a task. Confirmation is explicit and only invokes the existing
household operational task ledger, scope rules and evidence/verification flow.
No model may select the assignee, commit tasks or bypass status permissions.
"""
from datetime import date, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import (app, actor, db, require_owner, ensure_operational, audit,
                      scoped, now, uid, Task, Room, Member, StaffScope, Evidence,
                      HomeManagerPlan)


class RoomCleaningPlanIn(BaseModel):
    room_id:str=Field(min_length=1,max_length=100)
    assignee_id:str=Field(min_length=1,max_length=100)
    due_date:date|None=None
    instruction:str=Field(default="",max_length=600)


def _permission(s:Session,m,room,staff):
    if staff.role!="maid":
        raise HTTPException(422,"Room-cleaning plans can only be assigned to maid staff")
    scopes=s.scalars(select(StaffScope).where(
        StaffScope.household_id==m.household_id,
        StaffScope.member_id==staff.id)).all()
    if scopes and not any(scope.can_execute_tasks and
           (scope.room_id==room.id or
            (scope.room_id is None and scope.floor_id==room.floor_id))
           for scope in scopes):
        raise HTTPException(403,"Assigned staff member has no execution scope for this room")


def _plan(s:Session,m,id,*,lock=False):
    query=select(HomeManagerPlan).where(
      HomeManagerPlan.household_id==m.household_id,HomeManagerPlan.id==id)
    if lock:
        query=query.with_for_update()
    obj=s.scalar(query)
    if obj is None:
        raise HTTPException(404,"Home Manager plan not found")
    return obj


def _followup(task,plan):
    if plan.status=="PROPOSED":
        return "Awaiting owner confirmation — no task has been assigned."
    if plan.status=="CANCELLED":
        return "Cancelled before assignment."
    if not task:
        return "Attention required: linked operational task is unavailable."
    state=task.status
    states={
      "ASSIGNED":"Waiting for staff to start.",
      "IN_PROGRESS":"Staff reports work in progress.",
      "BLOCKED":"Blocked — owner should review the task and unblock.",
      "SUBMITTED":"Staff submitted work. Owner must inspect evidence and verify.",
      "REWORK_REQUIRED":"Owner requested rework — staff should correct and resubmit.",
      "VERIFIED":"Owner verified evidence. Task can be closed.",
      "CLOSED":"Completed and closed.",
    }
    suffix=""
    if task.due_date < date.today().isoformat() and state!="CLOSED":
        suffix=" Overdue: follow up with the assigned staff member."
    return states.get(state,"Unknown operational task state.")+suffix


def _present(s:Session,plan):
    task=s.get(Task,plan.task_id) if plan.task_id else None
    evidence_count=0
    if task:
        evidence_count=s.query(Evidence).filter(
           Evidence.household_id==plan.household_id,
           Evidence.task_id==task.id).count()
    return {
      "id":plan.id,"kind":plan.plan_kind,
      "room_id":plan.room_id,"assignee_id":plan.assignee_id,
      "title":plan.task_title,"instruction":plan.instruction,
      "due_date":plan.due_date,"status":plan.status,
      "task_id":plan.task_id,
      "task_status":task.status if task else None,
      "evidence_count":evidence_count,
      "owner_confirmed":plan.confirmed_at is not None,
      "follow_up":_followup(task,plan),
      "created_at":plan.created_at.isoformat() if plan.created_at else None,
    }


@app.post("/api/home-manager/plans",status_code=201)
def propose_room_cleaning(p:RoomCleaningPlanIn,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    ensure_operational(s,m)
    room=scoped(s,Room,p.room_id,m)
    staff=scoped(s,Member,p.assignee_id,m)
    _permission(s,m,room,staff)
    due=p.due_date or date.today()
    if due < date.today():
        raise HTTPException(422,"Due date cannot be in the past")
    if due > date.today()+timedelta(days=730):
        raise HTTPException(422,"Due date exceeds two-year planning horizon")
    plan=HomeManagerPlan(
       id=uid(),household_id=m.household_id,owner_id=m.id,room_id=room.id,
       assignee_id=staff.id,plan_kind="CLEAN_ROOM",task_title=f"Clean {room.name}",
       instruction=p.instruction.strip(),due_date=due.isoformat(),
       status="PROPOSED",created_at=now())
    s.add(plan)
    s.flush()
    audit(s,m,"home_manager.plan.proposed",plan.id)
    response=_present(s,plan)
    s.commit()
    return response


class RoomCleaningPlanPatch(BaseModel):
    room_id:str|None=Field(default=None,min_length=1,max_length=100)
    assignee_id:str|None=Field(default=None,min_length=1,max_length=100)
    instruction:str|None=Field(default=None,max_length=600)


@app.patch("/api/home-manager/plans/{plan_id}")
def revise_room_cleaning(plan_id:str,p:RoomCleaningPlanPatch,m=Depends(actor),s:Session=Depends(db)):
    """Owner-only revision of an unconfirmed draft; never mutates an assigned task."""
    require_owner(m)
    ensure_operational(s,m)
    plan=_plan(s,m,plan_id,lock=True)
    if plan.status!="PROPOSED":
        raise HTTPException(409,"Only a proposed, unassigned plan may be revised")
    if p.room_id is None and p.assignee_id is None and p.instruction is None:
        raise HTTPException(422,"Specify a field to revise")
    room=scoped(s,Room,p.room_id or plan.room_id,m)
    staff=scoped(s,Member,p.assignee_id or plan.assignee_id,m)
    _permission(s,m,room,staff)
    plan.room_id=room.id
    plan.assignee_id=staff.id
    plan.task_title=f"Clean {room.name}"
    if p.instruction is not None:
        plan.instruction=p.instruction.strip()
    audit(s,m,"home_manager.plan.revised",plan.id)
    response=_present(s,plan)
    s.commit()
    return response


@app.post("/api/home-manager/plans/{plan_id}/confirm")
def confirm_room_cleaning(plan_id:str,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    ensure_operational(s,m)
    plan=_plan(s,m,plan_id,lock=True)
    if plan.status=="ASSIGNED":
        return _present(s,plan)
    if plan.status!="PROPOSED":
        raise HTTPException(409,"Plan cannot be confirmed from current state")
    room=scoped(s,Room,plan.room_id,m)
    staff=scoped(s,Member,plan.assignee_id,m)
    _permission(s,m,room,staff)  # Scope may have changed after proposal.
    instructions=plan.instruction or "Clean the configured room safely."
    task=Task(
      id=uid(),household_id=m.household_id,
      room_id=room.id,assignee_id=staff.id,title=plan.task_title,
      category="CLEANING",priority="MEDIUM",source="HOME_MANAGER",
      status="ASSIGNED",due_date=plan.due_date,
      notes=f"Owner-confirmed plan {plan.id}: {instructions} "
            "Staff submits work; owner inspects photographic evidence before verification.")
    s.add(task)
    s.flush()
    plan.status="ASSIGNED"
    plan.task_id=task.id
    plan.confirmed_at=now()
    audit(s,m,"home_manager.task.assigned",f"{plan.id}:{task.id}")
    response=_present(s,plan)
    s.commit()
    return response


@app.post("/api/home-manager/plans/{plan_id}/cancel")
def cancel_room_cleaning(plan_id:str,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    plan=_plan(s,m,plan_id,lock=True)
    if plan.status!="PROPOSED":
        raise HTTPException(409,"Only unconfirmed plans may be cancelled")
    plan.status="CANCELLED"
    audit(s,m,"home_manager.plan.cancelled",plan.id)
    response=_present(s,plan)
    s.commit()
    return response


@app.get("/api/home-manager/plans/{plan_id}")
def get_room_cleaning(plan_id:str,m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    return _present(s,_plan(s,m,plan_id))


@app.get("/api/home-manager/plans")
def recent_room_cleaning(m=Depends(actor),s:Session=Depends(db)):
    require_owner(m)
    plans=s.scalars(select(HomeManagerPlan).where(
      HomeManagerPlan.household_id==m.household_id
    ).order_by(HomeManagerPlan.created_at.desc(),HomeManagerPlan.id.desc()).limit(40)).all()
    return {"plans":[_present(s,p) for p in plans],
            "mode":"HUMAN_CONFIRMED_SINGLE_TASK"}
