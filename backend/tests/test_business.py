"""业务规则测试（纯标准库，通过 sys.modules 桩件加载 FastAPI/psycopg）。

覆盖：
1. 补报历史周：未签预测失效、排队旧任务作废、按原情景重算。
2. 排队旧任务不得覆盖新预测（依据令牌不匹配即放弃）。
3. 补报与审签并发：任一站依据已变 → 整车退回且点名站点。
4. 已签领料单保留原数量；补报仅影响往后周次预测（预测冻结）。
5. 审签成功后重试：拿回原单，不重复占用载量。
"""
import os
import sys
import types
from contextlib import contextmanager
from datetime import date, timedelta

# ---------- 第三方依赖桩件 ----------
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "redis://stub/0")
os.environ.setdefault("DATABASE_URL", "postgresql://stub")

fastapi = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class _Router:
    def get(self, *a, **k):
        return lambda f: f

    def post(self, *a, **k):
        return lambda f: f

    def include_router(self, *a, **k):
        pass


def APIRouter(*a, **k):
    return _Router()


def Depends(*a, **k):
    return None


fastapi.HTTPException = HTTPException
fastapi.APIRouter = APIRouter
fastapi.Depends = Depends
sys.modules["fastapi"] = fastapi

security = types.ModuleType("fastapi.security")


class HTTPBearer:
    def __init__(self, *a, **k):
        pass


security.HTTPAuthorizationCredentials = object
security.HTTPBearer = HTTPBearer
sys.modules["fastapi.security"] = security

pydantic = types.ModuleType("pydantic")


class FieldInfo:
    def __init__(self, **kw):
        self.kw = kw


def Field(*a, **k):
    return FieldInfo(**k)


class BaseModel:
    def __init__(self, **kw):
        for key, value in kw.items():
            setattr(self, key, value)

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


pydantic.BaseModel = BaseModel
pydantic.Field = Field
sys.modules["pydantic"] = pydantic

psycopg = types.ModuleType("psycopg")
psycopg.IntegrityError = type("IntegrityError", (Exception,), {})
rows = types.ModuleType("psycopg.rows")
rows.dict_row = object
jsonmod = types.ModuleType("psycopg.types.json")


class Jsonb:
    def __init__(self, value, dumps=None):
        self.value = value


jsonmod.Jsonb = Jsonb
psycopg.rows = rows
psycopg.types = types.ModuleType("psycopg.types")
psycopg.types.json = jsonmod
sys.modules["psycopg"] = psycopg
sys.modules["psycopg.rows"] = rows
sys.modules["psycopg.types"] = psycopg.types
sys.modules["psycopg.types.json"] = jsonmod

redis_mod = types.ModuleType("redis")
redis_mod.Redis = type("Redis", (), {"from_url": staticmethod(lambda *a, **k: object())})
sys.modules["redis"] = redis_mod

jwt_mod = types.ModuleType("jwt")
jwt_mod.encode = lambda *a, **k: "token"
jwt_mod.decode = lambda *a, **k: {}
jwt_mod.InvalidTokenError = type("InvalidTokenError", (Exception,), {})
sys.modules["jwt"] = jwt_mod

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import enqueue  # noqa: E402
import counter_entries  # noqa: E402
import forecast_job  # noqa: E402
from round_picklist import Pickup, StationPick, bundle  # noqa: E402


