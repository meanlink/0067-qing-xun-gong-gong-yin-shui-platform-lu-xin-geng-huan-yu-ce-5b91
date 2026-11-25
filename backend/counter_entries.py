from datetime import date, timedelta

from fastapi import HTTPException
from pydantic import BaseModel, Field

from core import enqueue
from forecast_job import basis_of


class Reading(BaseModel):
    station: str
    week_of: date
    liters: int = Field(ge=0, le=500000)
    changes: int = Field(ge=0, le=1000)
    note: str = Field(min_length=4, max_length=140)


def put(cx, data):
    unit = cx.execute(
        "SELECT in_service FROM fountain_stations WHERE code=%s FOR UPDATE",
        (data.station,),
    ).fetchone()
    if not unit or not unit["in_service"]:
        raise HTTPException(409, "已停用饮水台不收新周读数")
    if data.week_of.weekday() != 0:
        raise HTTPException(409, "抄表周按周一起算")
    existing = cx.execute(
        "SELECT 1 FROM service_weeks WHERE station=%s AND week_of=%s",
        (data.station, data.week_of),
    ).fetchone()
    signed_week = cx.execute(
        """SELECT 1 FROM round_pickups WHERE station=%s AND planning_week>=%s LIMIT 1""",
        (data.station, data.week_of),
    ).fetchone()
    # 已签领料单的周次：历史读数是签核证据，冻结；已签数量也保留原数。
    if signed_week:
        raise HTTPException(409, "该周已安排领料，历史读数冻结，已签领料单保留原数量")
    cx.execute(
        '''
      INSERT INTO service_weeks VALUES(%(station)s,%(week_of)s,%(liters)s,%(changes)s,%(note)s)
      ON CONFLICT(station,week_of) DO UPDATE SET liters=excluded.liters,changes=excluded.changes,note=excluded.note
    ''',
        data.model_dump(),
    )
    estimate = cx.execute(
        "SELECT history_week,demand_class FROM replacement_estimates WHERE station=%s",
        (data.station,),
    ).fetchone()
    # 已签领料的预测（历史凭证周被并单）保持冻结：补报仍留在 service_weeks，
    # 往后周次跑预测时自然纳入新读数。
    frozen = estimate and cx.execute(
        "SELECT 1 FROM round_pickups WHERE station=%s AND planning_week=%s",
        (data.station, estimate["history_week"]),
    ).fetchone()
    if not estimate or frozen:
        return {
            "message": "抄表证据已登记"
            + ("；已签领料预测冻结，补报将用于往后周次预测" if frozen else "")
        }
    # 未签预测受补报影响：作废排队旧任务、让旧预测失效，并按原情景入队重算。
    cx.execute(
        """UPDATE app_jobs SET status='failed',
               error='补报换芯记录后依据已变，任务作废',finished_at=now()
           WHERE kind='filter-exposure' AND status='queued'
             AND payload->>'station'=%s""",
        (data.station,),
    )
    cx.execute(
        "DELETE FROM replacement_estimates WHERE station=%s", (data.station,)
    )
    weeks = cx.execute(
        "SELECT week_of,liters,changes FROM service_weeks "
        "WHERE station=%s ORDER BY week_of DESC LIMIT 10",
        (data.station,),
    ).fetchall()[::-1]
    if len(weeks) < 4 or any(
        second["week_of"] - first["week_of"] != timedelta(days=7)
        for first, second in zip(weeks, weeks[1:])
    ):
        return {"message": "抄表证据已登记；旧预测已失效，补齐连续四周读数后可重新预测"}
    basis = basis_of(weeks)
    enqueue(
        cx,
        "filter-exposure",
        {
            "station": data.station,
            "scenario": estimate["demand_class"],
            "basis": basis,
        },
    )
    return {
        "message": (
            "抄表证据已登记，受影响的未签预测已失效并排队重算"
            if existing else
            "补报换芯记录已登记，受影响的未签预测已失效并排队重算"
        )
    }
