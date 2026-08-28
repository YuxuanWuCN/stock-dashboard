# src/llm/llm_client.py —— 统一 LLM 客户端（OpenAI 兼容接口）
#
# 默认对接 DeepSeek；无 API Key 或调用失败时降级为模板/规则生成。
# API 密钥只保存在内存中，错误日志和报告元数据均不得包含密钥。

import logging
import os
from pathlib import Path
from typing import Any, Optional, Protocol

from .config import (
    DEEPSEEK_V4_FLASH_MODEL,
    LLM_BACKEND,
    LLM_CONFIG,
    LLM_DAILY_CALL_LIMIT,
    LLM_ENABLED,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger("stock-dashboard.llm.client")


class LLMUnavailableError(RuntimeError):
    """表示 LLM 不可用，并携带可安全记录的错误类别。"""

    def __init__(self, message: str, category: str = "unavailable") -> None:
        super().__init__(message)
        self.category = category


class LLMCompletionClient(Protocol):
    """报告与情感模块依赖的最小 LLM 客户端协议。"""

    @property
    def is_available(self) -> bool:
        """返回客户端当前是否可以调用。"""

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ) -> str:
        """返回一段文本补全。"""


def _classify_api_error(exc: Exception) -> tuple[str, Optional[int]]:
    """把 SDK 异常归一为不包含敏感信息的错误类别。"""
    status_code = getattr(exc, "status_code", None)
    if status_code in (401, 403):
        return "authentication", status_code
    if status_code == 429:
        return "rate_limit", status_code
    if isinstance(status_code, int) and status_code >= 500:
        return "server_error", status_code

    class_name = type(exc).__name__.lower()
    if "timeout" in class_name:
        return "timeout", status_code
    if "connection" in class_name:
        return "connection", status_code
    return "api_error", status_code


def _safe_error_message(category: str) -> str:
    messages = {
        "authentication": "LLM 认证失败，请检查 API Key",
        "rate_limit": "LLM 请求达到限流",
        "server_error": "LLM 服务端暂时不可用",
        "timeout": "LLM 请求超时",
        "connection": "无法连接 LLM 服务",
        "invalid_response": "LLM 返回结构无效",
        "api_error": "LLM API 调用失败",
    }
    return messages.get(category, "LLM 不可用")


