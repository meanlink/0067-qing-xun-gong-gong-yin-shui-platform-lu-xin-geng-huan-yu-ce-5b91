from fastapi import APIRouter,Depends
from core import db,require
from round_picklist import Pickup,bundle,load_rounds
router=APIRouter(prefix="/rounds")

@router.get("")
def routes(_=Depends(require())):
    with db() as cx:
        return load_rounds(cx)

@router.post("/{route}/bundle")
def approve(route:str,data:Pickup,user=Depends(require("reviewer"))):
    with db() as cx:
        return bundle(cx,route,data.stations,user["email"])
