import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "quality_gate.py"
SPEC = importlib.util.spec_from_file_location("quality_gate", MODULE_PATH)
QUALITY_GATE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(QUALITY_GATE)

# Ensure config cache is clean before each test run
QUALITY_GATE.reset_config_cache()


# ==========================================================================
# 1. EXISTING TESTS (14 items – all preserved)
# ==========================================================================

class QualitySystemTests(unittest.TestCase):
    def test_grade_boundaries(self):
        expected = {
            1: "E",
            4: "E",
            5: "D",
            8: "D",
            9: "C",
            12: "C",
            13: "B",
            16: "B",
            17: "A",
            19: "A",
            20: "S",
            22: "S",
        }
        for score, grade in expected.items():
            with self.subTest(score=score):
                self.assertEqual(QUALITY_GATE.grade_for(score)[0], grade)

    def test_scores_total_twenty_two(self):
        scores, total = QUALITY_GATE.validate_scores(
            {
                "functional": 6,
                "security": 5,
                "scope": 4,
                "probability": 3,
                "recovery": 2,
                "hidden": 2,
            }
        )
        self.assertEqual(total, 22)
        self.assertEqual(sum(scores.values()), 22)

    def test_zero_score_is_promoted_to_one(self):
        scores, total = QUALITY_GATE.validate_scores({})
        self.assertEqual(total, 1)
        self.assertEqual(scores["functional"], 1)

    def test_secret_redaction(self):
        value = "token=super-secret-value Authorization: Bearer abcdef"
        redacted = QUALITY_GATE.redact_secrets(value)
        self.assertNotIn("super-secret-value", redacted)
        self.assertNotIn("abcdef", redacted)

    def test_secret_scan_skips_only_documented_local_key_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / ".quality-gates.json"
            config_path.write_text('{"exclude_directories": []}', encoding="utf-8")
            local_key = "sk-" + "a" * 20
            source_key = "sk-" + "b" * 20
            (root / "api-key.txt").write_text(local_key, encoding="utf-8")
            (root / "api_key.txt").write_text(local_key, encoding="utf-8")
            (root / "source.py").write_text(source_key, encoding="utf-8")

            with mock.patch.multiple(
                QUALITY_GATE,
                ROOT=root,
                CONFIG_PATH=config_path,
            ):
                QUALITY_GATE.reset_config_cache()
                scan = QUALITY_GATE.secret_scan()
                QUALITY_GATE.reset_config_cache()

        self.assertFalse(scan["passed"])
        self.assertIn("source.py", scan["details"])
        self.assertNotIn("api-key.txt", scan["details"])
        self.assertNotIn("api_key.txt", scan["details"])
    def test_python_syntax_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.py"
            path.write_text("def broken(:\n", encoding="utf-8")
            result = QUALITY_GATE.check_python_syntax([path])
        self.assertFalse(result["passed"])

    def test_notebook_magic_preserves_indentation(self):
        source = "if True:\n    %time value = 1\n"
        ast_source = QUALITY_GATE.notebook_code(source)
        compile(ast_source, "notebook-cell", "exec")
        self.assertIn("    pass", ast_source)

    def test_business_code_requires_each_test_level(self):
        with (
            mock.patch.object(QUALITY_GATE, "project_code_files", return_value=[Path("model.py")]),
            mock.patch.object(QUALITY_GATE, "test_files", return_value=[]),
            mock.patch.object(QUALITY_GATE, "has_custom_commands", return_value=False),
        ):
            for level in ("small", "medium", "heavy"):
                with self.subTest(level=level):
                    check = QUALITY_GATE.project_test_coverage(level, [])
                    self.assertFalse(check["passed"])

    def test_selected_file_cannot_narrow_project_checks(self):
        files = [ROOT / "tools" / "quality_gate.py", ROOT / "tests" / "test_quality_system.py"]
        with mock.patch.object(QUALITY_GATE, "iter_source_files", return_value=files):
            selected = QUALITY_GATE.selected_files(str(files[0]))
        self.assertEqual(selected, files)

    def test_empty_business_test_file_does_not_satisfy_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            empty_test = Path(directory) / "test_model.py"
            empty_test.write_text("", encoding="utf-8")
            with (
                mock.patch.object(QUALITY_GATE, "project_code_files", return_value=[Path("model.py")]),
                mock.patch.object(QUALITY_GATE, "test_files", return_value=[empty_test]),
                mock.patch.object(QUALITY_GATE, "has_custom_commands", return_value=False),
            ):
                check = QUALITY_GATE.project_test_coverage("small", [])
        self.assertFalse(check["passed"])

    def test_runnable_business_test_satisfies_coverage(self):
        source = (
            "import unittest\n\n"
            "class ModelTests(unittest.TestCase):\n"
            "    def test_model(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            test_path = Path(directory) / "test_model.py"
            test_path.write_text(source, encoding="utf-8")
            with (
                mock.patch.object(QUALITY_GATE, "project_code_files", return_value=[Path("model.py")]),
                mock.patch.object(QUALITY_GATE, "test_files", return_value=[test_path]),
                mock.patch.object(QUALITY_GATE, "has_custom_commands", return_value=False),
            ):
                check = QUALITY_GATE.project_test_coverage("small", [])
        self.assertTrue(check["passed"])

    def test_control_file_is_protected(self):
        self.assertTrue(QUALITY_GATE.is_source_file(Path("AGENTS.md")))

    def test_agent_rules_require_independent_review(self):
        rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## 3. Agent 独立复核", rules)
        self.assertIn("不能把门禁退出码、测试数量或另一个 Agent 的结论当作正确性证明", rules)
        self.assertIn("可手算的小样本", rules)

    def test_resolved_bug_reopens_with_original_id(self):
        with tempfile.TemporaryDirectory() as directory:
            bug_root = Path(directory) / "bug合集"
            replacements = {
                "BUG_DIR": bug_root,
                "CATALOG_PATH": bug_root / "catalog.json",
                "BUG_INDEX_PATH": bug_root / "INDEX.md",
                "OPEN_BUG_DIR": bug_root / "未解决",
                "RESOLVED_BUG_DIR": bug_root / "已解决",
            }
            with mock.patch.multiple(QUALITY_GATE, **replacements):
                bug_id, repeated = QUALITY_GATE.add_bug(
                    category="code",
                    stage="test",
                    title="same failure",
                    details="same details",
                    scores={"functional": 1},
                )
                self.assertFalse(repeated)
                with mock.patch("builtins.print"):
                    QUALITY_GATE.resolve_bug(bug_id, "fixed", "test passed")
                reopened_id, repeated = QUALITY_GATE.add_bug(
                    category="code",
                    stage="test",
                    title="same failure",
                    details="same details",
                    scores={"functional": 1},
                )
                catalog = QUALITY_GATE.read_json(replacements["CATALOG_PATH"])

        self.assertTrue(repeated)
        self.assertEqual(reopened_id, bug_id)
        self.assertEqual(catalog["bugs"][0]["status"], "open")
        self.assertEqual(len(catalog["bugs"][0]["occurrences"]), 2)

    def test_tag_push_uses_tracked_heavy_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            (evidence_root / "v1.2.3.json").write_text(
                '{"source_hash":"source","bug_hash_after_logging":"bugs"}',
                encoding="utf-8",
            )
            hook_input = "refs/tags/v1.2.3 abc refs/tags/v1.2.3 000\n"
            with (
                mock.patch.object(QUALITY_GATE, "VERSION_REPORT_DIR", evidence_root),
                mock.patch.object(QUALITY_GATE, "source_hash", return_value="source"),
                mock.patch.object(QUALITY_GATE, "bug_hash", return_value="bugs"),
                mock.patch.object(QUALITY_GATE, "git_output", return_value="commit"),
                mock.patch.object(QUALITY_GATE.sys, "stdin", io.StringIO(hook_input)),
                mock.patch("builtins.print"),
            ):
                exit_code = QUALITY_GATE.command_verify_push(None)

        self.assertEqual(exit_code, 0)


# ==========================================================================
# 2. HOOK TARGET PATH  (D2 regression)
# ==========================================================================

class HookTargetPathTests(unittest.TestCase):
    def test_file_path_key(self):
        self.assertEqual(
            QUALITY_GATE.hook_target_path({"file_path": "src/a.py"}),
            "src/a.py",
        )

    def test_notebook_path_key(self):
        self.assertEqual(
            QUALITY_GATE.hook_target_path({"notebook_path": "nb/b.ipynb"}),
            "nb/b.ipynb",
        )

    def test_generic_path_key(self):
        self.assertEqual(
            QUALITY_GATE.hook_target_path({"path": "c.txt"}),
            "c.txt",
        )

    def test_priority_file_path_over_notebook(self):
        self.assertEqual(
            QUALITY_GATE.hook_target_path(
                {"file_path": "src/a.py", "notebook_path": "nb/b.ipynb"}
            ),
            "src/a.py",
        )

    def test_empty_input_returns_none(self):
        self.assertIsNone(QUALITY_GATE.hook_target_path({}))
        self.assertIsNone(QUALITY_GATE.hook_target_path({"file_path": ""}))
        self.assertIsNone(QUALITY_GATE.hook_target_path({"file_path": "  "}))


# ==========================================================================
# 3. PROTECTED STATE PATHS  (D1 regression)
# ==========================================================================

class ProtectedStatePathsTests(unittest.TestCase):
    def test_state_dir_is_protected(self):
        state_dir = QUALITY_GATE.STATE_DIR
        self.assertTrue(QUALITY_GATE._is_under_protection(state_dir / "small.json"))
        self.assertTrue(QUALITY_GATE._is_under_protection(state_dir / "reports" / "x.json"))

    def test_catalog_and_index_are_protected(self):
        self.assertTrue(
            QUALITY_GATE._is_under_protection(QUALITY_GATE.CATALOG_PATH)
        )
        self.assertTrue(
            QUALITY_GATE._is_under_protection(QUALITY_GATE.BUG_INDEX_PATH)
        )

    def test_open_bug_dir_is_protected(self):
        self.assertTrue(
            QUALITY_GATE._is_under_protection(
                QUALITY_GATE.OPEN_BUG_DIR / "BUG-0001.md"
            )
        )

    def test_resolved_bug_dir_is_protected(self):
        self.assertTrue(
            QUALITY_GATE._is_under_protection(
                QUALITY_GATE.RESOLVED_BUG_DIR / "BUG-0002.md"
            )
        )

    def test_version_report_dir_is_protected(self):
        self.assertTrue(
            QUALITY_GATE._is_under_protection(
                QUALITY_GATE.VERSION_REPORT_DIR / "v1.0.0.json"
            )
        )

    def test_readme_is_not_protected(self):
        """README.md and TEMPLATE.md are human-maintained docs, not protected."""
        self.assertFalse(
            QUALITY_GATE._is_under_protection(
                QUALITY_GATE.BUG_DIR / "README.md"
            )
        )
        self.assertFalse(
            QUALITY_GATE._is_under_protection(
                QUALITY_GATE.BUG_DIR / "TEMPLATE.md"
            )
        )

    def test_regular_source_is_not_protected(self):
        self.assertFalse(
            QUALITY_GATE._is_under_protection(ROOT / "tools" / "quality_gate.py")
        )


# ==========================================================================
# 4. BUG HASH SPLIT  (D5 regression)
# ==========================================================================

class BugHashBindingTests(unittest.TestCase):
    def setUp(self):
        QUALITY_GATE.reset_config_cache()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.bug_root = Path(self.tmpdir.name) / "bug合集"
        self.cat_path = self.bug_root / "catalog.json"
        self.replacements = {
            "BUG_DIR": self.bug_root,
            "CATALOG_PATH": self.cat_path,
            "BUG_INDEX_PATH": self.bug_root / "INDEX.md",
            "OPEN_BUG_DIR": self.bug_root / "未解决",
            "RESOLVED_BUG_DIR": self.bug_root / "已解决",
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def _fresh_catalog(self):
        catalog = {
            "schema_version": 1,
            "next_id": 1,
            "bugs": [],
        }
        QUALITY_GATE.write_json(self.cat_path, catalog)

    def test_old_record_not_agent_tool_call_is_binding(self):
        """Backward compat: records without receipt_binding key where stage != 'agent-tool-call' are binding."""
        record = {"stage": "small"}
        self.assertTrue(QUALITY_GATE._is_receipt_binding(record))

        record2 = {"stage": "medium"}
        self.assertTrue(QUALITY_GATE._is_receipt_binding(record2))

    def test_old_record_agent_tool_call_is_not_binding(self):
        record = {"stage": "agent-tool-call"}
        self.assertFalse(QUALITY_GATE._is_receipt_binding(record))

    def test_explicit_receipt_binding_overrides_stage(self):
        self.assertTrue(
            QUALITY_GATE._is_receipt_binding(
                {"stage": "agent-tool-call", "receipt_binding": True}
            )
        )
        self.assertFalse(
            QUALITY_GATE._is_receipt_binding(
                {"stage": "small", "receipt_binding": False}
            )
        )

    def test_non_binding_record_does_not_change_bug_hash(self):
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            self._fresh_catalog()
            hash_before = QUALITY_GATE.bug_hash()
            QUALITY_GATE.add_bug(
                category="agent",
                stage="agent-tool-call",
                title="tool failure",
                details="unique tool error details",
                scores={"functional": 1},
            )
            hash_after = QUALITY_GATE.bug_hash()
        self.assertEqual(hash_before, hash_after)

    def test_binding_record_changes_bug_hash(self):
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            self._fresh_catalog()
            hash_before = QUALITY_GATE.bug_hash()
            QUALITY_GATE.add_bug(
                category="code",
                stage="small",
                title="test failure",
                details="unique test error details",
                scores={"functional": 3},
            )
            hash_after = QUALITY_GATE.bug_hash()
        self.assertNotEqual(hash_before, hash_after)


# ==========================================================================
# 5. NOTEBOOK PATH IN HOOK-PRE  (D2 regression)
# ==========================================================================

class NotebookPathHookPreTests(unittest.TestCase):
    def test_hook_pre_denies_notebook_without_active_unit(self):
        payload = {
            "tool_input": {"notebook_path": str(ROOT / "notebooks/test.ipynb")},
        }
        stdin_mock = io.StringIO(json.dumps(payload))
        with (
            mock.patch.object(QUALITY_GATE, "bug_hash", return_value="hash"),
            mock.patch.object(QUALITY_GATE, "is_source_file", return_value=True),
            mock.patch.object(QUALITY_GATE, "read_state", return_value=None),
            mock.patch.object(QUALITY_GATE, "hook_json") as mock_hook,
            mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
        ):
            QUALITY_GATE.command_hook_pre(None)
        mock_hook.assert_called_once()
        # It should be PreToolUse with deny (no active unit for source file)
        args, kwargs = mock_hook.call_args
        self.assertEqual(kwargs.get("event") or args[0], "PreToolUse")
        self.assertIn("deny", kwargs)

    def test_hook_pre_allows_non_source_notebook(self):
        payload = {
            "tool_input": {"notebook_path": "/tmp/notes.md"},
        }
        stdin_mock = io.StringIO(json.dumps(payload))
        with (
            mock.patch.object(QUALITY_GATE, "is_source_file", return_value=False),
            mock.patch.object(QUALITY_GATE, "read_state", return_value=None),
            mock.patch.object(QUALITY_GATE, "hook_json") as mock_hook,
            mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
        ):
            with mock.patch("builtins.print") as mock_print:
                QUALITY_GATE.command_hook_pre(None)
            # Should have printed "{}" and returned 0, not called hook_json
            mock_hook.assert_not_called()

    def test_hook_pre_denies_protected_path_even_with_active_unit(self):
        payload = {
            "tool_input": {"file_path": str(QUALITY_GATE.STATE_DIR / "small.json")},
        }
        stdin_mock = io.StringIO(json.dumps(payload))
        with (
            mock.patch.object(QUALITY_GATE, "read_state", return_value={"id": "U-1"}),
            mock.patch.object(QUALITY_GATE, "hook_json") as mock_hook,
            mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
        ):
            QUALITY_GATE.command_hook_pre(None)
        mock_hook.assert_called_once()
        args, kwargs = mock_hook.call_args
        self.assertEqual(kwargs.get("event") or args[0], "PreToolUse")
        reason = kwargs.get("deny", "")
        self.assertIn("禁止直接编辑", reason)

    def test_hook_pre_denies_resolved_bug_write(self):
        payload = {
            "tool_input": {
                "file_path": str(QUALITY_GATE.RESOLVED_BUG_DIR / "BUG-0001.md")
            },
        }
        stdin_mock = io.StringIO(json.dumps(payload))
        with (
            mock.patch.object(QUALITY_GATE, "read_state", return_value={"id": "U-2"}),
            mock.patch.object(QUALITY_GATE, "hook_json") as mock_hook,
            mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
        ):
            QUALITY_GATE.command_hook_pre(None)
        mock_hook.assert_called_once()
        args, kwargs = mock_hook.call_args
        self.assertIn("禁止直接编辑", kwargs.get("deny", ""))


# ==========================================================================
# 6. HOOK-FAILURE D3 REGRESSION
# ==========================================================================

class HookFailureRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.bug_root = Path(self.tmpdir.name) / "bug合集"
        self.replacements = {
            "BUG_DIR": self.bug_root,
            "CATALOG_PATH": self.bug_root / "catalog.json",
            "BUG_INDEX_PATH": self.bug_root / "INDEX.md",
            "OPEN_BUG_DIR": self.bug_root / "未解决",
            "RESOLVED_BUG_DIR": self.bug_root / "已解决",
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_unrecognized_fields_yield_unique_payload_in_details(self):
        """Two different unknown payloads should produce TWO different bugs."""
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            catalog = {"schema_version": 1, "next_id": 1, "bugs": []}
            QUALITY_GATE.write_json(self.replacements["CATALOG_PATH"], catalog)

            for i, body in enumerate(["payload A unique", "payload B distinct"]):
                payload = {"unknown_field_x": body, "is_interrupt": False}
                stdin_mock = io.StringIO(json.dumps(payload))
                with (
                    mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
                    mock.patch("builtins.print"),
                ):
                    QUALITY_GATE.command_hook_failure(None)

            cat = QUALITY_GATE.read_json(self.replacements["CATALOG_PATH"])
            # Should have created TWO separate bugs, not collapsed into one
            self.assertGreaterEqual(len(cat["bugs"]), 2)

    def test_fallback_details_include_payload_keys(self):
        """Even completely unrecognized payloads write diagnostic info."""
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            catalog = {"schema_version": 1, "next_id": 1, "bugs": []}
            QUALITY_GATE.write_json(self.replacements["CATALOG_PATH"], catalog)

            payload = {"is_interrupt": False}
            stdin_mock = io.StringIO(json.dumps(payload))
            with (
                mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
                mock.patch("builtins.print"),
            ):
                QUALITY_GATE.command_hook_failure(None)

            cat = QUALITY_GATE.read_json(self.replacements["CATALOG_PATH"])
            self.assertEqual(len(cat["bugs"]), 1)
            # Fallback should serialize the payload as compact JSON
            details = cat["bugs"][0]["details"]
            self.assertIn("is_interrupt", details, "Details should include payload fields")

    def test_new_record_is_receipt_binding_false(self):
        """agent-tool-call auto-logged records must have receipt_binding=False."""
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            catalog = {"schema_version": 1, "next_id": 1, "bugs": []}
            QUALITY_GATE.write_json(self.replacements["CATALOG_PATH"], catalog)

            payload = {
                "tool_name": "Bash",
                "error": "command failed",
                "is_interrupt": False,
            }
            stdin_mock = io.StringIO(json.dumps(payload))
            with (
                mock.patch.object(QUALITY_GATE.sys, "stdin", stdin_mock),
                mock.patch("builtins.print"),
            ):
                QUALITY_GATE.command_hook_failure(None)

            cat = QUALITY_GATE.read_json(self.replacements["CATALOG_PATH"])
            self.assertEqual(len(cat["bugs"]), 1)
            self.assertFalse(cat["bugs"][0].get("receipt_binding", True))


# ==========================================================================
# 7. RESOLVE_BUG CLEARS PROVISIONAL  (round-1 issue 4 regression)
# ==========================================================================

class ResolveBugProvisionalTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.bug_root = Path(self.tmpdir.name) / "bug合集"
        self.replacements = {
            "BUG_DIR": self.bug_root,
            "CATALOG_PATH": self.bug_root / "catalog.json",
            "BUG_INDEX_PATH": self.bug_root / "INDEX.md",
            "OPEN_BUG_DIR": self.bug_root / "未解决",
            "RESOLVED_BUG_DIR": self.bug_root / "已解决",
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_resolve_sets_provisional_false(self):
        with mock.patch.multiple(QUALITY_GATE, **self.replacements):
            bug_id, _ = QUALITY_GATE.add_bug(
                category="code",
                stage="test",
                title="test bug",
                details="details",
                scores={"functional": 1},
            )
            # Provisional should be True initially
            cat = QUALITY_GATE.read_json(self.replacements["CATALOG_PATH"])
            self.assertTrue(cat["bugs"][0]["provisional"])

            with mock.patch("builtins.print"):
                QUALITY_GATE.resolve_bug(bug_id, "fixed", "verified by hand")

            cat = QUALITY_GATE.read_json(self.replacements["CATALOG_PATH"])
            self.assertFalse(cat["bugs"][0]["provisional"])
            self.assertIn("resolved_at", cat["bugs"][0])


# ==========================================================================
# 8. BASH HOOK DENY RULES  (round-1 issues 1&2 regression)
# ==========================================================================

class BashHookDenyTests(unittest.TestCase):
    def _check(self, command: str, active: dict | None = None) -> tuple[bool, str]:
        segments = QUALITY_GATE._segment_and_tokens(command)
        for tokens in segments:
            deny, reason = QUALITY_GATE._check_bash_segment(tokens, active)
            if deny:
                return True, reason
        return False, ""

    # --- Allowed commands ---

    def test_readonly_git_log_allowed(self):
        deny, _ = self._check("git log --oneline")
        self.assertFalse(deny)

    def test_readonly_git_status_allowed(self):
        deny, _ = self._check("git status --porcelain")
        self.assertFalse(deny)

    def test_readonly_git_diff_allowed(self):
        deny, _ = self._check("git diff HEAD~1")
        self.assertFalse(deny)

    def test_echo_allowed(self):
        deny, _ = self._check("echo hello world")
        self.assertFalse(deny)

    def test_cat_allowed(self):
        deny, _ = self._check("cat README.md")
        self.assertFalse(deny)

    def test_cd_allowed(self):
        deny, _ = self._check("cd /tmp")
        self.assertFalse(deny)

    def test_ls_allowed(self):
        deny, _ = self._check("ls -la")
        self.assertFalse(deny)

    # --- git push -n is dry-run, NOT --no-verify ---

    def test_git_push_dash_n_is_dry_run_allowed(self):
        deny, _ = self._check("git push -n")
        self.assertFalse(deny)

    def test_git_push_dash_n_long_is_dry_run_allowed(self):
        deny, _ = self._check("git push --dry-run")
        self.assertFalse(deny)

    # --- Quality gate self-invocation always allowed ---

    def test_run_quality_allowed(self):
        deny, _ = self._check(
            'powershell -ExecutionPolicy Bypass -File tools/run_quality.ps1 small'
        )
        self.assertFalse(deny)

    def test_quality_gate_py_allowed(self):
        deny, _ = self._check("python tools/quality_gate.py status")
        self.assertFalse(deny)

    # --- Deny: git commit --no-verify ---

    def test_git_commit_no_verify_denied(self):
        deny, reason = self._check("git commit --no-verify -m 'skip gate'")
        self.assertTrue(deny)
        self.assertIn("no-verify", reason.lower())

    def test_git_commit_dash_n_denied(self):
        deny, reason = self._check("git commit -n -m skip")
        self.assertTrue(deny)
        self.assertIn("no-verify", reason.lower())

    def test_git_push_no_verify_denied(self):
        deny, reason = self._check("git push --no-verify origin main")
        self.assertTrue(deny)

    # --- Deny: git config core.hooksPath ---

    def test_git_config_hooksPath_denied(self):
        deny, reason = self._check("git config core.hooksPath .git/hooks")
        self.assertTrue(deny)
        self.assertIn("hooksPath", reason)

    def test_git_config_hooks_path_with_underscore_denied(self):
        deny, reason = self._check("git config core.hooks_path .githooks")
        self.assertTrue(deny)

    # --- Deny: redirect to protected paths ---

    def test_redirect_to_state_dir_denied(self):
        deny, reason = self._check(
            f"echo x > {QUALITY_GATE.STATE_DIR / 'small.json'}"
        )
        self.assertTrue(deny)

    # --- Source write denied without active unit ---

    def test_source_write_without_active_unit_denied(self):
        deny, reason = self._check(
            f"echo 'bad code' > {ROOT / 'tools' / 'quality_gate.py'}"
        )
        self.assertTrue(deny)
        self.assertIn("没有活动单元", reason)

    # --- Source write allowed WITH active unit ---

    def test_source_write_with_active_unit_allowed(self):
        active = {
            "id": "U-TEST",
            "name": "test",
            "reviewed_bug_hash": QUALITY_GATE.bug_hash(),
        }
        deny, _ = self._check(
            f"echo 'fix' > {ROOT / 'tools' / 'quality_gate.py'}",
            active=active,
        )
        self.assertFalse(deny)

    # --- git destructive without active unit ---

    def test_git_checkout_without_active_unit_denied(self):
        deny, reason = self._check("git checkout main")
        self.assertTrue(deny)
        self.assertIn("没有活动单元", reason)

    def test_git_reset_without_active_unit_denied(self):
        deny, reason = self._check("git reset --hard HEAD~1")
        self.assertTrue(deny)

    def test_git_reset_with_active_unit_allowed(self):
        active = {
            "id": "U-TEST",
            "name": "test",
            "reviewed_bug_hash": QUALITY_GATE.bug_hash(),
        }
        deny, _ = self._check("git reset --soft HEAD~1", active=active)
        self.assertFalse(deny)


# ==========================================================================
# 9. CONTROL FILES HARD-CODED FLOOR
# ==========================================================================

class ControlFileFloorTests(unittest.TestCase):
    def test_hardcoded_includes_crucial_files(self):
        paths = QUALITY_GATE._hardcoded_control_file_paths()
        # Compute name ignoring leading dot for matching purposes
        rel_paths = set()
        for p in paths:
            name = p.name.casefold()
            rel_paths.add(name)
            # Also add the relative path variant so e.g. .quality-gates.json matches
            try:
                rel_paths.add(p.relative_to(ROOT).as_posix().casefold())
            except ValueError:
                pass
        for name in ("agents.md", "claude.md", "codex.md", "gemini.md",
                     "workflow.md", ".quality-gates.json", "pre-commit",
                     "commit-msg", "pre-push"):
            self.assertIn(name, rel_paths, f"Missing {name} from hardcoded control files")

    def test_config_cannot_shrink_floor(self):
        """Even with empty additional_control_files, the floor entries remain."""
        with mock.patch.object(
            QUALITY_GATE, "load_config",
            return_value={"additional_control_files": []},
        ):
            candidates = QUALITY_GATE.control_file_candidates()
            # floor entries like AGENTS.md must still be present
            agents = [p for p in candidates if p.name == "AGENTS.md"]
            self.assertEqual(len(agents), 1)

    def test_config_can_add_extra_files(self):
        with mock.patch.object(
            QUALITY_GATE, "load_config",
            return_value={"additional_control_files": ["extra/rules.md"]},
        ):
            candidates = QUALITY_GATE.control_file_candidates()
            extras = [p for p in candidates if "extra/rules.md" in str(p).replace("\\", "/")]
            self.assertEqual(len(extras), 1)


# ==========================================================================
# 10. CONFIG CACHE (D6 regression)
# ==========================================================================

class ConfigCacheTests(unittest.TestCase):
    def tearDown(self):
        QUALITY_GATE.reset_config_cache()

    def test_load_config_is_cached(self):
        QUALITY_GATE.reset_config_cache()
        c1 = QUALITY_GATE.load_config()
        c2 = QUALITY_GATE.load_config()
        self.assertIs(c1, c2)

    def test_reset_config_cache_clears(self):
        QUALITY_GATE.reset_config_cache()
        c1 = QUALITY_GATE.load_config()
        QUALITY_GATE.reset_config_cache()
        c2 = QUALITY_GATE.load_config()
        # After reset, should be a fresh parse – content identical, but new object
        self.assertEqual(c1, c2)


# ==========================================================================
# 11. REPORT PATHS INCLUDE UUID (anti-collision)
# ==========================================================================

class ReportPathsTests(unittest.TestCase):
    def test_two_calls_produce_different_paths(self):
        ts = "2026-08-01T00:00:00+08:00"
        j1, _ = QUALITY_GATE.report_paths("small", ts)
        j2, _ = QUALITY_GATE.report_paths("small", ts)
        self.assertNotEqual(j1, j2)


# ==========================================================================
# 12. _quality_system_test_names IS CONFIGURABLE
# ==========================================================================

class QualitySystemTestNamesTests(unittest.TestCase):
    def tearDown(self):
        QUALITY_GATE.reset_config_cache()

    def test_default_excludes_test_quality_system(self):
        QUALITY_GATE.reset_config_cache()
        names = QUALITY_GATE._quality_system_test_names()
        self.assertIn("test_quality_system.py", names)

    def test_config_can_override(self):
        with mock.patch.object(
            QUALITY_GATE, "load_config",
            return_value={
                "test_policy": {
                    "quality_system_test_files": ["custom_quality.py", "harness_test.py"],
                },
            },
        ):
            names = QUALITY_GATE._quality_system_test_names()
        self.assertIn("custom_quality.py", names)
        self.assertIn("harness_test.py", names)
        self.assertNotIn("test_quality_system.py", names)


if __name__ == "__main__":
    unittest.main()

