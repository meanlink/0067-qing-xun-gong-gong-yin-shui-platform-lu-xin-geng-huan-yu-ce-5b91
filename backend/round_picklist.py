from datetime import timedelta
from fastapi import HTTPException
from pydantic import BaseModel,Field

class Pickup(BaseModel):
    stations:list[str]=Field(min_length=1,max_length=20)

def load_rounds(cx):
    rows=cx.execute("SELECT * FROM service_rounds ORDER BY service_on,code").fetchall()
    for row in rows:
        row["pickups"]=cx.execute("SELECT * FROM round_pickups WHERE route=%s ORDER BY station",(row["code"],)).fetchall()
    return rows

def bundle(cx,code,selection,by):
    if len(set(selection))!=len(selection):
        raise HTTPException(422,"同一饮水台不能重复勾选")
    route=cx.execute("SELECT * FROM service_rounds WHERE code=%s FOR UPDATE",(code,)).fetchone()
    if not route:
        raise HTTPException(404,"区域班次不存在")
    records=cx.execute('''
      SELECT f.*,e.history_week,e.upper FROM fountain_stations f
      LEFT JOIN replacement_estimates e ON f.code=e.station WHERE f.code=ANY(%s) ORDER BY f.code FOR UPDATE OF f
    ''',(selection,)).fetchall()
    if len(records)!=len(selection) or any(r["district"]!=route["district"] or not r["in_service"] for r in records):
        raise HTTPException(409,"饮水台须在同一区域且仍启用")
    needs=[]
    for r in records:
        if r["history_week"] is None or not r["history_week"]+timedelta(days=7)<=route["service_on"]<r["history_week"]+timedelta(days=14):
            raise HTTPException(409,"尚无与轮换周对应的预测")
        if cx.execute("SELECT 1 FROM round_pickups WHERE station=%s AND planning_week=%s",(r["code"],r["history_week"])).fetchone():
            raise HTTPException(409,"这周已为该饮水台安排领料")
        take=max(0,r["upper"]-r["reserve"])
        if take:
            needs.append((code,r["code"],take,r["history_week"],r["cartridge"],by))
    if not needs:
        raise HTTPException(409,"各站现有备库已覆盖预测")
    loaded=cx.execute("SELECT coalesce(sum(quantities),0) AS count FROM round_pickups WHERE route=%s",(code,)).fetchone()["count"]
    if sum(x[2] for x in needs)+loaded>route["capacity"]:
        raise HTTPException(409,"合并后超过巡行携带容量")
    with cx.cursor() as curs:
        curs.executemany("INSERT INTO round_pickups VALUES(%s,%s,%s,%s,%s,%s)",needs)
    return {"route":code,"total":sum(x[2] for x in needs),"stations":[x[1] for x in needs]}
