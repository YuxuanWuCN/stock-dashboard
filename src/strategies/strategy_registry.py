"""策略注册表 —— 移植自 KHunter strategy/strategy_registry.py，去 yaml 依赖。

配置从 config/strategy_params.json 读取（与项目 JSON 数据体系一致），
策略自动从 src/strategies/ 目录扫描注册。
"""

import importlib
import json
from pathlib import Path
from typing import Optional

from src.strategies.base_strategy import BaseStrategy

DEFAULT_PARAMS_FILE = "config/strategy_params.json"


class StrategyRegistry:
    """策略注册器：自动扫描目录、按配置实例化策略。"""

    def __init__(self, params_file: str = DEFAULT_PARAMS_FILE):
        self.strategies = {}
        self.params_file = Path(params_file)
        self.params = self._load_params()

    def _load_params(self) -> dict:
        if self.params_file.exists():
            with open(self.params_file, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        return {}

    def register(self, strategy_class, name: Optional[str] = None):
        """注册策略类，从配置加载参数并实例化。"""
        strategy_name = name or strategy_class.__name__
        strategies_config = self.params.get("strategies", {})
        strategy_config = strategies_config.get(strategy_name, {})
        params = strategy_config.get("params", {}) or {}

        strategy = strategy_class(params=params)
        strategy.metadata = {
            k: strategy_config.get(k)
            for k in ("display_name", "description", "icon", "color")
            if k in strategy_config
        }
        strategy.param_groups = strategy_config.get("param_groups", [])
        strategy.param_details = strategy_config.get("param_details", {})
        self.strategies[strategy_name] = strategy
        return strategy

    def _load_strategy_params(self, strategy_name: str) -> dict:
        """从配置文件加载指定策略的最新参数。"""
        strategies_config = self.params.get("strategies", {})
        strategy_config = strategies_config.get(strategy_name, {})
        return strategy_config.get("params", {}) or {}

    def get_strategy(self, name: str):
        """获取策略（每次从配置重载参数）。"""
        if name not in self.strategies:
            return None
        latest_params = self._load_strategy_params(name)
        strategy_class = type(self.strategies[name])
        new_strategy = strategy_class(params=latest_params)
        new_strategy.metadata = getattr(self.strategies[name], "metadata", {})
        new_strategy.param_groups = getattr(self.strategies[name], "param_groups", [])
        new_strategy.param_details = getattr(self.strategies[name], "param_details", {})
        self.strategies[name] = new_strategy
        return new_strategy

    def list_strategies(self) -> list:
        """列出已注册策略名。"""
        return list(self.strategies.keys())

    def auto_register_from_directory(self, strategy_dir: str = ""):
        """自动扫描目录注册所有继承 BaseStrategy 的策略类。"""
        if not strategy_dir:
            strategy_dir = str(Path(__file__).parent)
        strategy_path = Path(strategy_dir)

        for py_file in sorted(strategy_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            try:
                module = importlib.import_module(f"src.strategies.{module_name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type)
                            and issubclass(attr, BaseStrategy)
                            and attr is not BaseStrategy):
                        # 只注册本模块定义的策略类（跳过继承自其他模块的）
                        if getattr(attr, "__module__", "") != f"src.strategies.{module_name}":
                            continue
                        self.register(attr, name=attr.__name__)
            except Exception as e:  # noqa: BLE001 - 单策略加载失败不影响整体
                print(f"  [ERROR] 加载 {module_name} 失败: {e}")

    def run_strategy(self, strategy_name: str, stock_data_dict: dict) -> dict:
        """对 {code: (name, df)} 运行单个策略，返回 {strategy_name: [signals]}。"""
        strategy = self.get_strategy(strategy_name)
        if strategy is None:
            return {}
        signals = []
        for code, (name, df) in stock_data_dict.items():
            result = strategy.analyze_stock(code, name, df)
            if result:
                signals.append(result)
        return {strategy_name: signals}

    def run_all(self, stock_data_dict: dict) -> dict:
        """对所有已注册策略运行选股。"""
        results = {}
        for strategy_name in self.list_strategies():
            results.update(self.run_strategy(strategy_name, stock_data_dict))
        return results


_registry = None


def get_registry(params_file: str = DEFAULT_PARAMS_FILE) -> StrategyRegistry:
    """获取全局策略注册器。"""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry(params_file)
    return _registry