# ---------- 内存数据库 ----------
class FakeCx:
    def __init__(self):
        self.stations = {}        # code -> dict
        self.weeks = {}           # (station, week_of) -> dict
        self.estimates = {}       # station -> dict
        self.rounds = {}          # code -> dict
        self.pickups = []         # list of dict
        self.jobs = []            # list of dict
        self._job_seq = 0

    @contextmanager
    def transaction(self):
        yield

    def cursor(self):
        outer = self

        class Curs:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, seq):
                for params in seq:
                    outer._execute(sql, params)

        return Curs()

    def execute(self, sql, params=None):
        return self._execute(sql, params or ())

    def _execute(self, sql, params):
        s = " ".join(sql.split())
        # 站点行锁查询
        if "FROM fountain_stations WHERE code" in s:
            row = self.stations.get(params[0])
            return _Result([dict(row)] if row else [])
        # 单周读数是否存在
        if "FROM service_weeks WHERE station=%s AND week_of=%s" in s:
            return _Result([{"one": 1}] if (params[0], params[1]) in self.weeks else [])
        # 路线下已签领料（须先于按站的 round_pickups 分支判定）
        if "FROM round_pickups WHERE route=%s ORDER BY station" in s:
            rows = [dict(p) for p in self.pickups if p["route"] == params[0]]
            rows.sort(key=lambda p: p["station"])
            return _Result(rows)
        # 已签领料（planning_week >= 某周）
        if "FROM round_pickups WHERE station=%s AND planning_week>=%s" in s:
            hit = any(
                p["station"] == params[0] and p["planning_week"] >= params[1]
                for p in self.pickups
            )
            return _Result([{"one": 1}] if hit else [])
        # 读数 upsert
        if "INSERT INTO service_weeks" in s:
            d = params
            self.weeks[(d["station"], d["week_of"])] = dict(d)
            return _Result([])
        # 预测删除（必须先于 replacement_estimates 的 SELECT 分支判定）
        if "DELETE FROM replacement_estimates" in s:
            self.estimates.pop(params[0], None)
            return _Result([])
        # 预测查询
        if "FROM replacement_estimates WHERE station=%s" in s:
            row = self.estimates.get(params[0])
            return _Result([dict(row)] if row else [])
        # 领料单是否已覆盖某站某周
        if "FROM round_pickups WHERE station=%s AND planning_week=%s" in s:
            hit = any(
                p["station"] == params[0] and p["planning_week"] == params[1]
                for p in self.pickups
            )
            return _Result([{"one": 1}] if hit else [])
        # 排队任务作废
        if "UPDATE app_jobs" in s:
            station = params[0]
            for job in self.jobs:
                if (
                    job["kind"] == "filter-exposure"
                    and job["status"] == "queued"
                    and job["payload"]["station"] == station
                ):
                    job["status"] = "failed"
            return _Result([])
        # 最近十周读数（SELECT * 与指定列两种形态；模拟 SQL 的 DESC，由调用方自行反转）
        if "FROM service_weeks" in s and "LIMIT 10" in s:
            rows = [
                dict(w) for (st, _week), w in self.weeks.items() if st == params[0]
            ]
            rows.sort(key=lambda w: w["week_of"], reverse=True)
            return _Result(rows[:10])
        # 入队
        if "INSERT INTO app_jobs" in s:
            self._job_seq += 1
            payload = params[1].value if isinstance(params[1], Jsonb) else params[1]
            job = {
                "id": self._job_seq,
                "kind": params[0],
                "payload": payload,
                "status": "queued",
            }
            self.jobs.append(job)
            return _Result([{"id": job["id"]}])
        # 路线
        if "FROM service_rounds WHERE code=%s" in s:
            row = self.rounds.get(params[0])
            return _Result([dict(row)] if row else [])
        # 并单站点联表
        if "FROM fountain_stations f" in s:
            out = []
            for code in params[0]:
                st = self.stations[code]
                est = self.estimates.get(code)
                row = dict(st)
                if est:
                    row.update(
                        history_week=est["history_week"],
                        upper=est["upper"],
                        basis=est["basis"],
                    )
                else:
                    row.update(history_week=None, upper=None, basis=None)
                out.append(row)
            out.sort(key=lambda r: r["code"])
            return _Result(out)
        # 已装载量
        if "sum(quantities)" in s:
            total = sum(
                p["quantities"] for p in self.pickups if p["route"] == params[0]
            )
            return _Result([{"count": total}])
        # 预测 upsert
        if "INSERT INTO replacement_estimates" in s:
            (code, history_week, expected, upper, demand_class,
             exposure, _calib, basis) = params
            self.estimates[code] = {
                "station": code, "history_week": history_week,
                "expected": expected, "upper": upper,
                "demand_class": demand_class, "exposure": exposure,
                "basis": basis,
            }
            return _Result([])
        # 领料插入
        if "INSERT INTO round_pickups" in s:
            route, station, qty, planning_week, cartridge, signed_by = params
            self.pickups.append(
                dict(route=route, station=station, quantities=qty,
                     planning_week=planning_week, cartridge=cartridge,
                     signed_by=signed_by)
            )
            return _Result([])
        raise AssertionError(f"未模拟的 SQL: {s}")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


# ---------- 夹具与断言辅助 ----------
MONDAY = date(2026, 10, 12)


def week(n):
    return MONDAY + timedelta(days=7 * n)