class LLMClient:
    """调用 OpenAI 兼容接口的同步客户端。"""

    def __init__(
        self,
        backend: Optional[str] = None,
        *,
        api_key: Optional[str] = None,
        api_key_file: Optional[str] = None,
    ) -> None:
        selected_backend = LLM_BACKEND if backend is None else backend
        self.backend = selected_backend.strip().lower()
        self._call_count = 0
        self._last_error_category = ""
        self._api_key_source = ""

        template = LLM_CONFIG.get(self.backend)
        self._config = dict(template) if template else None
        if self._config and self.backend == "deepseek":
            self._config["base_url"] = os.environ.get(
                "DEEPSEEK_BASE_URL",
                str(self._config["base_url"]),
            ).strip()
            self._config["model"] = DEEPSEEK_V4_FLASH_MODEL

        self._api_key = self._resolve_api_key(api_key, api_key_file)
        self._initial_unavailable_reason = self._get_initial_unavailable_reason()
        self.enabled = not self._initial_unavailable_reason

    @classmethod
    def disabled(cls) -> "LLMClient":
        """创建一个明确禁用、不会读取密钥或发起请求的客户端。"""
        return cls("")

    def _get_initial_unavailable_reason(self) -> str:
        if not LLM_ENABLED:
            return "disabled_by_config"
        if not self.backend:
            return "llm_disabled"
        if not self._config:
            return "unsupported_backend"
        if not self._api_key:
            return "missing_api_key"
        return ""

    def _resolve_api_key(
        self,
        explicit_api_key: Optional[str],
        api_key_file: Optional[str],
    ) -> str:
        if not self._config:
            return ""
        if explicit_api_key is not None:
            key = explicit_api_key.strip()
            self._api_key_source = "explicit" if key else ""
            return key

        env_name = str(self._config.get("api_key_env", ""))
        env_key = os.environ.get(env_name, "").strip()
        if env_key:
            self._api_key_source = "environment"
            return env_key

        default_key = str(self._config.get("default_api_key", "") or "").strip()
        if default_key:
            self._api_key_source = "default"
            return default_key

        key_path = self._config.get("api_key_file") if api_key_file is None else api_key_file
        file_key = self._read_api_key_file(str(key_path or ""))
        if file_key:
            self._api_key_source = "file"
        return file_key

    @staticmethod
    def _read_api_key_file(path: str) -> str:
        """读取被 Git 忽略的本地密钥文件，不记录文件内容。"""
        if not path:
            return ""
        try:
            raw = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return ""

        for line in raw.splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            if "=" in value:
                name, candidate = value.split("=", 1)
                if name.strip() == "DEEPSEEK_API_KEY":
                    value = candidate.strip()
            return value.strip().strip('"').strip("'")
        return ""

    @property
    def is_available(self) -> bool:
        """返回当前客户端是否具备调用条件。"""
        return self.enabled

    @property
    def model(self) -> str:
        """返回实际请求使用的模型名。"""
        return str(self._config.get("model", "")) if self._config else ""

    @property
    def call_count(self) -> int:
        """返回当前进程已发起的 API 请求数。"""
        return self._call_count

    @property
    def remaining_calls(self) -> int:
        """返回当前进程预算内的剩余请求数。"""
        return max(0, LLM_DAILY_CALL_LIMIT - self._call_count)

    @property
    def unavailable_reason(self) -> str:
        """返回可安全写入报告的不可用原因。"""
        return self._last_error_category or self._initial_unavailable_reason

    @property
    def metadata(self) -> dict[str, Any]:
        """返回不含 API Key、提示词或原始响应的客户端元数据。"""
        return {
            "backend": self.backend or "disabled",
            "model": self.model,
            "mode": "api" if self.is_available else "disabled",
            "fallback_reason": self.unavailable_reason,
        }

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.3,
    ) -> str:
        """调用 LLM 并返回非空文本。

        Raises:
            LLMUnavailableError: 客户端不可用、达到限额、API 失败或响应结构无效。
        """
        if not self.enabled:
            reason = self.unavailable_reason or "unavailable"
            raise LLMUnavailableError(_safe_error_message(reason), category=reason)
        if self._call_count >= LLM_DAILY_CALL_LIMIT:
            raise LLMUnavailableError(
                f"已达每进程调用上限 {LLM_DAILY_CALL_LIMIT}",
                category="call_limit",
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailableError(
                "openai 客户端未安装",
                category="missing_dependency",
            ) from exc

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._config["base_url"],
            timeout=LLM_TIMEOUT_SECONDS,
        )
        effective_max = max_tokens or LLM_MAX_TOKENS
        if "v4" in self.model:
            effective_max = max(effective_max, 500)

        self._call_count += 1
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=effective_max,
                temperature=temperature,
            )
            choices = getattr(response, "choices", None)
            if not choices:
                raise LLMUnavailableError(
                    "LLM 返回空 choices",
                    category="invalid_response",
                )
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if not isinstance(content, str) or not content.strip():
                raise LLMUnavailableError(
                    "LLM 返回空 content",
                    category="invalid_response",
                )
            self._last_error_category = ""
            return content.strip()
        except LLMUnavailableError as exc:
            self._last_error_category = exc.category
            raise
        except Exception as exc:
            category, status_code = _classify_api_error(exc)
            self._last_error_category = category
            logger.warning(
                "LLM 调用失败（backend=%s model=%s category=%s status=%s）",
                self.backend,
                self.model,
                category,
                status_code,
            )
            raise LLMUnavailableError(
                _safe_error_message(category),
                category=category,
            ) from exc


def diagnose_llm_connection(verbose: bool = True) -> dict[str, Any]:
    """诊断当前环境中的 LLM 凭证与连接状态，输出清晰的调试报告。"""
    client = LLMClient()
    status = {
        "enabled": client.is_available,
        "backend": client.backend,
        "model": client.model,
        "api_key_source": client._api_key_source or "none",
        "unavailable_reason": client.unavailable_reason or "none",
    }
    if verbose:
        print("\n" + "="*55)
        print(" [Rainbow-FinGPT] LLM 后端智能诊断")
        print("="*55)
        ready_text = "[OK] 已就绪 (Ready)" if client.is_available else "[WARN] 离线降级 (Offline)"
        print(f" - 状态 (Available):     {ready_text}")
        print(f" - 当前后端 (Backend):   {client.backend}")
        print(f" - 模型名称 (Model):     {client.model}")
        key_text = client._api_key_source or "未检测到密钥 (建议配置 api-key.txt 或启动本地 Ollama)"
        print(f" - 密钥来源 (Key Source): {key_text}")
        if not client.is_available:
            print(f" - 离线原因 (Reason):     {client.unavailable_reason}")
            print("\n [提示]：在根目录新建 api-key.txt 填入 API Key，或启动本地 Ollama 即可开启实时推理。")
        print("="*55 + "\n")
    return status



