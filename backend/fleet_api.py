from fastapi import APIRouter,Depends
from core import db,require
from station_stock import fleet
router=APIRouter(prefix="/fleet")
@router.get("")
def stations(_=Depends(require())):
    with db() as cx:
        return fleet(cx)
