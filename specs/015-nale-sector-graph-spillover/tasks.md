# 任务列表: Spec 015

## Phase 1: 核心引擎实现 (Core Engine)
- [ ] T1: 创建 `src/graph/sector_graph_engine.py`，实现拓扑图构建、板块广度计算、涨停识别与 NALE 消息传播
- [ ] T2: 创建 `tests/test_sector_graph_engine.py` 并通过单元测试

## Phase 2: 评分与流水线集成 (Pipeline Integration)
- [ ] T3: 修改 `src/build_ranking.py` 接入 `SectorGraphEngine`
- [ ] T4: 批量运行并验证 `analysis/{code}.json` 与 `ranking_v3.json` 包含 `nale_network` 节点属性

## Phase 3: 前端交互与看板呈现 (Frontend Presentation)
- [ ] T5: 在 `docs/index.html` 中新增 NALE 板块协同卡片容器
- [ ] T6: 在 `docs/assets/app.js` 中实现 `renderNaleNetworkCard`
- [ ] T7: 在 `docs/assets/style.css` 中添加 NALE 图谱与梯队标签样式

## Phase 4: 质量门禁与代码审查 (Quality & Review)
- [ ] T8: 执行全套单元测试
- [ ] T9: 执行双轴 `/code-review`
- [ ] T10: Git 提交并推送到 main 与 teacher-framework-refactor
