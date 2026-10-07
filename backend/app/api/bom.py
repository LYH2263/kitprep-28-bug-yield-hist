from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Dish, Ingredient
from app.services.prep_service import generate_prep_run, lock_open_orders, prep_lock
router = APIRouter(prefix="/bom", tags=["bom"])

@router.get("")
def list_bom(db: Session = Depends(get_db)):
    dishes = {d.id: d for d in db.scalars(select(Dish)).all()}
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    rows = db.scalars(select(BomLine).order_by(BomLine.dish_id, BomLine.id)).all()
    return [{"id": r.id, "dish_id": r.dish_id, "dish_name": dishes[r.dish_id].name,
             "ingredient_id": r.ingredient_id, "ingredient_name": ings[r.ingredient_id].name,
             "qty_per_portion": r.qty_per_portion, "yield_rate": r.yield_rate,
             "unit": ings[r.ingredient_id].unit} for r in rows]

@router.get("/tree")
def bom_tree(db: Session = Depends(get_db)):
    dishes = db.scalars(select(Dish).order_by(Dish.id)).all()
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    lines = db.scalars(select(BomLine)).all()
    tree = []
    for d in dishes:
        children = [{"ingredient": ings[l.ingredient_id].name, "qty": l.qty_per_portion,
                     "yield_rate": l.yield_rate, "unit": ings[l.ingredient_id].unit}
                    for l in lines if l.dish_id == d.id]
        tree.append({"dish": d.name, "code": d.code, "children": children})
    return tree

class YieldRateItem(BaseModel):
    id: int  # bom_line id
    yield_rate: float | None = None  # null = 清除（视为从未写过，按 1 展开）

class YieldRateSave(BaseModel):
    rates: list[YieldRateItem]

def _validate(rate: float | None) -> None:
    # 失败说明只讲出成率，与结存无关
    if rate is not None and not 0.0 < rate <= 1.0:
        raise HTTPException(400, f"出成率必须大于 0 且不超过 1，收到: {rate}")

@router.put("/yield-rates")
def save_yield_rates(payload: YieldRateSave, db: Session = Depends(get_db)):
    """定额页保存出成率：定义仓与当前有效单同一事务整张重写；任何一步失败整体退回。

    - 只插新 PrepRun，已存档历史单一字不改；
    - 库存结存与此接口无关，保存前后同一个数；
    - 与备料台「生成备料单」抢锁时按订单行锁串行，只许同一套成败。
    """
    for item in payload.rates:
        _validate(item.yield_rate)
    try:
        with prep_lock:
            open_orders = lock_open_orders(db)
            lines = {l.id: l for l in db.scalars(select(BomLine)).all()}
            for item in payload.rates:
                line = lines.get(item.id)
                if line is None:
                    raise HTTPException(404, f"BOM 行不存在: {item.id}")
                line.yield_rate = item.yield_rate
            db.flush()
            # 当前有效单整张按新率重落：只插新 PrepRun，与备料台「生成备料单」同一套展开；
            # 已存档历史单一字不改，库存结存与此接口无关（保存不是领料）。
            rewritten = []
            if payload.rates:
                for order in open_orders:
                    run = generate_prep_run(db, order)
                    rewritten.append({"order_id": order.id, "prep_run_id": run.id})
            db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "出成率保存失败，定义与当前备料单已整体退回")
    return {"ok": True, "updated": len(payload.rates), "rewritten": rewritten}
