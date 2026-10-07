"""Central kitchen BOM explode: order lines × BOM qty ÷ yield rate, merge ingredients, shortage = need - stock."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float

def _effective_qty_per_portion(bom_line: dict) -> float:
    """qty_per_portion 按出成率折算：出成率 None 或 1 时与一层展开完全一致。"""
    rate = bom_line.get("yield_rate")
    if rate is None:
        return bom_line["qty_per_portion"]
    rate = float(rate)
    if not 0.0 < rate <= 1.0:
        raise ValueError(f"出成率必须大于 0 且不超过 1，收到: {rate!r}")
    if rate == 1.0:
        return bom_line["qty_per_portion"]
    return bom_line["qty_per_portion"] / rate

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion, yield_rate?."""
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = (
                need.get(bl["ingredient_id"], 0.0)
                + ol["portions"] * _effective_qty_per_portion(bl)
            )
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines

def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }
