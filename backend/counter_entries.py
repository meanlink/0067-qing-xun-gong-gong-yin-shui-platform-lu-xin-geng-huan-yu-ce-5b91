from datetime import date
from fastapi import HTTPException
from pydantic import BaseModel,Field

class Reading(BaseModel):
    station:str
    week_of:date
    liters:int=Field(ge=0,le=500000)
    changes:int=Field(ge=0,le=1000)
    note:str=Field(min_length=4,max_length=140)

def put(cx,data):
    unit=cx.execute("SELECT in_service FROM fountain_stations WHERE code=%s FOR UPDATE",(data.station,)).fetchone()
    if not unit or not unit["in_service"]:
        raise HTTPException(409,"已停用饮水台不收新周读数")
    if data.week_of.weekday()!=0:
        raise HTTPException(409,"抄表周按周一起算")
    if cx.execute("SELECT 1 FROM round_pickups WHERE station=%s AND planning_week>=%s",(data.station,data.week_of)).fetchone():
        raise HTTPException(409,"该周已安排领料，历史读数冻结")
    cx.execute('''
      INSERT INTO service_weeks VALUES(%(station)s,%(week_of)s,%(liters)s,%(changes)s,%(note)s)
      ON CONFLICT(station,week_of) DO UPDATE SET liters=excluded.liters,changes=excluded.changes,note=excluded.note
    ''',data.model_dump())
    cx.execute("DELETE FROM replacement_estimates WHERE station=%s",(data.station,))
    return {"message":"抄表证据已登记"}