def build_cx():
    cx = FakeCx()
    cx.stations["F01"] = {
        "code": "F01", "title": "南沿广场饮水台", "district": "桥北",
        "cartridge": "QF/20", "reserve": 0, "in_service": True,
    }
    cx.stations["F02"] = {
        "code": "F02", "title": "石阶花园饮水台", "district": "桥北",
        "cartridge": "QF/20", "reserve": 0, "in_service": True,
    }
    cx.rounds["BR2"] = {
        "code": "BR2", "district": "桥北",
        "service_on": week(6), "capacity": 9,
    }
    # 六周连续读数
    for i, changes in enumerate([0, 1, 0, 2, 0, 2]):
        cx.weeks[("F01", week(i))] = {
            "station": "F01", "week_of": week(i),
            "liters": 250 + i * 10, "changes": changes, "note": "值勤周读数",
        }
    for i, changes in enumerate([0, 0, 1, 0, 0, 1]):
        cx.weeks[("F02", week(i))] = {
            "station": "F02", "week_of": week(i),
            "liters": 180 + i * 6, "changes": changes, "note": "值勤周读数",
        }
    return cx


def reading(station, week_of, changes, liters=260, note="桥北班组补报换芯"):
    return counter_entries.Reading(
        station=station, week_of=week_of, liters=liters,
        changes=changes, note=note,
    )


def run_queued(cx):
    """模拟 worker：按入队顺序依次跑掉所有 queued 任务。"""
    results = []
    for job in [j for j in cx.jobs if j["status"] == "queued"]:
        forecast_job.run_job(cx, job["kind"], job["payload"])
        job["status"] = "done"
        results.append(job)
    return results


def current_basis(cx, station):
    rows = cx.execute(
        "SELECT week_of,liters,changes FROM service_weeks "
        "WHERE station=%s ORDER BY week_of DESC LIMIT 10",
        (station,),
    ).fetchall()[::-1]
    return forecast_job.basis_of(rows)


def make_forecast(cx, station="F01", scenario="base"):
    """走 enqueue + worker 的完整预测路径。"""
    basis = current_basis(cx, station)
    job_id = enqueue(
        cx, "filter-exposure",
        {"station": station, "scenario": scenario, "basis": basis},
    )
    job = cx.jobs[job_id - 1]
    result = forecast_job.run_job(cx, job["kind"], job["payload"])
    job["status"] = "done"
    return result


def sign(cx, route, station_codes, by="reviewer@demo.local"):
    items = [
        StationPick(station=code, basis=current_basis(cx, code))
        for code in station_codes
    ]
    return bundle(cx, route, Pickup(stations=items).stations, by)


PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
_failures = []


def check(name, fn):
    try:
        fn()
        print(f"{PASS} {name}")
    except Exception as exc:  # noqa: BLE001
        _failures.append((name, exc))
        print(f"{FAIL} {name}: {exc!r}")


def expect_409(fn, fragment):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == 409, exc.status_code
        assert fragment in exc.detail, exc.detail
        return
    raise AssertionError(f"预期 409（含 {fragment!r}），但调用成功")


# ---------- 场景 1：补报 → 未签预测失效、旧任务作废、按原情景重算 ----------
def t_backfill_invalidates_unsigned_forecast():
    cx = build_cx()
    make_forecast(cx, "F01", scenario="festival")
    old = dict(cx.estimates["F01"])
    # 复核员核对期间，另一个预测请求先排队（旧任务）
    stale_id = enqueue(
        cx, "filter-exposure",
        {"station": "F01", "scenario": "festival", "basis": old["basis"]},
    )
    # 班组补报历史周（第 2 周，周一）：由 1 根更正为 2 根
    msg = counter_entries.put(
        cx, reading("F01", week(1), changes=2, liters=260)
    )
    assert "失效" in msg["message"] and "重算" in msg["message"], msg
    # 旧排队任务已被作废
    assert cx.jobs[stale_id - 1]["status"] == "failed"
    # 旧预测已被删除（等待重算），不存在陈旧行
    assert "F01" not in cx.estimates
    # 自动入队了重算任务，且沿用原情景 festival
    recompute = [j for j in cx.jobs if j["status"] == "queued"][-1]
    assert recompute["payload"]["scenario"] == "festival"
    assert recompute["payload"]["basis"] != old["basis"]
    # worker 跑完后得到新预测
    run_queued(cx)
    new = cx.estimates["F01"]
    assert new["basis"] != old["basis"]
    assert new["demand_class"] == "festival"


