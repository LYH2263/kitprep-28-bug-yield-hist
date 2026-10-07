"""备料单落库：定义仓（bom_lines 含出成率）当前值整张展开，写入新的 PrepRun 快照。

历史 PrepRun 是已钉死的存档，只插不改；当前有效单 = 每个 open 订单最新一张 PrepRun。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict

# 进程内互斥：与订单行锁（Postgres FOR UPDATE）双重保险。
# 定额保存与「生成备料单」抢在同一瞬间时，只许同一套成败——
# 单进程内由这把锁串行，多进程/多副本由数据库行锁串行。
prep_lock = threading.Lock()


def lock_open_orders(db: Session) -> list[KitchenOrder]:
    """按 id 顺序锁住全部 open 订单（Postgres 下 FOR UPDATE，SQLite 下退化为普通查询）。

    定额保存与「生成备料单」都走同一把锁，保证同一瞬间只有一套成败：
    要么整张按新率落库，要么整张停住，不会一边新率一边旧率。
    """
    return list(db.scalars(
        select(KitchenOrder)
        .where(KitchenOrder.status == "open")
        .order_by(KitchenOrder.id)
        .with_for_update()
    ).all())


def lock_order(db: Session, order_id: int) -> KitchenOrder | None:
    """锁住并取出单个订单（与 lock_open_orders 同一把行锁）。"""
    return db.scalars(
        select(KitchenOrder)
        .where(KitchenOrder.id == order_id)
        .with_for_update()
    ).first()


def generate_prep_run(db: Session, order: KitchenOrder) -> PrepRun:
    """按定义仓当前值整张展开，插入一张新的 PrepRun（当前有效单）；不动历史单、不动库存。"""
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id,
            "qty_per_portion": b.qty_per_portion, "yield_rate": b.yield_rate}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    run = PrepRun(order_id=order.id, created_at=datetime.utcnow(),
                  result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.flush()
    return run


def latest_run(db: Session, order_id: int) -> PrepRun | None:
    """当前有效单 = 该订单最新一张 PrepRun。纯只读：读路径绝不改存档、不落库。"""
    return db.scalars(
        select(PrepRun)
        .where(PrepRun.order_id == order_id)
        .order_by(PrepRun.id.desc())
    ).first()
