from fastapi import APIRouter,Depends
from core import db,require
from counter_entries import Reading,put
router=APIRouter(prefix="/readings")

@router.get("")
def read(_=Depends(require())):
    with db() as cx:
        return cx.execute("SELECT * FROM service_weeks ORDER BY week_of DESC,station").fetchall()

@router.post("")
def submit(data:Reading,_=Depends(require("operator","reviewer"))):
    with db() as cx:
        return put(cx,data)
