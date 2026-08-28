"""tests/test_secret_key_resolver.py —— 密钥文件路径解析（006 外置）单元测试。"""

from src.llm.config import resolve_api_key_file_path


def test_env_value_has_highest_priority(tmp_path):
    """环境变量路径优先于所有默认路径。"""
    external = tmp_path / "external" / "api-key.txt"
    legacy = tmp_path / "legacy" / "api-key.txt"
    env = str(tmp_path / "custom-key.txt")
    assert resolve_api_key_file_path(env, external, legacy) == env


def test_external_path_wins_when_exists(tmp_path):
    """外置路径存在时优先于旧路径。"""
    external = tmp_path / "external" / "api-key.txt"
    external.parent.mkdir(parents=True)
    external.write_text("sk-external", encoding="utf-8")
    legacy = tmp_path / "legacy" / "api-key.txt"
    assert resolve_api_key_file_path(None, external, legacy) == str(external)


def test_legacy_path_fallback_when_external_missing(tmp_path):
    """外置缺失但旧路径存在时回退旧路径（迁移过渡期兼容）。"""
    external = tmp_path / "external" / "api-key.txt"  # 不存在
    legacy = tmp_path / "legacy" / "api-key.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("sk-legacy", encoding="utf-8")
    assert resolve_api_key_file_path(None, external, legacy) == str(legacy)


def test_both_missing_returns_external_for_safe_degrade(tmp_path):
    """双缺失时返回外置路径，由 llm_client 读不到 key 时安全降级（不 crash）。"""
    external = tmp_path / "external" / "api-key.txt"  # 不存在
    legacy = tmp_path / "legacy" / "api-key.txt"  # 不存在
    assert resolve_api_key_file_path(None, external, legacy) == str(external)
