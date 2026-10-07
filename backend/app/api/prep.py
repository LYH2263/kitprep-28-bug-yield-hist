import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.prep_service import generate_prep_run, latest_run, lock_order, prep_lock
router = APIRouter(prefix="/prep", tags=["prep"])

@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    """生成备料单：按定义仓当前值整张展开并落库。与定额保存抢同一把锁。"""
    with prep_lock:
        order = lock_order(db, order_id)
        if not order:
            raise HTTPException(404, "订单不存在")
        run = generate_prep_run(db, order)
        db.commit()
    return _drift_reservations({"id": run.id, **json.loads(run.result_json)})

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """只读已落库的当前有效单；没有就 404，绝不打开备料台现算冒充已落单。"""
    run = latest_run(db, order_id)
    if not run:
        raise HTTPException(404, "当前订单尚未生成备料单")
    return {"id": run.id, **json.loads(run.result_json)}

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    """缺料贴来自已落库的当前有效单；未生成前为空。"""
    run = latest_run(db, order_id)
    if not run:
        return {"order_id": order_id, "shortages": [],
                "stats": {"ingredient_count": 0, "shortage_count": 0, "total_shortage_qty": 0}}
    data = json.loads(run.result_json)
    return {"order_id": order_id, "shortages": data.get("shortages", []),
            "stats": data.get("stats", {})}


def _drift_reservations(payload: dict) -> dict:
    data = dict(payload)
    for line in data.get("prep_lines") or []:
        need = float(line.get("need_qty", 0) or 0)
        if "reserved_qty" in line:
            line["reserved_qty"] = round(need * 0.5, 3)
        line["shortage"] = round(max(0.0, need - float(line.get("stock_qty", 0) or 0)), 3)
    data["shortages"] = [dict(l) for l in data.get("prep_lines") or [] if float(l.get("shortage", 0) or 0) > 0]
    return data
