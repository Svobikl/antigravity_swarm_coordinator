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

    def test_m8_v41_semantic_auditor_and_validate_claims_happy_and_negative(self):
        """M8: SemanticCompletionAuditor defaults to RESEARCH, drops pandas, and validates ClaimDefinition (duration_units/event_count/events_per_unit) alongside validate_program_state.validate_claims()."""
        auditor_src = (REPO_ROOT / ".antigravity" / "semantic" / "auditor.py").read_text(encoding="utf-8")
        self.assertNotIn("import pandas", auditor_src)

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        vps = _load_module("validate_program_state", REPO_ROOT / ".antigravity" / "scripts" / "validate_program_state.py")
        from core_framework.semantic.auditor import SemanticCompletionAuditor
        from core_framework.semantic.claims import ClaimRegistryManager
        from core_framework.semantic.invariants import InvariantManager
        from core_framework.semantic.schema import ClaimDefinition, DeploymentStatus, ProgramInvariants, ScientificVerdict
        from core_framework.semantic.snapshot import SourceSnapshotManager

        with tempfile.TemporaryDirectory() as tmp:
            prog_dir = Path(tmp) / "prog_ok"
            prog_dir.mkdir(parents=True)
            snap_mgr = SourceSnapshotManager(prog_dir)
            snap_mgr.create_snapshot("# Source Plan\n")
            inv_mgr = InvariantManager(prog_dir)
            inv_mgr.invariants = ProgramInvariants(program_id="PROG-M8")
            inv_mgr.save_invariants()

            claim_mgr = ClaimRegistryManager(prog_dir)
            ok_claim = ClaimDefinition(
                claim_id="CLAIM-001",
                claim_text="100 events over 2.0 units",
                metric_name="throughput",
                metric_version="1.0",
                value=50.0,
                units="events/unit",
                execution_contract_id="EXEC-1",
                evaluation_period_start="2026-01-01",
                evaluation_period_end="2026-01-03",
                duration_units=2.0,
                event_count=100,
                events_per_unit=50.0,
                validation_status=ScientificVerdict.OUTER_VALIDATED,
            )
            reg_ok, reg_msg = claim_mgr.register_claim(ok_claim)
            self.assertTrue(reg_ok, reg_msg)
            claim_mgr.save("PROG-M8")

            auditor = SemanticCompletionAuditor(prog_dir, root_dir=Path(tmp))
            res_ok = auditor.run_semantic_audit()
            self.assertTrue(res_ok.is_fully_clean, f"Unexpected blocking errors: {res_ok.blocking_errors}")
            self.assertEqual(res_ok.four_axis_header.deployment_status, DeploymentStatus.RESEARCH)
            self.assertEqual(vps.validate_claims(prog_dir), [])

            # Negative case: inject arithmetic mismatch directly into CLAIM_REGISTRY.json
            bad_claim = ClaimDefinition(
                claim_id="CLAIM-002",
                claim_text="Broken arithmetic claim",
                metric_name="throughput",
                metric_version="1.0",
                value=5.0,
                units="events/unit",
                execution_contract_id="EXEC-1",
                evaluation_period_start="2026-01-01",
                evaluation_period_end="2026-01-03",
                duration_units=2.0,
                event_count=100,
                events_per_unit=5.0,
                validation_status=ScientificVerdict.EXPLORATORY,
            )
            claim_mgr.claims["CLAIM-002"] = bad_claim
            claim_mgr.save("PROG-M8")

            res_bad = SemanticCompletionAuditor(prog_dir, root_dir=Path(tmp)).run_semantic_audit()
            self.assertFalse(res_bad.is_fully_clean)
            self.assertTrue(any("Arithmetic contradiction in claim CLAIM-002" in e for e in res_bad.blocking_errors))

            vps_errs = vps.validate_claims(prog_dir)
            self.assertEqual(len(vps_errs), 1)
            self.assertIn("Arithmetic error in claim 'CLAIM-002'", vps_errs[0])

    def test_vq_m5_two_stage_retrace_egdp_and_mirror_parity(self):
        """VQ-M5: Reviewer agents enforce 2-Stage RETRACE + EGDP + STING mutation gate across 3 byte-identical mirrors."""
        mirror_dirs = [
            REPO_ROOT / "plugins" / "antigravity-swarm" / "agents",
            REPO_ROOT / ".antigravity" / "agents",
            REPO_ROOT / "core_framework" / "agents",
        ]
        expected_tools = {
            "asw-reviewer.md": "tools: [read_file, write_file, edit_file, run_command, manage_task, search_web]",
            "asw-opposition-reviewer.md": "tools: [read_file, run_command, manage_task, search_web]",
        }
        required_tokens = [
            "RETRACE",
            "EGDP",
            "STING",
            "Stage 1",
            "Stage 2",
            "--mode prepare-blind-review",
            "--mode diff-review",
            "--verify-mutations",
            "0.75",
            "I/O & Edge-Case Matrix",
            "<frozen-after-approval>",
            "## Implementation Notes",
            "subagent: true",
            "mainAgent: false",
            "<= 250 tokens",
            "<thought>",
            "unconstrained",
        ]

        for agent_file, tools_line in expected_tools.items():
            ref_bytes = (mirror_dirs[0] / agent_file).read_bytes()
            for md_dir in mirror_dirs[1:]:
                self.assertEqual(
                    (md_dir / agent_file).read_bytes(),
                    ref_bytes,
                    f"{md_dir / agent_file} is not byte-identical to {mirror_dirs[0] / agent_file}",
                )

            txt = ref_bytes.decode("utf-8")
            self.assertIn(tools_line, txt, f"{agent_file} changed expected tools frontmatter")
            for tok in required_tokens:
                self.assertIn(tok, txt, f"{agent_file} missing required RETRACE/EGDP/STING token: {tok}")

            # Ensure Stage 1 blind reconstruction precedes Stage 2 matrix/mutation reconciliation
            s1_idx = txt.index("Stage 1")
            s2_idx = txt.index("Stage 2")
            blind_idx = txt.index("--mode prepare-blind-review")
            diff_idx = txt.index("--verify-mutations")
            self.assertLess(s1_idx, s2_idx, f"{agent_file} must order Stage 1 before Stage 2")
            self.assertLess(blind_idx, diff_idx, f"{agent_file} must run prepare-blind-review before --verify-mutations")

        # Preserve all 5 BMAD lenses in asw-reviewer.md and all 4 Attack Vectors in asw-opposition-reviewer.md
        rev_txt = (mirror_dirs[0] / "asw-reviewer.md").read_text(encoding="utf-8")
        for lens in ("blind-hunter", "edge-case-hunter", "verification-gap", "intent-alignment", "opus-cross-family"):
            self.assertIn(lens, rev_txt, f"asw-reviewer.md missing BMAD lens: {lens}")

        opp_txt = (mirror_dirs[0] / "asw-opposition-reviewer.md").read_text(encoding="utf-8")
        for vec in (
            "1. Scope, Plan Integrity",
            "2. Research, ML Falsification",
            "3. Edge Cases, Boundary Breakdown",
            "4. Downstream, Blast-Radius",
        ):
            self.assertIn(vec, opp_txt, f"asw-opposition-reviewer.md missing Attack Vector: {vec}")


if __name__ == "__main__":
    unittest.main()
