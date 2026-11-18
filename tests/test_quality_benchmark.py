"""Tests for SWE-MiniBench-5 Quality & Token Benchmark (M1..M7)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / ".antigravity" / "scripts"
QB_SCRIPT = SCRIPTS_DIR / "quality_benchmark.py"
TE_SCRIPT = SCRIPTS_DIR / "token_economizer.py"
OPUS_SCRIPT = SCRIPTS_DIR / "invoke_opus_reviewer.py"


def _onexc_chmod(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _load_module(name: str, path: Path):
    if not path.is_file():
        raise ImportError(f"Missing module file: {path}")
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class TestQualityBenchmark(unittest.TestCase):
    def setUp(self):
        self._tmp_dirs: list[Path] = []

    def tearDown(self):
        for d in self._tmp_dirs:
            if d.exists():
                shutil.rmtree(d, onexc=_onexc_chmod)

    def _make_temp_dir(self, prefix: str = "qb_test_") -> Path:
        p = Path(tempfile.mkdtemp(prefix=prefix))
        self._tmp_dirs.append(p)
        return p

    def test_m1_materialize_and_unpatched_baseline(self):
        qb = _load_module("quality_benchmark", QB_SCRIPT)
        src_text = QB_SCRIPT.read_text(encoding="utf-8")
        # Holdouts must be compressed/encoded, never plaintext in script
        self.assertNotIn("def test_holdout_", src_text)

        tmp_out = self._make_temp_dir("qb_m1_")
        info = qb.materialize_benchmark(out_dir=tmp_out, arm="both")
        self.assertEqual(set(info["tasks"].keys()), {"baseline", "swarm"})

        expected_tasks = ("T1", "T2", "T3", "T4", "T5")
        expected_pkgs = {
            "T1": "gateway",
            "T2": "cfgdag",
            "T3": "quantbt",
            "T4": "ratelimit",
            "T5": "outbox",
        }
        total_unpatched_holdout_pass = 0
        total_unpatched_holdout_count = 0

        for arm in ("baseline", "swarm"):
            self.assertEqual(tuple(sorted(info["tasks"][arm].keys())), expected_tasks)
            for tid in expected_tasks:
                t_meta = info["tasks"][arm][tid]
                t_dir = Path(t_meta["path"])
                self.assertTrue(t_dir.is_dir())
                pkg_dir = t_dir / expected_pkgs[tid]
                self.assertTrue((pkg_dir / "__init__.py").is_file())
                py_modules = [
                    p for p in pkg_dir.glob("*.py") if p.name != "__init__.py"
                ]
                self.assertEqual(len(py_modules), 5, f"{tid} must have 5 modules")

                issue_path = t_dir / "ISSUE.md"
                self.assertTrue(issue_path.is_file())
                issue_txt = issue_path.read_text(encoding="utf-8")
                self.assertNotIn("test_holdout_", issue_txt)
                for spoon_file in ("batch.py", "reconcile.py", "snapshot.py", "report.py", "decorator.py", "dlq.py"):
                    self.assertNotIn(spoon_file, issue_txt)
                self.assertGreater(len(issue_txt.strip()), 120)

                pub_test = t_dir / "tests" / "test_public.py"
                self.assertTrue(pub_test.is_file())

                git_status = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(t_dir),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(git_status.returncode, 0)
                self.assertEqual(git_status.stdout.strip(), "")

                # Public tests must pass 100% on starter code
                pub_run = subprocess.run(
                    [sys.executable, "-m", "pytest", str(pub_test), "-q"],
                    cwd=str(t_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(
                    pub_run.returncode,
                    0,
                    f"Starter public tests failed for {arm}/{tid}:\n{pub_run.stdout}\n{pub_run.stderr}",
                )

                if arm == "baseline":
                    res = qb.run_task_holdouts(t_dir, tid)
                    total_unpatched_holdout_pass += res["passed"]
                    total_unpatched_holdout_count += res["total"]

        self.assertEqual(total_unpatched_holdout_count, 50)
        self.assertLess(
            total_unpatched_holdout_pass,
            20,
            f"Unpatched baseline passed too many holdouts: {total_unpatched_holdout_pass}/50",
        )

    def test_m2_verify_oracle_50_of_50(self):
        qb = _load_module("quality_benchmark", QB_SCRIPT)
        tmp_dir = self._make_temp_dir("qb_m2_")
        out_json = tmp_dir / "oracle_verify.json"

        proc = subprocess.run(
            [
                sys.executable,
                str(QB_SCRIPT),
                "--verify-oracle",
                "--json",
                "--output",
                str(out_json),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"--verify-oracle failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        self.assertTrue(out_json.is_file())
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["oracle_holdout_passed"], 50)
        self.assertEqual(payload["oracle_holdout_total"], 50)
        self.assertGreater(payload["oracle_public_total"], 0)
        self.assertEqual(payload["oracle_public_passed"], payload["oracle_public_total"])
        self.assertLess(payload["unpatched_holdout_passed"], 20)

        # Negative validation: helper rejects oracle < 50/50 or unpatched >= 40%
        with self.assertRaises(RuntimeError):
            qb.validate_oracle_summary(
                oracle_holdout_passed=49,
                oracle_holdout_total=50,
                oracle_public_passed=20,
                oracle_public_total=20,
                unpatched_holdout_passed=0,
                unpatched_holdout_total=50,
                unpatched_public_passed=20,
                unpatched_public_total=20,
            )
        with self.assertRaises(RuntimeError):
            qb.validate_oracle_summary(
                oracle_holdout_passed=50,
                oracle_holdout_total=50,
                oracle_public_passed=20,
                oracle_public_total=20,
                unpatched_holdout_passed=20,
                unpatched_holdout_total=50,
                unpatched_public_passed=20,
                unpatched_public_total=20,
            )

    def test_m3_audit_transcript_isolation_leakage_guard(self):
        qb = _load_module("quality_benchmark", QB_SCRIPT)
        tmp_dir = self._make_temp_dir("qb_m3_")
        qb.materialize_benchmark(out_dir=tmp_dir, arm="both")

        base_t1 = tmp_dir / "baseline" / "T1"
        swarm_t1 = tmp_dir / "swarm" / "T1"
        base_t2 = tmp_dir / "baseline" / "T2"
        external_file = tmp_dir / "secret_notes.txt"
        external_file.write_text("do not read", encoding="utf-8")

        # Clean baseline transcript inside allowed task dir
        clean_base_tr = tmp_dir / "clean_baseline.jsonl"
        _write_jsonl(
            clean_base_tr,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"AbsolutePath": str(base_t1 / "ISSUE.md")}},
                        {"name": "view_file", "arguments": {"AbsolutePath": str(base_t1 / "gateway" / "service.py")}},
                        {"name": "edit_file", "arguments": {"TargetFile": str(base_t1 / "gateway" / "service.py")}},
                        {"name": "list_dir", "arguments": {"DirectoryPath": str(base_t1)}},
                        {"name": "grep_search", "arguments": {"SearchPath": str(base_t1), "Query": "baseline"}},
                        {"name": "run_command", "arguments": {"CommandLine": "python -m pytest tests/test_public.py", "Cwd": str(base_t1)}},
                    ],
                }
            ],
        )
        res_clean = qb.audit_transcript_isolation(
            clean_base_tr, allowed_task_dir=base_t1, arm="baseline", repo_root=REPO_ROOT
        )
        self.assertTrue(res_clean["isolated"])

        # Clean swarm transcript using allowlisted .asw/ & Swarm scripts + rtk
        clean_swarm_tr = tmp_dir / "clean_swarm.jsonl"
        _write_jsonl(
            clean_swarm_tr,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"AbsolutePath": str(swarm_t1 / "ISSUE.md")}},
                        {"name": "read_file", "arguments": {"AbsolutePath": str(TE_SCRIPT)}},
                        {"name": "write_file", "arguments": {"TargetFile": str(REPO_ROOT / ".asw" / "evidence" / "tmp.txt")}},
                        {"name": "run_command", "arguments": {"CommandLine": "rtk pytest tests/test_public.py"}},
                    ],
                }
            ],
        )
        res_swarm = qb.audit_transcript_isolation(
            clean_swarm_tr, allowed_task_dir=swarm_t1, arm="swarm", repo_root=REPO_ROOT
        )
        self.assertTrue(res_swarm["isolated"])

        # Shared batch reviewer transcript scoped to arm root allows T1 & T2 in same arm, still blocks opposing arm
        shared_swarm_tr = tmp_dir / "shared_swarm.jsonl"
        _write_jsonl(
            shared_swarm_tr,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"AbsolutePath": str(swarm_t1 / "ISSUE.md")}},
                        {"name": "read_file", "arguments": {"AbsolutePath": str(tmp_dir / "swarm" / "T2" / "ISSUE.md")}},
                    ],
                }
            ],
        )
        res_shared = qb.audit_transcript_isolation(
            shared_swarm_tr,
            allowed_task_dir=tmp_dir / "swarm",
            arm="swarm",
            repo_root=REPO_ROOT,
            allow_arm_root=True,
        )
        self.assertTrue(res_shared["isolated"])
        bad_shared_tr = tmp_dir / "bad_shared_swarm.jsonl"
        _write_jsonl(
            bad_shared_tr,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"AbsolutePath": str(base_t1 / "ISSUE.md")}},
                    ],
                }
            ],
        )
        with self.assertRaises(qb.BenchmarkLeakageError):
            qb.audit_transcript_isolation(
                bad_shared_tr,
                allowed_task_dir=tmp_dir / "swarm",
                arm="swarm",
                repo_root=REPO_ROOT,
                allow_arm_root=True,
            )

        # Leakage vectors across all 8 inspected tools + mixed case
        leakage_cases = [
            ("read_file_qb", {"name": "read_file", "arguments": {"AbsolutePath": str(QB_SCRIPT).upper()}}),
            ("view_file_other_task", {"name": "view_file", "arguments": {"AbsolutePath": str(base_t2 / "ISSUE.md")}}),
            ("edit_file_opposing_arm", {"name": "edit_file", "arguments": {"TargetFile": str(swarm_t1 / "gateway" / "service.py")}}),
            ("write_file_external", {"name": "write_file", "arguments": {"TargetFile": str(external_file)}}),
            ("grep_search_qb", {"name": "grep_search", "arguments": {"SearchPath": str(SCRIPTS_DIR), "Query": "quality_benchmark"}}),
            ("find_by_name_other_task", {"name": "find_by_name", "arguments": {"SearchDirectory": str(base_t2)}}),
            ("list_dir_external", {"name": "list_dir", "arguments": {"DirectoryPath": str(tmp_dir)}}),
            ("run_command_qb", {"name": "run_command", "arguments": {"CommandLine": f"python {QB_SCRIPT} --verify-oracle"}}),
            ("baseline_rtk_forbidden", {"name": "run_command", "arguments": {"CommandLine": "rtk pytest tests/test_public.py"}}),
            ("baseline_asw_forbidden", {"name": "read_file", "arguments": {"AbsolutePath": str(TE_SCRIPT)}}),
            ("view_file_outline_other_task", {"name": "view_file_outline", "arguments": {"AbsolutePath": str(base_t2 / "cfgdag" / "engine.py")}}),
            ("view_code_item_file_key", {"name": "view_code_item", "arguments": {"File": str(base_t2 / "cfgdag" / "engine.py"), "NodePaths": ["ConfigEngine"]}}),
            ("run_command_capital_cwd_external", {"name": "run_command", "arguments": {"CommandLine": "pytest", "Cwd": str(tmp_dir)}}),
            ("run_command_dash_c_backslash_t_drive", {"name": "run_command", "arguments": {"CommandLine": "python -c \"open(r'C:\\temp\\secret.txt')\""}}),
        ]
        for label, tc in leakage_cases:
            bad_tr = tmp_dir / f"bad_{label}.jsonl"
            _write_jsonl(bad_tr, [{"type": "PLANNER_RESPONSE", "tool_calls": [tc]}])
            with self.subTest(case=label):
                with self.assertRaises(qb.BenchmarkLeakageError) as ctx:
                    qb.audit_transcript_isolation(
                        bad_tr, allowed_task_dir=base_t1, arm="baseline", repo_root=REPO_ROOT
                    )
                self.assertIn("BENCHMARK_LEAKAGE_DETECTED", str(ctx.exception))

        # _parse_pytest_verbose must ignore print("foo PASSED") user stdout
        noisy_stdout = (
            "foo PASSED\n"
            "test_eval_t1.py::test_holdout_01 PASSED\n"
            "test_eval_t1.py::test_holdout_02 FAILED\n"
        )
        self.assertEqual(qb._parse_pytest_verbose(noisy_stdout, "", 1), (1, 2))

        # CLI exit code 2 check
        bad_cli_tr = tmp_dir / "bad_cli.jsonl"
        _write_jsonl(
            bad_cli_tr,
            [{"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"AbsolutePath": str(QB_SCRIPT)}}]}],
        )
        cli_proc = subprocess.run(
            [
                sys.executable,
                str(QB_SCRIPT),
                "--audit-isolation",
                str(bad_cli_tr),
                "--task-dir",
                str(swarm_t1),
                "--arm",
                "swarm",
                "--repo-root",
                str(REPO_ROOT),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(cli_proc.returncode, 2)
        self.assertIn("BENCHMARK_LEAKAGE_DETECTED", cli_proc.stdout + cli_proc.stderr)

    def test_m4_four_tier_model_weights_and_pass_at_1_grading(self):
        qb = _load_module("quality_benchmark", QB_SCRIPT)
        te = _load_module("token_economizer", TE_SCRIPT)
        tmp_dir = self._make_temp_dir("qb_m4_")
        qb.materialize_benchmark(out_dir=tmp_dir, arm="both")

        # Apply oracle patches to swarm T1..T5 (so swarm achieves 5/5, 50/50)
        # Leave baseline T1..T5 unpatched (so baseline fails Pass@1)
        for tid in ("T1", "T2", "T3", "T4", "T5"):
            qb.apply_oracle_solution(tmp_dir / "swarm" / tid, tid)

        # Build realistic transcripts for all 4 MODEL_WEIGHTS tiers
        manifest = {
            "run_id": "test-m4",
            "arms": {
                "baseline": {"label": "Stock Orchestrator Carbon (Baseline)", "tasks": {}},
                "swarm": {"label": "Antigravity Swarm Coordinator V4.1", "tasks": {}},
            },
        }
        for tid in ("T1", "T2", "T3", "T4", "T5"):
            b_dir = tmp_dir / "baseline" / tid
            b_tr = tmp_dir / "transcripts" / f"baseline_{tid}_carbon.jsonl"
            _write_jsonl(
                b_tr,
                [
                    {
                        "type": "PLANNER_RESPONSE",
                        "usage": {"input_tokens": 2000, "cache_read_input_tokens": 4000, "output_tokens": 500},
                        "tool_calls": [{"name": "read_file", "arguments": {"AbsolutePath": str(b_dir / "ISSUE.md")}}],
                    }
                ],
            )
            manifest["arms"]["baseline"]["tasks"][tid] = {
                "task_dir": str(b_dir),
                "transcripts": [
                    {
                        "path": str(b_tr),
                        "role": "coordinator",
                        "model": "gemini-4-carbon",
                        "conversation_id": f"conv-base-{tid}",
                    }
                ],
            }

            s_dir = tmp_dir / "swarm" / tid
            s_trs = []
            tier_specs = [
                ("planner", "gemini-4-carbon", {"input_tokens": 400, "cache_read_input_tokens": 1000, "output_tokens": 120}),
                ("implementer", "gemini-4-hydrogen", {"input_tokens": 600, "cache_read_input_tokens": 2000, "output_tokens": 200}),
                ("reviewer", "gemini-4-argon", {"input_tokens": 300, "cache_read_input_tokens": 1000, "output_tokens": 80}),
                ("opus_reviewer", "claude-opus-5-5", {"input_tokens": 200, "cache_read_input_tokens": 800, "cache_creation_input_tokens": 400, "output_tokens": 60}),
            ]
            for role, model, usage in tier_specs:
                tr_p = tmp_dir / "transcripts" / f"swarm_{tid}_{role}.jsonl"
                _write_jsonl(
                    tr_p,
                    [
                        {
                            "type": "PLANNER_RESPONSE",
                            "usage": usage,
                            "tool_calls": [{"name": "read_file", "arguments": {"AbsolutePath": str(s_dir / "ISSUE.md")}}],
                        }
                    ],
                )
                s_trs.append(
                    {
                        "path": str(tr_p),
                        "role": role,
                        "model": model,
                        "conversation_id": f"conv-swarm-{tid}-{role}",
                    }
                )
            manifest["arms"]["swarm"]["tasks"][tid] = {
                "task_dir": str(s_dir),
                "transcripts": s_trs,
            }

        # Add shared batch reviewer transcript for swarm (distributed 1/5 across per_task and summed into arm total)
        shared_rev_tr = tmp_dir / "transcripts" / "swarm_shared_batch_reviewer.jsonl"
        _write_jsonl(
            shared_rev_tr,
            [
                {
                    "type": "PLANNER_RESPONSE",
                    "usage": {"input_tokens": 500, "cache_read_input_tokens": 1000, "output_tokens": 100},
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"AbsolutePath": str(tmp_dir / "swarm" / "T1" / "ISSUE.md")}},
                        {"name": "read_file", "arguments": {"AbsolutePath": str(tmp_dir / "swarm" / "T2" / "ISSUE.md")}},
                    ],
                }
            ],
        )
        manifest["arms"]["swarm"]["shared_transcripts"] = [
            {
                "path": str(shared_rev_tr),
                "role": "swarm-batch-reviewer",
                "model": "gemini-4-argon",
                "conversation_id": "conv-swarm-shared-batch-rev",
            }
        ]

        manifest_path = tmp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        report_path = tmp_dir / "report.json"

        report = qb.evaluate_benchmark(manifest_path, output_json_path=report_path)
        self.assertTrue(report_path.is_file())

        # Check Pass@1 & Holdout assertions
        self.assertEqual(report["arms"]["swarm"]["tasks_passed"], 5)
        self.assertEqual(report["arms"]["swarm"]["holdout_passed"], 50)
        self.assertEqual(report["arms"]["swarm"]["holdout_total"], 50)
        self.assertLess(report["arms"]["baseline"]["holdout_passed"], 20)
        self.assertEqual(report["arms"]["baseline"]["tasks_passed"], 0)
        self.assertEqual(len(report["arms"]["swarm"]["shared_transcripts"]), 1)
        self.assertEqual(
            sum(t["raw_tokens"] for t in report["arms"]["swarm"]["per_task"].values()),
            report["arms"]["swarm"]["raw_tokens"],
        )
        self.assertAlmostEqual(
            sum(t["effective_tokens"] for t in report["arms"]["swarm"]["per_task"].values()),
            report["arms"]["swarm"]["effective_tokens"],
            places=4,
        )

        # Verify exact MODEL_WEIGHTS summation across all 4 tiers for Swarm (including shared argon reviewer)
        expected_opus_eff = te.effective_tokens(
            {"input_tokens": 200 * 5, "cache_read_input_tokens": 800 * 5, "cache_creation_input_tokens": 400 * 5, "output_tokens": 60 * 5},
            model="claude-opus-5-5",
        )
        expected_argon_eff = te.effective_tokens(
            {"input_tokens": 300 * 5 + 500, "cache_read_input_tokens": 1000 * 5 + 1000, "output_tokens": 80 * 5 + 100},
            model="gemini-4-argon",
        )
        swarm_by_model = report["arms"]["swarm"]["tokens_by_model"]
        self.assertEqual(
            set(swarm_by_model.keys()),
            {"gemini-4-carbon", "gemini-4-argon", "gemini-4-hydrogen", "claude-opus-5-5"},
        )
        self.assertAlmostEqual(swarm_by_model["claude-opus-5-5"]["effective_tokens"], expected_opus_eff, places=4)
        self.assertAlmostEqual(swarm_by_model["gemini-4-argon"]["effective_tokens"], expected_argon_eff, places=4)

        # Verify host paths redacted in saved JSON
        saved_text = report_path.read_text(encoding="utf-8")
        self.assertNotIn(str(tmp_dir), saved_text)
        self.assertIn("sha256", saved_text)

        # Missing transcript must abort
        bad_manifest = json.loads(json.dumps(manifest))
        bad_manifest["arms"]["baseline"]["tasks"]["T1"]["transcripts"][0]["path"] = str(tmp_dir / "nonexistent.jsonl")
        bad_manifest_path = tmp_dir / "bad_manifest.json"
        bad_manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            qb.evaluate_benchmark(bad_manifest_path)

    def test_m5_render_svg_xml_and_json_parity(self):
        qb = _load_module("quality_benchmark", QB_SCRIPT)
        tmp_dir = self._make_temp_dir("qb_m5_")

        report_dict = {
            "run_id": "m5-test",
            "arms": {
                "baseline": {
                    "label": "Stock Orchestrator Carbon (Baseline)",
                    "tasks_passed": 2,
                    "tasks_total": 5,
                    "pass_at_1_rate": 0.4,
                    "holdout_passed": 28,
                    "holdout_total": 50,
                    "raw_tokens": 180000,
                    "effective_tokens": 110000.0,
                    "tokens_by_model": {
                        "gemini-4-carbon": {"raw_tokens": 180000, "effective_tokens": 110000.0},
                        "gemini-4-argon": {"raw_tokens": 0, "effective_tokens": 0.0},
                        "gemini-4-hydrogen": {"raw_tokens": 0, "effective_tokens": 0.0},
                        "claude-opus-5-5": {"raw_tokens": 0, "effective_tokens": 0.0},
                    },
                    "per_task": {
                        "T1": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 20000.0, "raw_tokens": 34000},
                        "T2": {"holdout_passed": 5, "holdout_total": 10, "pass_at_1": False, "effective_tokens": 22000.0, "raw_tokens": 36000},
                        "T3": {"holdout_passed": 3, "holdout_total": 10, "pass_at_1": False, "effective_tokens": 24000.0, "raw_tokens": 38000},
                        "T4": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 21000.0, "raw_tokens": 35000},
                        "T5": {"holdout_passed": 0, "holdout_total": 10, "pass_at_1": False, "effective_tokens": 23000.0, "raw_tokens": 37000},
                    },
                },
                "swarm": {
                    "label": "Antigravity Swarm Coordinator V4.1",
                    "tasks_passed": 5,
                    "tasks_total": 5,
                    "pass_at_1_rate": 1.0,
                    "holdout_passed": 50,
                    "holdout_total": 50,
                    "raw_tokens": 95000,
                    "effective_tokens": 52000.0,
                    "tokens_by_model": {
                        "gemini-4-carbon": {"raw_tokens": 20000, "effective_tokens": 12000.0},
                        "gemini-4-argon": {"raw_tokens": 15000, "effective_tokens": 8000.0},
                        "gemini-4-hydrogen": {"raw_tokens": 50000, "effective_tokens": 25000.0},
                        "claude-opus-5-5": {"raw_tokens": 10000, "effective_tokens": 7000.0},
                    },
                    "per_task": {
                        "T1": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 10000.0, "raw_tokens": 18000},
                        "T2": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 11000.0, "raw_tokens": 20000},
                        "T3": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 10500.0, "raw_tokens": 19000},
                        "T4": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 10200.0, "raw_tokens": 18500},
                        "T5": {"holdout_passed": 10, "holdout_total": 10, "pass_at_1": True, "effective_tokens": 10300.0, "raw_tokens": 19500},
                    },
                },
            },
            "comparison": {
                "pass_at_1_delta": 0.6,
                "holdout_passed_delta": 22,
                "raw_tokens_saved": 85000,
                "raw_tokens_savings_pct": 47.22,
                "effective_tokens_saved": 58000.0,
                "effective_tokens_savings_pct": 52.73,
            },
        }
        report_json = tmp_dir / "report.json"
        report_json.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
        svg_out = tmp_dir / "telemetry.svg"

        proc = subprocess.run(
            [
                sys.executable,
                str(QB_SCRIPT),
                "--render-svg",
                str(svg_out),
                "--report",
                str(report_json),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(svg_out.is_file())
        svg_text = svg_out.read_text(encoding="utf-8")
        root = ET.fromstring(svg_text)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("prefers-color-scheme: light", svg_text)
        self.assertIn("@keyframes", svg_text)
        self.assertIn("Stock Orchestrator Carbon (Baseline)", svg_text)
        self.assertIn("Antigravity Swarm Coordinator V4.1", svg_text)
        self.assertIn("2/5", svg_text)
        self.assertIn("5/5", svg_text)
        self.assertIn("28/50", svg_text)
        self.assertIn("50/50", svg_text)
        for tid in ("T1", "T2", "T3", "T4", "T5"):
            self.assertIn(tid, svg_text)

    def test_m6_readme_and_published_report_parity(self):
        readme_path = REPO_ROOT / "README.md"
        evidence_report_path = REPO_ROOT / ".asw" / "evidence" / "quality-benchmark-report.json"
        docs_report_path = REPO_ROOT / "docs" / "quality-benchmark-report.json"
        svg_path = REPO_ROOT / "assets" / "quality-benchmark-telemetry.svg"

        self.assertTrue(
            evidence_report_path.is_file() or docs_report_path.is_file(),
            "Missing quality-benchmark-report.json in .asw/evidence/ and docs/",
        )
        if evidence_report_path.is_file() and docs_report_path.is_file():
            self.assertEqual(
                json.loads(evidence_report_path.read_text(encoding="utf-8")),
                json.loads(docs_report_path.read_text(encoding="utf-8")),
                "docs/quality-benchmark-report.json drifted from .asw/evidence/quality-benchmark-report.json",
            )
        report_path = evidence_report_path if evidence_report_path.is_file() else docs_report_path

        self.assertTrue(svg_path.is_file(), "Missing assets/quality-benchmark-telemetry.svg")
        ET.fromstring(svg_path.read_text(encoding="utf-8"))

        readme_txt = readme_path.read_text(encoding="utf-8")
        self.assertIn("./assets/quality-benchmark-telemetry.svg", readme_txt)
        self.assertIn("<details>", readme_txt)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        b_arm = report["arms"]["baseline"]
        s_arm = report["arms"]["swarm"]
        self.assertIn(f"{b_arm['holdout_passed']}/{b_arm['holdout_total']}", readme_txt)
        self.assertIn(f"{s_arm['holdout_passed']}/{s_arm['holdout_total']}", readme_txt)
        self.assertIn(f"{b_arm['tasks_passed']}/{b_arm['tasks_total']}", readme_txt)
        self.assertIn(f"{s_arm['tasks_passed']}/{s_arm['tasks_total']}", readme_txt)
        for tid in ("T1", "T2", "T3", "T4", "T5"):
            self.assertIn(tid, readme_txt)
        mode2 = (report.get("supplementary_arms") or {}).get("mode2_fast_swarm")
        if mode2:
            self.assertIn(f"{mode2['raw_tokens']:,}", readme_txt)
            self.assertIn(f"{mode2['effective_tokens']:,.1f}", readme_txt)
            self.assertIn(f"{mode2['holdout_passed']}/{mode2['holdout_total']}", readme_txt)

    def test_m7_mirror_install_and_catalog_invariants(self):
        self.assertTrue(QB_SCRIPT.is_file())
        core_mirror = REPO_ROOT / "core_framework" / "scripts" / "quality_benchmark.py"
        if core_mirror.exists():
            self.assertEqual(
                QB_SCRIPT.read_bytes(),
                core_mirror.read_bytes(),
                "core_framework/scripts/quality_benchmark.py drifted from .antigravity/scripts/quality_benchmark.py",
            )

        # Installer deploys quality_benchmark.py to ~/.gemini/scripts/
        tmp_home = self._make_temp_dir("qb_m7_home_")
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "install.py"),
                "--home-dir",
                str(tmp_home),
                "--skip-prompt",
                "--skip-skills",
                "--skip-plugin",
                "--skip-vault",
                "--skip-rtk",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed_qb = tmp_home / ".gemini" / "scripts" / "quality_benchmark.py"
        self.assertTrue(installed_qb.is_file(), "install.py did not deploy quality_benchmark.py")
        self.assertEqual(installed_qb.read_bytes(), QB_SCRIPT.read_bytes())

        # Verify 200/201-skill Golden Catalog in ~/.gemini/config/skills remains intact
        home_skills_dir = Path.home() / ".gemini" / "config" / "skills"
        if home_skills_dir.is_dir():
            skill_count = len(
                [d for d in home_skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file()]
            )
            self.assertIn(skill_count, (200, 201))

        # Public-repo PII/secret scan on new benchmark files
        scan_proc = subprocess.run(
            [
                sys.executable,
                str(OPUS_SCRIPT),
                "--scan-public-repo",
                str(QB_SCRIPT),
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(scan_proc.returncode, 0, scan_proc.stdout + scan_proc.stderr)


if __name__ == "__main__":
    unittest.main()