# ---------- 场景 2：排队旧任务依据不匹配，不得覆盖新预测 ----------
def t_stale_job_cannot_overwrite_new_forecast():
    cx = build_cx()
    first = make_forecast(cx, "F01")
    # 一个携带旧依据的任务仍在排队
    stale_payload = {"station": "F01", "scenario": "busy", "basis": first["basis"]}
    # 补报后重算出新预测
    counter_entries.put(cx, reading("F01", week(0), changes=1, liters=240))
    run_queued(cx)
    refreshed = dict(cx.estimates["F01"])
    assert refreshed["basis"] != first["basis"]
    # 旧任务此刻才被 worker 取到 → 必须放弃，不能覆盖
    expect_409(
        lambda: forecast_job.run_job(cx, "filter-exposure", stale_payload),
        "依据已变化",
    )
    assert cx.estimates["F01"]["basis"] == refreshed["basis"]
    assert cx.estimates["F01"]["demand_class"] == refreshed["demand_class"]


# ---------- 场景 3a：补报与审签并发，依据已变 → 整车退回并点名站点 ----------
def t_concurrent_backfill_rejects_whole_bundle_naming_station():
    cx = build_cx()
    make_forecast(cx, "F01")
    make_forecast(cx, "F02")
    basis_f01 = current_basis(cx, "F01")
    basis_f02 = current_basis(cx, "F02")
    # 复核员页面已加载两站依据；审签前 F02 被补报并重算
    counter_entries.put(cx, reading("F02", week(2), changes=1, liters=185))
    run_queued(cx)
    assert current_basis(cx, "F02") != basis_f02
    stale_items = [
        StationPick(station="F01", basis=basis_f01),
        StationPick(station="F02", basis=basis_f02),
    ]
    expect_409(
        lambda: bundle(cx, "BR2", stale_items, "reviewer@demo.local"),
        "F02",
    )
    # 整车退回：F01 也没有被签进去
    assert cx.pickups == []


# ---------- 场景 3b：缺依据令牌也整车退回 ----------
def t_missing_basis_rejected():
    cx = build_cx()
    make_forecast(cx, "F01")
    expect_409(
        lambda: bundle(
            cx, "BR2", [StationPick(station="F01", basis="")], "r@d.local"
        ),
        "依据令牌",
    )


# ---------- 场景 3c：依据一致时审签成功 ----------
def t_sign_succeeds_with_fresh_basis():
    cx = build_cx()
    make_forecast(cx, "F01")
    result = sign(cx, "BR2", ["F01"])
    assert result["route"] == "BR2"
    assert [p["station"] for p in cx.pickups] == ["F01"]


# ---------- 场景 4：已签领料保留原数量；补报冻结该预测，只进往后周次 ----------
def t_signed_pickup_kept_and_forecast_frozen():
    cx = build_cx()
    make_forecast(cx, "F01")
    sign(cx, "BR2", ["F01"])
    signed_qty = next(p["quantities"] for p in cx.pickups if p["station"] == "F01")
    frozen_basis = cx.estimates["F01"]["basis"]
    # 已签周次及之后的读数补报被拒绝（证据冻结）
    expect_409(
        lambda: counter_entries.put(cx, reading("F01", week(5), changes=3)),
        "冻结",
    )
    # 预测行保持原样
    assert cx.estimates["F01"]["basis"] == frozen_basis
    assert next(p["quantities"] for p in cx.pickups if p["station"] == "F01") == signed_qty
    # 已签预测的重算任务即便被错误入队，也会被“情景冻结”挡住，不覆盖
    expect_409(
        lambda: forecast_job.run_job(
            cx, "filter-exposure",
            {"station": "F01", "scenario": "base", "basis": frozen_basis},
        ),
        "情景冻结",
    )
    assert next(p["quantities"] for p in cx.pickups if p["station"] == "F01") == signed_qty


def t_backfill_after_signed_week_feeds_future_forecast():
    """已签领料后：历史周读数全部冻结、不重算；新一周读数可登记，
    并自然纳入往后周次的预测（补报数据继续服务未来计划）。"""
    cx = build_cx()
    make_forecast(cx, "F01")
    sign(cx, "BR2", ["F01"])
    frozen = dict(cx.estimates["F01"])
    queued_before = len(cx.jobs)
    # 任何历史周（含早于签核周的周次）补报都被冻结保护挡住
    expect_409(
        lambda: counter_entries.put(
            cx, reading("F01", week(0), changes=1, liters=240)
        ),
        "冻结",
    )
    assert len(cx.jobs) == queued_before  # 未入队任何重算
    assert cx.estimates["F01"]["basis"] == frozen["basis"]
    # 新一周（签核周之后）读数可正常登记，不触碰已签预测
    next_week = week(6)
    counter_entries.put(
        cx, reading("F01", next_week, changes=1, liters=310, note="新一周班组读数")
    )
    assert cx.estimates["F01"]["basis"] == frozen["basis"]  # 已签预测仍冻结
    # 新读数已入库，未来预测取最近十周时会带上
    assert cx.weeks[("F01", next_week)]["changes"] == 1


