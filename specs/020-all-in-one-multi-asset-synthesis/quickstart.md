# 快速上手指南：020-all-in-one-multi-asset-synthesis
# 全域多资产因果量化投研中台快速上手 (Multi-Asset Quickstart Guide)

**规格**：`specs/020-all-in-one-multi-asset-synthesis/spec.md`  
**日期**：2026-09-30  

---

## 1. 环境准备 (Prerequisites)

- **Python 版本**：Python 3.10+ (推荐 Python 3.11 / 3.13)
- **核心依赖项**：
  ```bash
  pip install -r requirements.txt
  # 关键依赖：pandas, numpy, scipy, statsmodels, scikit-learn, flask, pytest
  ```

---

## 2. 分赛道测试与门禁验证 (Domain Testing)

系统采用分层多资产架构，支持按赛道独立运行测试，亦支持全量跨资产集成测试：

### 2.1 基础数学与因果推理核心测试
```bash
# 验证 Fama-MacBeth 回归、Newey-West HAC 稳健标准误、物理因果本体论
pytest tests/core/ tests/test_causal_ontology.py -v
```

### 2.2 A 股权益与大创赛资产测试
```bash
# 验证 202 股票池、存储超级周期、黄金杠铃策略及 CSMAR 行情走步回测
pytest tests/test_fama_macbeth_engine.py tests/test_storage_backtest_runner.py tests/test_monster_reviewer.py -v
```

### 2.3 郑商所商品期现套保与双轨保障测试
```bash
# 验证 ADR-0001 两层解耦、一票否决代码门禁、极星 19.5 插件规范
pytest tests/test_two_layer_decoupling.py -v
```

### 2.4 全域跨资产集成契约测试
```bash
pytest tests/integration/test_multi_asset_synthesis.py -v
```

---

## 3. 运行统一全景交互终端 (Launching Web Terminal)

### 3.1 零依赖离线演示模式 (适用于答辩现场弱网/无网环境)
- **银发普惠与学术双核终端**：直接双击或通过本地浏览器打开 `docs/index_wealth.html`。
- **A 股机构量化看板**：打开 `docs/index.html`。
- **郑商所跨资产期望盈余看板**：打开 `docs/index_commodity.html`（或从主看板顶部导航一键穿透）。

### 3.2 动态 API 服务模式
```bash
# 启动多资产统一网关服务 (监听端口 5000)
python start_local.py
```
访问 `http://localhost:5000` 即可通过统一导航栏在不同资产轨道间平滑切换。

---

## 4. 赛事材料调取路径 (Accessing Competition Materials)

所有赛事申报与路演材料已实现物理严格隔离，防止赛道混淆：

1. **2026 中国国际大学生创新大赛（大创赛 / 达观数据命题）**：
   - 申报书与填报版：`competitions/dachuang_2026/2026中国国际大学生创新大赛_产业命题申报书_Rainbow-FinGPT.md`
   - 18 页金牌路演文稿：`competitions/dachuang_2026/2026中国国际大学生创新大赛_18页校赛金牌路演PPT全景设计与逐页演讲文稿_最终完美版.md`
   - 评委攻防手册：`competitions/dachuang_2026/评委答辩专家攻防QA靶向演练手册.md`

2. **郑商所衍生品大赛（郑商所杯 / 极星量化）**：
   - 研究计划与论文：`competitions/czce_futures/01_研究计划与论文/`
   - 极星 19.5 插件工程：`competitions/czce_futures/02_极星量化与实盘/`
   - 纯碱玻璃算法与回测：`competitions/czce_futures/03_算法模型与回测/`
