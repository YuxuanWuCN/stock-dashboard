# Implementation Plan: 仓库目录整理与密钥外置

**Branch**: `006-repo-organization` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: /specs/006-repo-organization/spec.md

## Summary

把真实密钥 `api-key.txt` 从 2.0版 根目录外置到 `D:\股票分析项目\`（2.0版 上一级），改 `src/llm/config.py` 的密钥默认路径并保留向后兼容回退；把"研究过程产出"（自荐/研读 PDF、封箱检验产物、历史总结 MD、一次性脚本、散图）迁移到 `D:\股票分析项目\research-outputs\`（git 仓库之外）。纯迁移 + 配置路径改动，不删除、不改主程序逻辑。

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: 无新增（仅 pathlib / os 路径解析）

**Storage**: 文件系统；密钥为单行文本文件；研究产出为 PDF/JSON/PNG/MD

**Testing**: pytest（密钥解析的正常/回退/缺失路径）

**Target Platform**: Windows 本地 + GitHub Pages 静态前端

**Project Type**: 单体 Python 分析系统 + 静态前端

**Performance Goals**: N/A（路径解析为 O(1) 文件检查）

**Constraints**: 不破坏每日流水线（LLM 报告降级行为保持）；不删除文件；迁移幂等

**Scale/Scope**: 单仓库；约 30+ 文件迁移

## Constitution Check

*GATE: 依据 2.0版/AGENTS.md（项目事实章程，.specify/memory/constitution.md 仍为模板占位）*

1. **质量工作流**：本 feature 唯一的源码改动是 `src/llm/config.py` 的密钥默认路径 → 修改前运行 `tools/run_quality.ps1 begin-unit`，完成后按 small→medium→heavy 测试。
2. **数据与测试**：密钥解析需覆盖正常/回退/缺失/环境变量覆盖 4 条路径；不覆盖原始数据（迁移是移动不是覆盖）。
3. **独立复核**：密钥外置后，用独立脚本断言 `2.0版\api-key.txt` 不存在且新路径存在、LLMClient 仍能读到 key，不依赖测试退出码作唯一证据。

## Project Structure

### Documentation (this feature)

```text
specs/006-repo-organization/
├── plan.md              # 本文件
├── spec.md              # 功能规范
├── tasks.md             # 任务列表
└── checklists/
    └── requirements.md  # 需求检查清单
```

### 迁移目标（仓库外，非 git 管理）

```text
D:\股票分析项目\research-outputs\
├── reports\      # 自荐/研读 PDF
├── sealed-box\   # 封箱检验 JSON/PNG/MD
├── summaries\    # 历史总结 MD
├── scripts\      # 一次性脚本（PDF生成器/封箱/对比）
└── figures\      # figures_test.png 等散图
```

**Structure Decision**: 2.0版 保持单项目结构；"研究产出"整体迁出到仓库外的 `research-outputs/`，不进入 git（避免研究垃圾污染功能提交历史）。

## Complexity Tracking

无（无新增项目/抽象；仅为路径改动 + 文件迁移）