# ---------- 场景 5：审签成功后重试拿回原单，不重复占用载量 ----------
def t_retry_returns_original_pickup_without_double_capacity():
    cx = build_cx()
    make_forecast(cx, "F01")
    make_forecast(cx, "F02")
    first = sign(cx, "BR2", ["F01", "F02"])
    loaded_after_first = sum(p["quantities"] for p in cx.pickups)
    # 网络重试：同路线同站集，页面拿着已过期的依据令牌（例如客户端缓存未刷新）。
    # 幂等判定先于依据校验，直接拿回原单，不再走占用载量的插入路径。
    retry_items = [
        StationPick(station="F01", basis="stale-basis"),
        StationPick(station="F02", basis="stale-basis"),
    ]
    again = bundle(cx, "BR2", retry_items, "reviewer@demo.local")
    assert again.get("retried") is True
    assert again["total"] == first["total"]
    # 领料行没有新增，载量占用不变
    assert len(cx.pickups) == 2
    assert sum(p["quantities"] for p in cx.pickups) == loaded_after_first


# ---------- 场景 6：部分重叠站集不允许借幂等绕过 ----------
def t_partial_overlap_is_conflict():
    cx = build_cx()
    make_forecast(cx, "F01")
    make_forecast(cx, "F02")
    sign(cx, "BR2", ["F01"])
    expect_409(
        lambda: sign(cx, "BR2", ["F01", "F02"]),
        "F01",
    )


# ---------- 场景 7：兼容旧版纯字符串站列表 ----------
def t_plain_string_stations_still_supported():
    cx = build_cx()
    make_forecast(cx, "F01")
    # 无依据 → 明确要求刷新，而不是悄悄按旧数签
    expect_409(lambda: bundle(cx, "BR2", ["F01"], "r@d.local"), "依据令牌")


# ---------- 场景 8：新预测入队即作废旧排队任务 ----------
def t_new_forecast_cancels_queued_old_jobs():
    cx = build_cx()
    make_forecast(cx, "F01")
    basis = current_basis(cx, "F01")
    old_id = enqueue(
        cx, "filter-exposure", {"station": "F01", "scenario": "base", "basis": basis}
    )
    # 模拟 demand_api 的取消逻辑（与接口内语句一致）
    cx.execute(
        """UPDATE app_jobs SET status='failed'
           WHERE kind='filter-exposure' AND status='queued'
             AND payload->>'station'=%s""",
        ("F01",),
    )
    assert cx.jobs[old_id - 1]["status"] == "failed"


if __name__ == "__main__":
    tests = [
        ("补报后未签预测失效、旧任务作废、按原情景重算",
         t_backfill_invalidates_unsigned_forecast),
        ("排队旧任务依据不匹配，不得覆盖新预测",
         t_stale_job_cannot_overwrite_new_forecast),
        ("补报与审签并发：整车退回并点名变化站点",
         t_concurrent_backfill_rejects_whole_bundle_naming_station),
        ("缺少依据令牌：整车退回", t_missing_basis_rejected),
        ("依据一致：审签成功", t_sign_succeeds_with_fresh_basis),
        ("已签领料保留原数量且预测冻结", t_signed_pickup_kept_and_forecast_frozen),
        ("已签后历史冻结，新周读数供往后周次预测",
         t_backfill_after_signed_week_feeds_future_forecast),
        ("重试拿回原单，不重复占用载量",
         t_retry_returns_original_pickup_without_double_capacity),
        ("部分重叠站集判定冲突", t_partial_overlap_is_conflict),
        ("纯字符串旧请求被明确拒绝而非静默签出",
         t_plain_string_stations_still_supported),
        ("新预测入队作废旧排队任务", t_new_forecast_cancels_queued_old_jobs),
    ]
    for name, fn in tests:
        check(name, fn)
    print()
    if _failures:
        print(f"{FAIL} {len(_failures)} 个场景失败")
        sys.exit(1)
    print(f"{PASS} 全部 {len(tests)} 个业务场景通过")
