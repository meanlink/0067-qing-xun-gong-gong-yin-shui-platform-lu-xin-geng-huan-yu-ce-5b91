from typing import Literal
from fastapi import APIRouter,Depends
from pydantic import BaseModel
from core import db,enqueue,require
router=APIRouter(prefix="/demand")

class Estimate(BaseModel):
    station:str
    scenario:Literal["base","busy","festival"]

@router.get("")
def forecasts(_=Depends(require())):
    with db() as cx:
        return cx.execute("SELECT * FROM replacement_estimates ORDER BY station").fetchall()

@router.post("")
def forecast(data:Estimate,_=Depends(require("operator","reviewer"))):
    with db() as cx:
        return {"job_id":enqueue(cx,"filter-exposure",data.model_dump())}
