import pytest
from app.services.bom_engine import explode_and_merge

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0

def _base():
    order_lines = [{"dish_id": 1, "portions": 10}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 100.0}}
    return order_lines, ings

def test_yield_rate_scales_need_up():
    order_lines, ings = _base()
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": 0.5}]
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].need_qty == 4.0  # 10 * 0.2 / 0.5

def test_smaller_yield_rate_bigger_need():
    order_lines, ings = _base()
    def need(rate):
        bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": rate}]
        return explode_and_merge(order_lines, bom, ings)[0].need_qty
    assert need(0.5) > need(0.8) > need(1.0)

def test_yield_rate_one_and_unset_match_legacy():
    order_lines, ings = _base()
    legacy = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2}]
    unset = [{**legacy[0], "yield_rate": None}]
    one = [{**legacy[0], "yield_rate": 1.0}]
    expected = explode_and_merge(order_lines, legacy, ings)[0].need_qty
    assert explode_and_merge(order_lines, unset, ings)[0].need_qty == expected
    assert explode_and_merge(order_lines, one, ings)[0].need_qty == expected

@pytest.mark.parametrize("bad", [0, 0.0, -0.3, 1.5, 2])
def test_invalid_yield_rate_rejected(bad):
    order_lines, ings = _base()
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": bad}]
    with pytest.raises(ValueError, match="出成率"):
        explode_and_merge(order_lines, bom, ings)
