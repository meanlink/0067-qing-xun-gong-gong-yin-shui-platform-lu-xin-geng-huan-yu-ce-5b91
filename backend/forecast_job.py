from fastapi import HTTPException
from psycopg.types.json import Jsonb
from datetime import timedelta
from hurdle import estimate

def run_job(cx,kind,payload):
    if kind!="filter-exposure":
        raise ValueError(kind)
    code=payload["station"]
    unit=cx.execute("SELECT * FROM fountain_stations WHERE code=%s FOR UPDATE",(code,)).fetchone()
    if not unit or not unit["in_service"]:
        raise HTTPException(409,"饮水台已停用")
    weeks=cx.execute("SELECT * FROM service_weeks WHERE station=%s ORDER BY week_of DESC LIMIT 10",(code,)).fetchall()[::-1]
    if len(weeks)<4 or any(second["week_of"]-first["week_of"]!=timedelta(days=7) for first,second in zip(weeks,weeks[1:])):
        raise HTTPException(409,"至少需要四周连续抄表，缺页须补齐")
    latest=weeks[-1]["week_of"]
    if cx.execute("SELECT 1 FROM round_pickups WHERE station=%s AND planning_week=%s",(code,latest)).fetchone():
        raise HTTPException(409,"该周已安排领料，情景冻结")
    result=estimate(weeks,payload["scenario"])
    cx.execute('''
       INSERT INTO replacement_estimates VALUES(%s,%s,%s,%s,%s,%s,%s)
       ON CONFLICT(station) DO UPDATE SET history_week=excluded.history_week,expected=excluded.expected,upper=excluded.upper,
       demand_class=excluded.demand_class,exposure=excluded.exposure,calibration=excluded.calibration
    ''',(code,latest,result["expected"],result["upper"],payload["scenario"],result["exposure"],Jsonb(result["calibration"])))
    return result|{"station":code,"history_week":str(latest)}
