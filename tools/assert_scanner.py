"""弱断言扫描器（彩虹找虫 v2）。

用 AST 扫描测试目录，找出 peaks-mut 五模式对应的 Python 弱断言：
测试"看起来在断言，实际什么都没验证"的常见写法。

设计约束（v2 信任红线）：
- 纯标准库，零第三方依赖（ast/pathlib/json/sys）
- 全部 UTF-8 读写，stdout 防御性 reconfigure（GBK 坑）
- 不读 stdin，不写任何门禁状态
- 扫描失败（语法错误等）逐文件跳过并报告，不整体失败（fail-open）
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_TEST_DIR = "tests"
DEFAULT_MAX_RATIO = 0.05  # 弱断言占比上限（对应 peaks ≤5%）

# 弱断言模式表：pattern 名 -> 描述/严重级
# severity: error = 一定程度的假绿（自比较、恒真字面量、无断言）
#           warn  = 弱验证（裸 assertTrue(x)、assertIsNotNone）
PATTERNS: dict[str, dict] = {
    "assert-true-bare": {
        "severity": "warn",
        "desc": "assertTrue(x)/assert_(x) 且 x 不是比较/调用/带条件的表达式（弱验证）",
    },
    "assert-is-not-none": {
        "severity": "warn",
        "desc": "assertIsNotNone(x)（弱验证，任何非 None 值都通过）",
    },
    "assert-equal-self": {
        "severity": "error",
        "desc": "assertEqual(a, b)/assertEquals/assertIs(a, b) 且 a 与 b 是同一对象（自比较假绿）",
    },
    "assert-in-self": {
        "severity": "error",
        "desc": "assertIn(a, b) 且 a 与 b 是同一对象（自包含假绿）",
    },
    "assert-compare-self": {
        "severity": "error",
        "desc": "assertGreater/assertLess/assertAlmostEqual(a, b) 且 a 与 b 是同一对象",
    },
    "assert-literal-constant": {
        "severity": "error",
        "desc": "断言参数为字面量恒真（assertTrue(True)/assertEqual(1, 1)）",
    },
    "no-assert": {
        "severity": "error",
        "desc": "test_ 函数体没有任何断言调用（测试等于没测）",
    },
}

# 比较类断言方法（带两个参数，需检查自比较）
_COMPARE_ASSERT_METHODS = {
    "assertEqual",
    "assertEquals",
    "assertNotEqual",
    "assertIs",
    "assertIsNot",
    "assertIn",
    "assertNotIn",
    "assertGreater",
    "assertGreaterEqual",
    "assertLess",
    "assertLessEqual",
    "assertAlmostEqual",
    "assertNotAlmostEqual",
}

# 自比较 -> pattern 归类（按方法族区分）
_SELF_EQUAL_METHODS = {"assertEqual", "assertEquals", "assertNotEqual", "assertIs", "assertIsNot"}
_SELF_IN_METHODS = {"assertIn", "assertNotIn"}
_SELF_COMPARE_METHODS = {
    "assertGreater",
    "assertGreaterEqual",
    "assertLess",
    "assertLessEqual",
    "assertAlmostEqual",
    "assertNotAlmostEqual",
}

# 单参数弱断言方法
_WEAK_ASSERT_METHODS = {
    "assertTrue": "assert-true-bare",
    "assert_": "assert-true-bare",
    "assertIsNotNone": "assert-is-not-none",
    "assertIsNone": None,  # 合法断言（检查 None），不报
}

# 所有断言方法名集合（用于统计总断言数与 no-assert 判定）
_ALL_ASSERT_METHODS = _COMPARE_ASSERT_METHODS | set(_WEAK_ASSERT_METHODS) | {
    "assertRaises",
    "assertRaisesRegex",
    "assertWarns",
    "assertRegex",
    "assertNotRegex",
    "assertCountEqual",
    "assertMultiLineEqual",
    "assertSequenceEqual",
    "assertListEqual",
    "assertTupleEqual",
    "assertSetEqual",
    "assertDictEqual",
    "assertTrue",
    "assertFalse",
    "fail",
} | {
    # mock 框架的验证方法（合法的行为验证，不算弱断言也不算 no-assert）
    "assert_called_once",
    "assert_called_once_with",
    "assert_called",
    "assert_called_with",
    "assert_not_called",
    "assert_has_calls",
    "assert_any_call",
} | {
    # numpy/pandas testing 断言（np.testing.assert_array_equal 等，合法强断言）
    "assert_array_equal",
    "assert_array_almost_equal",
    "assert_allclose",
    "assert_almost_equal",
    "assert_equal",
    "assert_raises",
} | {
    # pytest 上下文管理器（with pytest.raises(...) 是合法异常断言）
    "raises",
    "warns",
}

# 模块级断言前缀（np.testing.assert_* / pd.testing.assert_*）
_MODULE_ASSERT_PREFIXES = ("testing.assert",)
# 模块级断言方法（属于 np.testing 家族）
_MODULE_ASSERT_METHODS = {
    "assert_array_equal",
    "assert_array_almost_equal",
    "assert_allclose",
    "assert_almost_equal",
    "assert_raises",
}

# 强比较检查：参数中有 Compare/Constant/List/Dict/Set/Tuple/Call 等"有内容"节点
# 的 assertTrue(x) 不算弱（assertTrue(a == b) 是合法断言）
_STRONG_ARG_TYPES = (
    ast.Compare,
    ast.Call,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
)


# ---------------------------------------------------------------------------
# 核心扫描
# ---------------------------------------------------------------------------


def weak_assert_patterns() -> dict[str, dict]:
    """返回模式表（可测）。"""
    return {name: dict(meta) for name, meta in PATTERNS.items()}


def _is_strong_arg(node: ast.AST) -> bool:
    """参数是否为"有内容"表达式（强断言不报）。"""
    if isinstance(node, ast.Compare):
        return True
    if isinstance(node, ast.Call):
        return True
    if isinstance(node, ast.Constant):
        # 字面量：True/False/None 之外的常量（如 assertEqual(x, 5)）是强断言
        return not isinstance(node.value, bool) and node.value is not None
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return bool(getattr(node, "elts", None) or getattr(node, "keys", None))
    return False


def _same_node(a: ast.AST | None, b: ast.AST | None) -> bool:
    """两个参数是否为同一对象引用（自比较判定：同一 Name 节点或同一属性链）。"""
    if a is None or b is None:
        return False
    if isinstance(a, ast.Name) and isinstance(b, ast.Name):
        return a.id == b.id
    if isinstance(a, ast.Attribute) and isinstance(b, ast.Attribute):
        try:
            return ast.dump(a) == ast.dump(b)
        except Exception:
            return False
    return False


def _constant_self_compare(a: ast.AST | None, b: ast.AST | None) -> bool:
    """两个字面量常量相等（assertEqual(1, 1)/assertEqual("x", "x")）。"""
    if isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
        try:
            return a.value == b.value and a.value is not None
        except Exception:
            return False
    return False


def _literal_always_true(node: ast.AST | None) -> bool:
    """断言参数为恒真字面量（assertTrue(True)）。"""
    if isinstance(node, ast.Constant):
        return node.value is True
    if isinstance(node, ast.BoolOp):
        return all(_literal_always_true(v) for v in node.values) if isinstance(node.op, ast.And) else any(
            _literal_always_true(v) for v in node.values
        )
    return False


def scan_file(path: Path) -> list[dict]:
    """扫描单个测试文件，返回弱断言 Finding 列表。

    Finding 结构: {"file": str, "line": int, "pattern": str, "code": str, "severity": str}
    """
    findings: list[dict] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        # 语法错误/编码错误：fail-open，记录但不当作弱断言
        findings.append(
            {
                "file": str(path),
                "line": 0,
                "pattern": "parse-error",
                "code": f"无法解析: {exc}",
                "severity": "warn",
            }
        )
        return findings

    # 收集测试函数体（unittest 类方法 + 顶层 test_ 函数）
    test_bodies: list[list[ast.stmt]] = []

    def _collect(node: ast.AST, is_test: bool) -> None:
        if isinstance(node, ast.FunctionDef) and is_test:
            test_bodies.append(node.body)
        for child in ast.iter_child_nodes(node):
            _collect(child, is_test or (isinstance(node, ast.FunctionDef) and node.name.startswith("test")))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            test_bodies.append(node.body)

    for body in test_bodies:
        assert_count = 0
        for stmt in body:
            # pytest 风格裸 assert 语句计入总断言数（不是弱断言）
            for child in ast.walk(stmt):
                if isinstance(child, ast.Assert):
                    assert_count += 1
                    continue
                if isinstance(child, ast.Call):
                    fn = child.func
                    method = None
                    if isinstance(fn, ast.Attribute):
                        method = fn.attr
                        # 模块级断言前缀（np.testing.assert_array_equal → testing.assert 前缀）
                        if method in ("assert_array_equal", "assert_array_almost_equal", "assert_allclose", "assert_almost_equal", "assert_raises"):
                            chain = []
                            node = fn
                            while isinstance(node, ast.Attribute):
                                chain.append(node.attr)
                                node = node.value
                            if ".".join(reversed(chain)).startswith(_MODULE_ASSERT_PREFIXES) or isinstance(node, ast.Name) and node.id in ("np", "pd", "numpy", "pandas"):
                                assert_count += 1
                                continue
                    elif isinstance(fn, ast.Name):
                        method = fn.id
                    if method in _ALL_ASSERT_METHODS:
                        assert_count += 1
                        findings.extend(_scan_assert_call(path, child, method))
        if assert_count == 0:
            # test 函数体无任何断言（只有 docstring/pass/辅助调用）
            has_code = any(
                isinstance(s, (ast.Assign, ast.Expr, ast.Return, ast.Call, ast.With, ast.Try))
                and not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                for s in body
            )
            if has_code:
                findings.append(
                    {
                        "file": str(path),
                        "line": body[0].lineno,
                        "pattern": "no-assert",
                        "code": "test 函数没有任何断言",
                        "severity": "error",
                    }
                )
    return findings


def _scan_assert_call(path: Path, call: ast.Call, method: str) -> list[dict]:
    """扫描单个断言调用，返回该调用命中弱断言模式的 Finding 列表。"""
    args = call.args
    findings: list[dict] = []

    def finding(pattern: str, code: str) -> dict:
        return {
            "file": str(path),
            "line": call.lineno,
            "pattern": pattern,
            "code": code,
            "severity": PATTERNS[pattern]["severity"],
        }

    if method in _COMPARE_ASSERT_METHODS:
        if len(args) >= 2:
            a, b = args[0], args[1]
            if _same_node(a, b):
                if method in _SELF_IN_METHODS:
                    findings.append(finding("assert-in-self", "assertIn(a, a) 自包含"))
                elif method in _SELF_COMPARE_METHODS:
                    findings.append(finding("assert-compare-self", "assertGreater(a, a) 自比较"))
                else:
                    findings.append(finding("assert-equal-self", "assertEqual(a, a) 自比较"))
            elif _constant_self_compare(a, b):
                findings.append(finding("assert-literal-constant", "断言两个相同字面量"))
        return findings

    if method in _WEAK_ASSERT_METHODS:
        pattern = _WEAK_ASSERT_METHODS[method]
        if pattern is None:
            return findings
        if not args:
            return findings
        arg = args[0]
        if _literal_always_true(arg):
            findings.append(finding("assert-literal-constant", f"{method}(恒真字面量)"))
        elif not _is_strong_arg(arg):
            findings.append(finding(pattern, f"{method}({ast.unparse(arg) if hasattr(ast, 'unparse') else '?'})"))
        return findings

    return findings


def _quality_system_test_names() -> set[str]:
    """质量系统自身测试文件名（跳过扫描，避免鸡生蛋）。"""
    try:
        cfg = json.loads((Path(__file__).resolve().parents[1] / ".quality-gates.json").read_text(encoding="utf-8"))
        names = (cfg.get("test_policy") or {}).get("quality_system_test_files", ["test_quality_system.py"])
        return {n.casefold() for n in names}
    except Exception:
        return {"test_quality_system.py"}


def scan_tests(test_root: Path | None = None) -> list[dict]:
    """扫描测试目录，聚合排序。跳过质量系统自身测试（quality_system_test_files）。"""
    root = test_root or (Path(__file__).resolve().parents[1] / DEFAULT_TEST_DIR)
    if not root.is_dir():
        return []
    skip = _quality_system_test_names()
    findings: list[dict] = []
    for path in sorted(root.rglob("test_*.py")):
        if path.name.casefold() in skip:
            continue
        findings.extend(scan_file(path))
    findings.sort(key=lambda f: (f["file"], f["line"]))
    return findings


def summarize(findings: list[dict]) -> dict:
    """汇总统计。"""
    by_pattern: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in findings:
        by_pattern[f["pattern"]] = by_pattern.get(f["pattern"], 0) + 1
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    return {
        "total": len(findings),
        "by_pattern": by_pattern,
        "by_severity": by_severity,
    }


def count_total_asserts(test_root: Path | None = None) -> int:
    """统计测试目录全部断言调用数（含强断言），用于占比。"""
    root = test_root or (Path(__file__).resolve().parents[1] / DEFAULT_TEST_DIR)
    total = 0
    if not root.is_dir():
        return 0
    for path in sorted(root.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                total += 1
                continue
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    method = fn.attr
                    # 模块级断言前缀（np.testing.assert_*）
                    if method in _MODULE_ASSERT_METHODS:
                        chain = []
                        n = fn
                        while isinstance(n, ast.Attribute):
                            chain.append(n.attr)
                            n = n.value
                        if ".".join(reversed(chain)).startswith(_MODULE_ASSERT_PREFIXES) or isinstance(n, ast.Name) and n.id in ("np", "pd", "numpy", "pandas"):
                            total += 1
                            continue
                else:
                    method = fn.id if isinstance(fn, ast.Name) else None
                if method in _ALL_ASSERT_METHODS:
                    total += 1
    return total


def weak_ratio(findings: list[dict], total_asserts: int) -> float:
    """弱断言占比 = 弱断言数 / 总断言数。"""
    if total_asserts <= 0:
        return 0.0
    return len(findings) / total_asserts


def as_result(findings: list[dict], total_asserts: int, max_ratio: float = DEFAULT_MAX_RATIO) -> dict:
    """转成与 quality_gate.result() 同构的检查结果结构。

    passed = 无 error 级弱断言 且 占比 <= max_ratio
    """
    errors = [f for f in findings if f["severity"] == "error"]
    ratio = weak_ratio(findings, total_asserts)
    passed = len(errors) == 0 and ratio <= max_ratio
    lines = [f"{f['file']}:{f['line']} [{f['severity']}] {f['pattern']}: {f['code']}" for f in findings]
    if not lines:
        lines.append("未发现弱断言")
    details = "\n".join(lines[:50])
    if len(lines) > 50:
        details += f"\n…（共 {len(lines)} 条）"
    details += f"\n弱断言占比 {ratio:.1%}（上限 {max_ratio:.0%}），error 级 {len(errors)} 条"
    return {
        "name": "弱断言扫描",
        "passed": passed,
        "details": details,
        "category": "test",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(argv: list[str] | None = None) -> int:
    """CLI 入口：python tools/assert_scanner.py [--json] [--root .]"""
    parser = argparse.ArgumentParser(prog="assert_scanner")
    parser.add_argument("--json", action="store_true", help="输出完整 Finding 列表 JSON")
    parser.add_argument("--root", default=".", help="项目根目录（默认当前目录）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    test_dir = root / DEFAULT_TEST_DIR
    findings = scan_tests(test_dir)
    total = count_total_asserts(test_dir)
    summary = summarize(findings)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if args.json:
        print(json.dumps({"findings": findings, "summary": summary, "total_asserts": total}, ensure_ascii=False, indent=2))
    else:
        print(f"弱断言扫描: {summary['total']} 条（error {summary['by_severity'].get('error', 0)} / warn {summary['by_severity'].get('warn', 0)}）")
        print(f"总断言数: {total}，弱断言占比 {weak_ratio(findings, total):.1%}")
        for f in findings:
            print(f"  {f['file']}:{f['line']} [{f['severity']}] {f['pattern']}")

    errors = [f for f in findings if f["severity"] == "error"]
    ratio = weak_ratio(findings, total)
    return 1 if (errors or ratio > DEFAULT_MAX_RATIO) else 0


if __name__ == "__main__":
    raise SystemExit(run())
