import hashlib
from datetime import timedelta

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from hurdle import estimate


def basis_of(weeks):
    """依据令牌：该站参与预测的全部周读数快照。

    补报任何一周（含历史周）都会改变令牌，排队中的旧任务因此无法覆盖新预测。
    """
    payload = "|".join(
        f"{w['week_of']}:{w['liters']}:{w['changes']}" for w in weeks
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def run_job(cx, kind, payload):
    if kind != "filter-exposure":
        raise ValueError(kind)
    code = payload["station"]
    unit = cx.execute(
        "SELECT * FROM fountain_stations WHERE code=%s FOR UPDATE", (code,)
    ).fetchone()
    if not unit or not unit["in_service"]:
        raise HTTPException(409, "饮水台已停用")
    weeks = cx.execute(
        "SELECT * FROM service_weeks WHERE station=%s ORDER BY week_of DESC LIMIT 10",
        (code,),
    ).fetchall()[::-1]
    if len(weeks) < 4 or any(
        second["week_of"] - first["week_of"] != timedelta(days=7)
        for first, second in zip(weeks, weeks[1:])
    ):
        raise HTTPException(409, "至少需要四周连续抄表，缺页须补齐")
    basis = basis_of(weeks)
    # 入队后读数被补报/改写：排队的旧任务依据已变，放弃执行，不得覆盖新预测。
    if payload.get("basis") and payload["basis"] != basis:
        raise HTTPException(409, "抄表依据已变化，本次预测作废，请重新运行预测")
    latest = weeks[-1]["week_of"]
    signed = cx.execute(
        "SELECT 1 FROM round_pickups WHERE station=%s AND planning_week=%s",
        (code, latest),
    ).fetchone()
    if signed:
        raise HTTPException(409, "该周已安排领料，情景冻结")
    result = estimate(weeks, payload["scenario"])
    cx.execute(
        '''
       INSERT INTO replacement_estimates VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
       ON CONFLICT(station) DO UPDATE SET history_week=excluded.history_week,expected=excluded.expected,upper=excluded.upper,
       demand_class=excluded.demand_class,exposure=excluded.exposure,calibration=excluded.calibration,basis=excluded.basis
    ''',
        (
            code, latest, result["expected"], result["upper"], payload["scenario"],
            result["exposure"], Jsonb(result["calibration"]), basis,
        ),
    )
    return result | {"station": code, "history_week": str(latest), "basis": basis}
