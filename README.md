# 清巡 · 公共饮水台滤芯更换预测

桥北社区设施组有两名巡行员、四座街区饮水台。月末从抄表 CSV 估计备品，原先经常把零更换当缺表、节日人流按平时估算、或同站被两班重复领料。系统把出水量口径接到区域领料，下游是工具车取货单。

## 一天的工作顺序

1. 08:30 对照桥北班组-1116.csv 确认 F01 和 F02 的周数据。
2. 09:00 停用的旧长凳 F04 拒收新读数。
3. 09:20 对 F01 和 F02 分别运行节日人流预测。
4. 09:35 记录 F01 六周观察中三个有实际更换。
5. 10:10 合并领料时 BR1 只有一根载量，被拒绝。
6. 10:25 审签 BR2 领料，记录两站料号。
7. 11:00 尝试 BR1 重复领同站同周，系统提示已安排。

## 算法口径

用简化零膨胀泊松模型。活动概率是（换芯周数+1）/（总周数+2）；活动时，使用阳性周换芯量除以出水量的平滑率，乘最近三周平均出水量和情景系数（1、1.25 或 1.6）。以该混合分布的第一项累计概率达到 0.9 为预测上界，缺口扣站内现存数。使用最近最多十个连续完整周。

## 上手

```sh
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
docker compose down --remove-orphans
```

前端走本机 **18461**，API 走 **19461**，PostgreSQL 走 **17961**。本地开发可在安装 Python 3.11、PostgreSQL 和 Redis 后配置与 Compose 相同的环境变量，在 backend 运行 `uvicorn app:app --reload`，前端以 Nginx 同源代理启动。

| 角色 | 邮箱 | 业务权限 |
|---|---|---|
| 录入员 | operator@demo.local | 登记周读数、运行情景 |
| 复核员 | reviewer@demo.local | 审签区域并单领料 |
| 查阅员 | viewer@demo.local | 查饮水台、读数、预测、领料单 |

三个演示账号默认密码均为 `Demo2026!`。使用本地合成样本，seed 只插入缺失的自然键。关闭 `SEED_DEMO` 可跳过自动 seed。使用自己的 `JWT_SECRET`、`POSTGRES_PASSWORD` 和 `DEMO_PASSWORD` 部署。

| 目录 | 技术与职责 |
|---|---|
| backend | Python 3.11 / FastAPI，使用 PostgreSQL 16；Worker 轮询持久化队列，Redis 为登录限流及健康检查提供支持 |
| frontend | Nginx、HTML、CSS、JavaScript ES modules，HTTP 同源代理 |
| docker-compose.yml | 5 服务及健康检查、独立卷；Redis 与 worker 无宿主端口 |

角色、作业状态在 `backend/core.py`、`frontend/base.js` 定义，在 `backend/core.py`（鉴权、队列）与 `backend/worker.py` 使用。领域阶段由数据库约束与业务服务维护，`frontend/view.js` 负责显示。接口输出为最新已提交状态。

模型输入为合成周读数。领料单在本地签核，外部仓库库存由班组另行管理。

MIT License
