from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core import db, enqueue, require
from forecast_job import basis_of

router = APIRouter(prefix="/demand")


class Estimate(BaseModel):
    station: str
    scenario: Literal["base", "busy", "festival"]


@router.get("")
def forecasts(_=Depends(require())):
    with db() as cx:
        return cx.execute(
            "SELECT * FROM replacement_estimates ORDER BY station"
        ).fetchall()


@router.post("")
def forecast(data: Estimate, _=Depends(require("operator", "reviewer"))):
    with db() as cx:
        unit = cx.execute(
            "SELECT in_service FROM fountain_stations WHERE code=%s FOR UPDATE",
            (data.station,),
        ).fetchone()
        if not unit or not unit["in_service"]:
            raise HTTPException(409, "饮水台已停用")
        weeks = cx.execute(
            "SELECT week_of,liters,changes FROM service_weeks "
            "WHERE station=%s ORDER BY week_of DESC LIMIT 10",
            (data.station,),
        ).fetchall()[::-1]
        if len(weeks) < 4:
            raise HTTPException(409, "至少需要四周连续抄表，缺页须补齐")
        basis = basis_of(weeks)
        # 新预测入队即让该站排队中的旧任务失效，旧任务跑起来也过不了依据校验。
        cx.execute(
            """UPDATE app_jobs SET status='failed',
                   error='已被更新的预测请求取代',finished_at=now()
               WHERE kind='filter-exposure' AND status='queued'
                 AND payload->>'station'=%s""",
            (data.station,),
        )
        job_id = enqueue(
            cx, "filter-exposure", data.model_dump() | {"basis": basis}
        )
        return {"job_id": job_id, "basis": basis}
