# 🏆 R-FinGPTv2（中国国际大学生创新大赛 · 国创版本）

本文件夹为 **2026 中国国际大学生创新大赛（达观数据产业命题）** 独立封闭参赛工作空间。

## 📁 目录架构导览

```
D:\R-FinGPTv2（国创版本）\
├── 2026中国国际大学生创新大赛_产业命题申报书_Rainbow-FinGPT.md  # 🌟 官方申报书 (附件3)
├── 达观数据产业命题答卷方案.md                                    # 📘 命题答卷白皮书
├── research-outputs/                                          # 📑 参赛实证成果库
│   └── reports/                                              # 10+ 篇出版级实证研报 PDF
│       ├── 存储超级周期_物理隔绝真实交易实测研报.pdf
│       ├── 黄金地缘避险_物理隔绝真实交易实测研报.pdf
│       ├── 688525_佰维存储_存储超级周期深度实证报告.pdf
│       └── ...
└── Rainbow_FinGPTv2/                                         # ⚡ 核心量化投研智能体系统
    ├── src/                                                  # 三层解耦核心源码 (RAG / 定价 / 风控)
    ├── docs/                                                 # Web 交互看板 (自选股/模拟盘/妖股鉴定器)
    ├── data/raw/                                             # 物理隔离数据集 (存储/黄金/60天实盘)
    ├── tools/                                                # 自动化流水线 & PDF生成工具
    └── tests/                                                # 完整 pytest 自动化测试套件
```

## 🚀 常用操作指引

### 1. 启动本地全功能量化看板
```bash
cd Rainbow_FinGPTv2
python -m http.server 8000 --directory docs
```
浏览器访问: `http://127.0.0.1:8000`

### 2. 运行物理隔离样本外回测
```bash
cd Rainbow_FinGPTv2
python -m pytest tests/test_storage_backtest_runner.py tests/test_gold_backtest_runner.py
```

### 3. 一键重新生成所有实证 PDF 研报
```bash
cd Rainbow_FinGPTv2
python tools/generate_contest_matrix_pdf.py
python tools/generate_isolated_storage_dossier_pdf.py
python tools/generate_isolated_gold_dossier_pdf.py
```
