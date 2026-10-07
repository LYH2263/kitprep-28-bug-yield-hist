# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护中央厨房出品与用料树。
2. 在「BOM」定额表填写出成率（范围 (0, 1]，留空按 1 展开）并保存：定义仓与当前有效备料单同一事务整张重写，已存档历史单一字不改，库存结存不受保存影响。
3. 在「订单」「库存」确认当日需求与现有库存。
4. 打开「备料单」查看已落库的当前有效单（只读不现算），点「生成备料单」按当前定额落新单。
5. 在「缺料」查看 need − stock 为正的原料。

## 开发与测试

```bash
docker compose exec api pytest -q
```
