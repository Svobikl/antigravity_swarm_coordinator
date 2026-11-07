import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MEMLOG_SCRIPT = REPO_ROOT / ".antigravity" / "scripts" / "bmad_memlog.py"
SPINE_SCRIPT = REPO_ROOT / ".antigravity" / "scripts" / "bmad_lint_spine.py"
REVIEWER_SCRIPT = REPO_ROOT / ".antigravity" / "scripts" / "invoke_opus_reviewer.py"
STOP_HOOK_SCRIPT = REPO_ROOT / "plugins" / "antigravity-swarm" / "scripts" / "asw-stop-check.mjs"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBMADMethodIntegration(unittest.TestCase):
    """Comprehensive unit, negative/edge-case, and real-surface CLI tests for BMAD-METHOD V7 integration (M1..M6)."""

    def test_m1_frozen_contract_tamper_detection_happy_and_negative(self):
        """M1: Unmodified <frozen-after-approval> passes; tampered <frozen-after-approval> triggers BMAD_FROZEN_CONTRACT_VIOLATION."""
        rev = _load_module("invoke_opus_reviewer", REVIEWER_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            plan_path = tmp_dir / "plan.md"
            plan_path.write_text(
                "---\nstatus: in-progress\nbaseline_revision: 2aaa75e\n---\n"
                "<!-- <frozen-after-approval> -->\n### Intent\nKeep original behavior.\n<!-- </frozen-after-approval> -->\n"
                "- [x] Task 1\n",
                encoding="utf-8",
            )
            ev_path = tmp_dir / "ev.md"
            ev_path.write_text("RED phase failed, GREEN phase passed, negative test edge case verified.\n", encoding="utf-8")

            clean_diff = (
                "diff --git a/src/service.py b/src/service.py\n"
                "+++ b/src/service.py\n"
                "+def process_item(x: int) -> int:\n"
                "+    return x + 1\n"
                "diff --git a/tests/test_service.py b/tests/test_service.py\n"
                "+++ b/tests/test_service.py\n"
                "+def test_process_item_negative_edge():\n"
                "+    assert process_item(1) == 2\n"
            )
            verdict_ok, findings_ok, report_ok = rev.audit_diff(
                plan_path, None, ev_path, diff_content_override=clean_diff, workdir=tmp_dir
            )
            self.assertEqual(verdict_ok, "ASW APPROVED", f"Unexpected findings: {findings_ok}")
            self.assertIn("BMAD 5-Lens Audit", report_ok)

            tampered_diff = (
                "diff --git a/plan.md b/plan.md\n"
                "+++ b/plan.md\n"
                " <!-- <frozen-after-approval> -->\n"
                "-Keep original behavior.\n"
                "+Rewrote matrix expectation to make broken test pass.\n"
                " <!-- </frozen-after-approval> -->\n"
                + clean_diff
            )
            verdict_bad, findings_bad, _ = rev.audit_diff(
                plan_path, None, ev_path, diff_content_override=tampered_diff, workdir=tmp_dir
            )
            self.assertEqual(verdict_bad, "ASW REJECTED")
            msgs = " ".join(f["message"] for f in findings_bad)
            self.assertIn("BMAD_FROZEN_CONTRACT_VIOLATION", msgs)

    def test_m2_and_m4_lint_spine_and_plan_contract_happy_and_negative(self):
        """M2 & M4: bmad_lint_spine.py validates Architecture Spines (AD-n Binds/Prevents/Rule, Stack pins) and Plan Contracts."""
        linter = _load_module("bmad_lint_spine", SPINE_SCRIPT)

        valid_spine = (
            "---\ntitle: Architecture Spine\n---\n"
            "## Stack\n"
            "| Name | Version |\n"
            "| --- | --- |\n"
            "| Python | 3.12 |\n"
            "| FastAPI | 0.115.0 |\n\n"
            "### AD-1 Event Outbox Persistence\n"
            "- **Binds:** OrderWorker, PaymentGateway\n"
            "- **Prevents:** Orphaned external orders on DB rollback\n"
            "- **Rule:** Always persist PENDING row before external API call.\n"
        )
        res_ok = linter.lint_spine(valid_spine, name="valid_spine.md")
        self.assertTrue(res_ok["ok"], f"Expected valid spine to pass, got: {res_ok}")
        self.assertEqual(res_ok["total_findings"], 0)

        invalid_spine = (
            "---\ntitle: Broken Spine\n---\n"
            "## Stack\n"
            "| Name | Version |\n"
            "| --- | --- |\n"
            "| Python | |\n\n"
            "### AD-2 Second Decision First\n"
            "- **Binds:** API\n"
            "- **Prevents:** Drift\n"
            "- **Rule:** Enforce schema.\n\n"
            "### AD-1 Non-Monotonic and Missing Prevents\n"
            "- **Binds:** Worker\n"
            "- **Rule:** TBD placeholder here.\n"
        )
        res_bad = linter.lint_spine(invalid_spine, name="broken_spine.md")
        self.assertFalse(res_bad["ok"])
        cats = {f["category"] for f in res_bad["findings"]}
        self.assertIn("version_pin", cats)
        self.assertIn("ad_id", cats)
        self.assertIn("ad_fields", cats)
        self.assertIn("placeholder", cats)

        # Plan contract negative test (missing frozen block and empty matrix)
        broken_plan = (
            "---\nstatus: ready-for-dev\n---\n"
            "# Plan Without Frozen Block\n"
            "## I/O & Edge-Case Matrix\n"
            "| Scenario | Input | Output |\n"
            "| --- | --- | --- |\n"
        )
        plan_bad = linter.lint_plan_contract(broken_plan, name="broken_plan.md")
        self.assertFalse(plan_bad["ok"])
        plan_cats = {f["category"] for f in plan_bad["findings"]}
        self.assertIn("frozen_contract", plan_cats)
        self.assertIn("io_matrix", plan_cats)
        self.assertIn("code_map", plan_cats)
        self.assertIn("baseline_revision", plan_cats)

    def test_m3_deletion_and_missing_adoption_gap_and_triage_gate(self):
        """M3: Deleting a function while a surviving caller still invokes it triggers BMAD_DELETION_OR_ADOPTION_GAP; unresolved triage blocks Stop hook."""
        rev = _load_module("invoke_opus_reviewer", REVIEWER_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            plan_path = tmp_dir / "plan.md"
            plan_path.write_text(
                "---\nstatus: in-progress\nbaseline_revision: 2aaa75e\n---\n"
                "<!-- <frozen-after-approval> -->\n### Intent\nRefactor tariff engine.\n<!-- </frozen-after-approval> -->\n"
                "- [x] Task 1\n"
                "## Review Triage Log\n"
                "- [patch] Fix sibling caller in worker.py\n",
                encoding="utf-8",
            )
            ev_path = tmp_dir / "ev.md"
            ev_path.write_text("RED phase failed, GREEN phase passed, negative test edge case verified.\n", encoding="utf-8")

            orphan_diff = (
                "diff --git a/src/tariff.py b/src/tariff.py\n"
                "+++ b/src/tariff.py\n"
                "-def calculate_legacy_rate(val: float) -> float:\n"
                "-    return val * 1.1\n"
                "+def calculate_v2_rate(val: float) -> float:\n"
                "+    return calculate_legacy_rate(val) * 1.2\n"
                "diff --git a/tests/test_tariff.py b/tests/test_tariff.py\n"
                "+++ b/tests/test_tariff.py\n"
                "+def test_negative_edge_rate():\n"
                "+    assert calculate_v2_rate(10.0) == 13.2\n"
            )
            verdict, findings, _ = rev.audit_diff(
                plan_path, None, ev_path, diff_content_override=orphan_diff, workdir=tmp_dir
            )
            self.assertEqual(verdict, "ASW REJECTED")
            msgs = " ".join(f["message"] for f in findings)
            self.assertIn("BMAD_DELETION_OR_ADOPTION_GAP", msgs)
            self.assertIn("BMAD_UNRESOLVED_TRIAGE_ITEM", msgs)

            # Also verify asw-stop-check.mjs blocks Stop when all tasks are [x] but [patch] is unresolved
            plans_dir = tmp_dir / ".asw" / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "active.md").write_text(plan_path.read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run(
                ["node", str(STOP_HOOK_SCRIPT)],
                input=json.dumps({"cwd": str(tmp_dir), "fullyIdle": True}),
                capture_output=True,
                text=True,
                check=True,
            )
            hook_out = json.loads(proc.stdout)
            self.assertEqual(hook_out["decision"], "continue")
            self.assertIn("BMAD Review Triage Gate", hook_out["reason"])

    def test_m5_bmad_memlog_atomic_init_append_set_and_tally(self):
        """M5: bmad_memlog.py supports init, rejects duplicate init with exit 2, appends atomically, and tallies claims."""
        with tempfile.TemporaryDirectory() as tmp:
            r_init = subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "init", "--workspace", tmp, "--field", "topic=BMAD Recon", "--field", "goal=Verify Firewall"],
                capture_output=True,
                text=True,
                check=True,
            )
            init_data = json.loads(r_init.stdout)
            self.assertTrue(init_data["ok"])
            self.assertEqual(init_data["entries"], 0)

            # Negative case: calling init again on existing .memlog.md must fail with exit code 2
            r_dup = subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "init", "--workspace", tmp],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_dup.returncode, 2)

            # Append verified claim, unverified claim, and overturned claim
            subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "append", "--workspace", tmp, "--type", "claim", "--by", "locator", "--text", "Found entrypoint in install.py"],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "append", "--workspace", tmp, "--type", "unverified", "--text", "External benchmark pending"],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "append", "--workspace", tmp, "--type", "overturned", "--text", "Old config format deprecated"],
                capture_output=True,
                text=True,
                check=True,
            )
            r_tally = subprocess.run(
                [sys.executable, str(MEMLOG_SCRIPT), "tally", "--workspace", tmp],
                capture_output=True,
                text=True,
                check=True,
            )
            tally_data = json.loads(r_tally.stdout)
            self.assertEqual(tally_data["entries"], 3)
            self.assertEqual(tally_data["claims"], {"verified": 1, "unverified": 1, "overturned": 1})

    def test_m6_bmad_skill_references_and_section_28_present(self):
        """M6: All BMAD reference files, Section 28 rules, and merged skill sections exist without breaking catalog curation."""
        rules_txt = (REPO_ROOT / ".antigravity" / "rules" / "GLOBAL_DEVELOPMENT_RULES.md").read_text(encoding="utf-8")
        self.assertIn("## 28. BMAD-METHOD V7", rules_txt)

        cf_skills = REPO_ROOT / "core_framework" / "skills"
        self.assertTrue((cf_skills / "asw-plan" / "references" / "bmad-plan-template.md").is_file())
        self.assertTrue((cf_skills / "asw-loop" / "references" / "bmad-steps.md").is_file())
        self.assertTrue((cf_skills / "asw-review" / "references" / "bmad-review-lenses.md").is_file())

        for skill_name in (
            "swarm-coordinator",
            "asw-plan",
            "asw-loop",
            "asw-start-work",
            "asw-review",
            "opposition-reviewer",
            "software-architect",
            "program-state-controller",
            "spec-product-analyst",
            "deep-research",
            "asw-rules",
            "completion-auditor",
            "documentation-handoff-agent",
        ):
            skill_txt = (cf_skills / skill_name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("## BMAD-METHOD V7", skill_txt, f"Missing BMAD-METHOD V7 section in {skill_name}")

        readme_txt = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("How to Use the Swarm Coordinator Effectively", readme_txt)
        for cmd_name in ("/asw-plan", "/asw-start-work", "/asw-test-gui", "/asw-debug", "/asw-review", "/asw-goal", "/asw-cleanup"):
            self.assertIn(cmd_name, readme_txt)


if __name__ == "__main__":
    unittest.main()
