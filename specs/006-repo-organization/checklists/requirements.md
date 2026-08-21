# Requirements Checklist: 006-repo-organization

> 验证方式：静态审阅 + pytest（tests/test_secret_key_resolver.py）+ 独立断言脚本

| ID | 需求 | 状态 | 证据 |
|----|------|------|------|
| FR-001 | 密钥默认路径外置 + 环境变量最高优先 | ✅ 通过 | config.py resolve_api_key_file_path；test_env_value_has_highest_priority |
| FR-002 | 旧路径回退 + warning | ✅ 通过 | test_legacy_path_fallback_when_external_missing |
| FR-003 | 无 key 降级不 crash | ✅ 通过 | test_both_missing_returns_external_for_safe_degrade + LLMClient 既有行为 |
| FR-004 | 只移动不删除 | ✅ 通过 | 迁移 34 项产出到 research-outputs/（PDF/封箱/总结/脚本/图） |
| FR-005 | 不破坏主程序 | ✅ 通过 | grep 确认无引用 + 全量 555 passed 无回归 |
| FR-006 | 幂等迁移 | ✅ 通过 | 目标已存在跳过逻辑 |
| FR-007 | .env.example/README 更新路径约定 | ✅ 通过 | .env.example 注释 + README/README_CN 密钥段 |
| FR-008 | 密钥解析 pytest 覆盖 | ✅ 通过 | tests/test_secret_key_resolver.py（4 用例） |

## 独立复核（AGENTS.md 第 3 条）

- 断言脚本：外置路径命中（True）、2.0版 内无残留（True）、LLMClient._api_key_source=="file"、key_len=35
