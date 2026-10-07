"""出成率验收：定义仓/当前单/历史单/库存 四套口径 + 并发同一套成败。"""
import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.models import Base, BomLine, Ingredient, PrepRun
from app.services.seed import seed_if_empty


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/t.db",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    SessionT = sessionmaker(bind=engine)
    db = SessionT()
    seed_if_empty(db)
    db.close()

    def _get_db():
        s = SessionT()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app), SessionT
    app.dependency_overrides.clear()


def _bom_line_id(client, dish_name, ingredient_name):
    for row in client.get("/api/bom").json():
        if row["dish_name"] == dish_name and row["ingredient_name"] == ingredient_name:
            return row["id"]
    raise AssertionError(f"未找到定额行 {dish_name}/{ingredient_name}")


def _need(client, ingredient_name):
    data = client.get("/api/prep/latest?order_id=1").json()
    for line in data["prep_lines"]:
        if line["ingredient_name"] == ingredient_name:
            return line["need_qty"]
    raise AssertionError(f"备料单缺行 {ingredient_name}")


def _save(client, line_id, rate):
    return client.put("/api/bom/yield-rates", json={"rates": [{"id": line_id, "yield_rate": rate}]})


def test_save_rewrites_current_sheet_but_not_history_or_stock(env):
    client, SessionT = env
    run1 = client.post("/api/prep/run?order_id=1").json()
    assert _need(client, "五花肉") == 10.0  # 40 份 × 0.25，未写率 = 一层展开
    stock_before = client.get("/api/inventory").json()
    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")

    res = _save(client, line_id, 0.5)
    assert res.status_code == 200, res.text

    # 定义仓已落新率
    row = [r for r in client.get("/api/bom").json() if r["id"] == line_id][0]
    assert row["yield_rate"] == 0.5
    # 当前有效单整张按新率重写：需求变大，缺料贴跟着变
    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] != run1["id"]
    assert _need(client, "五花肉") == 20.0  # 40 × 0.25 / 0.5
    pork = [s for s in latest["shortages"] if s["ingredient_name"] == "五花肉"][0]
    assert pork["shortage"] == 12.0
    # 已存档历史单一字未改
    db = SessionT()
    old = db.get(PrepRun, run1["id"])
    old_pork = [l for l in json.loads(old.result_json)["prep_lines"] if l["ingredient_name"] == "五花肉"][0]
    assert old_pork["need_qty"] == 10.0
    db.close()
    # 库存结存保存前后同一个数（保存不是领料）
    assert client.get("/api/inventory").json() == stock_before


def test_smaller_rate_bigger_need(env):
    client, _ = env
    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")
    assert _save(client, line_id, 0.8).status_code == 200
    assert _need(client, "五花肉") == 12.5
    assert _save(client, line_id, 0.5).status_code == 200
    assert _need(client, "五花肉") == 20.0


def test_rate_one_and_cleared_match_legacy(env):
    client, _ = env
    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")
    assert _save(client, line_id, 1.0).status_code == 200
    assert _need(client, "五花肉") == 10.0
    assert _save(client, line_id, None).status_code == 200
    assert _need(client, "五花肉") == 10.0
    row = [r for r in client.get("/api/bom").json() if r["id"] == line_id][0]
    assert row["yield_rate"] is None


@pytest.mark.parametrize("bad", [0, 1.5])
def test_invalid_rate_rolls_back_everything(env, bad):
    client, SessionT = env
    run1 = client.post("/api/prep/run?order_id=1").json()
    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")

    res = _save(client, line_id, bad)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "出成率" in detail
    assert "结存" not in detail and "库存不足" not in detail  # 失败说明不许写成结存不够

    # 定义仓退回
    row = [r for r in client.get("/api/bom").json() if r["id"] == line_id][0]
    assert row["yield_rate"] is None
    # 当前单与缺料贴退回保存前（还是原来那张，需求没动）
    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == run1["id"]
    assert _need(client, "五花肉") == 10.0
    # 没有多落任何一张单
    db = SessionT()
    assert len(db.scalars(select(PrepRun)).all()) == 1
    db.close()


def test_latest_never_fakes_a_sheet(env):
    client, _ = env
    assert client.get("/api/prep/latest?order_id=1").status_code == 404
    res = client.get("/api/prep/shortages?order_id=1").json()
    assert res["shortages"] == []
    # 读过之后库里仍然一张单都没有：读不落库
    assert client.get("/api/prep/latest?order_id=1").status_code == 404


def test_save_and_generate_race_lands_on_one_outcome(env):
    client, _ = env
    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")
    rates = [0.5, 0.8, 0.25, 1.0, 0.6]
    errors = []

    def save(rate):
        try:
            r = TestClient(app).put("/api/bom/yield-rates",
                                    json={"rates": [{"id": line_id, "yield_rate": rate}]})
            assert r.status_code == 200, r.text
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def gen():
        try:
            r = TestClient(app).post("/api/prep/run?order_id=1")
            assert r.status_code == 200, r.text
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    for rate in rates:
        ts = [threading.Thread(target=save, args=(rate,)), threading.Thread(target=gen)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # 每一轮结束：当前有效单必须跟定义仓是同一套率，禁止一边新率一边旧率
        expected = round(40 * 0.25 / rate, 3)
        assert _need(client, "五花肉") == expected
    assert errors == []


def test_archived_order_not_rewritten(env):
    client, SessionT = env
    # 把当前订单存档（status != open），它就不再是"当前有效单"
    from app.models.models import KitchenOrder
    db = SessionT()
    run1 = client.post("/api/prep/run?order_id=1").json()
    order = db.get(KitchenOrder, 1)
    order.status = "archived"
    db.commit()
    db.close()

    line_id = _bom_line_id(client, "红烧肉套餐", "五花肉")
    res = _save(client, line_id, 0.5)
    assert res.status_code == 200
    assert res.json()["rewritten"] == []  # 没有 open 订单可重写
    # 存档单还是保存前那张
    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == run1["id"]
    db = SessionT()
    old = db.get(PrepRun, run1["id"])
    old_pork = [l for l in json.loads(old.result_json)["prep_lines"] if l["ingredient_name"] == "五花肉"][0]
    assert old_pork["need_qty"] == 10.0
    # 定义仓照样落新率（定义与历史单分套）
    assert db.get(BomLine, line_id).yield_rate == 0.5
    # 库存依旧没动
    assert db.get(Ingredient, 1).stock_qty == 8.0
    db.close()
