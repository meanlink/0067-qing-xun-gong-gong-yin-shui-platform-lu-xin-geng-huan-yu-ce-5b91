from datetime import timedelta
from typing import Union

from fastapi import HTTPException
from pydantic import BaseModel, Field


class StationPick(BaseModel):
    station: str
    basis: str = ""


class Pickup(BaseModel):
    # 兼容两种提交：["F01","F02"] 或 [{"station":"F01","basis":"..."}]
    stations: list[Union[str, StationPick]] = Field(min_length=1, max_length=20)


def _normalized(items):
    return [
        item if isinstance(item, str) else item.station
        for item in items
    ]


def _basis_of(items, code):
    for item in items:
        if not isinstance(item, str) and item.station == code:
            return item.basis
    return ""


def load_rounds(cx):
    rows = cx.execute(
        "SELECT * FROM service_rounds ORDER BY service_on,code"
    ).fetchall()
    for row in rows:
        row["pickups"] = cx.execute(
            "SELECT * FROM round_pickups WHERE route=%s ORDER BY station",
            (row["code"],),
        ).fetchall()
    return rows


def bundle(cx, code, selection, by):
    raw = selection
    selection = _normalized(selection)
    if len(set(selection)) != len(selection):
        raise HTTPException(422, "同一饮水台不能重复勾选")
    route = cx.execute(
        "SELECT * FROM service_rounds WHERE code=%s FOR UPDATE", (code,)
    ).fetchone()
    if not route:
        raise HTTPException(404, "区域班次不存在")

    # 幂等重试：同一路线、完全相同的站集再次审签 → 拿回原单，不重复占用载量。
    existing = cx.execute(
        "SELECT station,quantities FROM round_pickups WHERE route=%s ORDER BY station",
        (code,),
    ).fetchall()
    if existing and sorted(r["station"] for r in existing) == sorted(selection):
        return {
            "route": code,
            "total": sum(r["quantities"] for r in existing),
            "stations": [r["station"] for r in existing],
            "retried": True,
            "message": "该领料单已审签，返回原单，未重复占用载量",
        }
    if existing:
        overlap = sorted(
            set(r["station"] for r in existing) & set(selection)
        )
        if overlap:
            raise HTTPException(
                409, f"饮水台 {overlap[0]} 已在本路线并单；每站每周只能领料一次"
            )

    records = cx.execute(
        '''
      SELECT f.*,e.history_week,e.upper,e.basis FROM fountain_stations f
      LEFT JOIN replacement_estimates e ON f.code=e.station
      WHERE f.code=ANY(%s) ORDER BY f.code FOR UPDATE OF f
    ''',
        (selection,),
    ).fetchall()
    if len(records) != len(selection) or any(
        r["district"] != route["district"] or not r["in_service"]
        for r in records
    ):
        raise HTTPException(409, "饮水台须在同一区域且仍启用")
    needs = []
    for r in records:
        if r["history_week"] is None:
            raise HTTPException(409, f"饮水台 {r['code']} 尚无预测，无法审签")
        # 整车退回：补报/重算导致该站待签数量依据已变，点名站点。
        submitted_basis = _basis_of(raw, r["code"])
        if not submitted_basis:
            raise HTTPException(
                409,
                f"饮水台 {r['code']} 缺少预测依据令牌，请刷新页面后重新整单审签",
            )
        if submitted_basis != r["basis"]:
            raise HTTPException(
                409,
                f"饮水台 {r['code']} 的预测依据已变化（补报换芯后已重算），"
                "整车退回，请按新待签数量重新审签",
            )
        if not (
            r["history_week"] + timedelta(days=7)
            <= route["service_on"]
            < r["history_week"] + timedelta(days=14)
        ):
            raise HTTPException(409, f"饮水台 {r['code']} 尚无与轮换周对应的预测")
        if cx.execute(
            "SELECT 1 FROM round_pickups WHERE station=%s AND planning_week=%s",
            (r["code"], r["history_week"]),
        ).fetchone():
            raise HTTPException(409, f"这周已为饮水台 {r['code']} 安排领料")
        take = max(0, r["upper"] - r["reserve"])
        if take:
            needs.append(
                (code, r["code"], take, r["history_week"], r["cartridge"], by)
            )
    if not needs:
        raise HTTPException(409, "各站现有备库已覆盖预测")
    loaded = cx.execute(
        "SELECT coalesce(sum(quantities),0) AS count FROM round_pickups WHERE route=%s",
        (code,),
    ).fetchone()["count"]
    if sum(x[2] for x in needs) + loaded > route["capacity"]:
        raise HTTPException(409, "合并后超过巡行携带容量")
    with cx.cursor() as curs:
        curs.executemany(
            "INSERT INTO round_pickups VALUES(%s,%s,%s,%s,%s,%s)", needs
        )
    return {
        "route": code,
        "total": sum(x[2] for x in needs),
        "stations": [x[1] for x in needs],
    }
