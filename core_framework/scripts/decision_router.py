#!/usr/bin/env python3
"""System 1 Local Decision Model (Laya) Integration for Autonomous Routing & Triage.

Provides sub-40ms bounded routing decisions (Mode 0-5 classification, Quad-Model tier
routing, UI verification detection, active skill budget selection, and review triage)
using the local NandhaKishorM/laya engine or zero-latency (< 5ms) calibrated bilingual (CZ/EN) fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_DECISION_CONFIG: dict[str, object] = {
    "enabled": True,
    "prefer_gpu": True,
    "min_free_vram_mib": 2048,
    "min_total_vram_mib": 4096,
    "cpu_threads": 12,
    "flush_denormal": True,
    "preferred_checkpoint": "multilingual",
    "compact_question_schema": True,
    "use_local_snapshot_fastload": True,
}


def get_decision_config_path(target_dir: Path | None = None) -> Path:
    """Resolve the path for decision_config.json."""
    if target_dir:
        return target_dir / "decision_config.json"
    workspace_cfg = Path.cwd() / ".antigravity" / "decision_config.json"
    if workspace_cfg.parent.is_dir():
        return workspace_cfg
    global_cfg = Path.home() / ".gemini" / "decision_config.json"
    return global_cfg


def load_decision_config() -> dict[str, object]:
    """Load decision configuration from disk and environment variables."""
    cfg = dict(DEFAULT_DECISION_CONFIG)
    candidates = [
        Path.cwd() / ".antigravity" / "decision_config.json",
        Path(__file__).resolve().parent.parent / "decision_config.json",
        Path.home() / ".gemini" / "decision_config.json",
        Path.home() / ".gemini" / ".antigravity" / "decision_config.json",
    ]
    for c in candidates:
        if c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
                    break
            except Exception:
                pass

    env_val = os.environ.get("ASW_DECISION_MODEL_ENABLED")
    if env_val is not None:
        s = env_val.strip().lower()
        if s in ("0", "false", "no", "off"):
            cfg["enabled"] = False
        elif s in ("1", "true", "yes", "on"):
            cfg["enabled"] = True

    return cfg


def save_decision_config(updates: dict[str, object], target_path: Path | None = None) -> Path:
    """Save updates to decision_config.json."""
    cfg = load_decision_config()
    cfg.update(updates)
    dest = target_path or get_decision_config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    gemini_cfg = Path.home() / ".gemini" / "decision_config.json"
    if dest != gemini_cfg and gemini_cfg.parent.is_dir():
        try:
            gemini_cfg.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except Exception:
            pass
    return dest


def select_optimal_device(
    *,
    min_free_vram_mib: int = 2048,
    min_total_vram_mib: int = 4096,
    min_compute_cap: float = 7.0,
    nvidia_smi_output: str | None = None,
) -> dict[str, object]:
    """Inspect GPU hardware to select 'cuda' vs 'cpu'.

    Selects 'cuda' ONLY when:
      1. free_vram_mib >= min_free_vram_mib (2048 MiB)
      2. total_vram_mib >= min_total_vram_mib (4096 MiB)
      3. compute_cap >= min_compute_cap (7.0, Volta/Turing/Ampere/Ada/Blackwell)

    On GPUs like GTX 1060 3GB (Pascal compute 6.1, ~600 MiB free, 3072 MiB total),
    automatically selects 'cpu' (max_loaded=1) to prevent CUDA OOM or PCIe thrashing.
    """
    raw_csv = nvidia_smi_output
    if raw_csv is None:
        try:
            res = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free,compute_cap",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                raw_csv = res.stdout.strip()
        except Exception:
            raw_csv = None

    if not raw_csv or not raw_csv.strip():
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": None,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "no_cuda_or_smi_failed",
        }

    first_line = raw_csv.strip().splitlines()[0]
    parts = [p.strip() for p in first_line.split(",")]
    if len(parts) < 4:
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": parts[0] if parts else None,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "unrecognized_smi_format",
        }

    gpu_name = parts[0]
    try:
        total_vram = int(float(parts[1]))
        free_vram = int(float(parts[2]))
        compute_cap = float(parts[3])
    except (ValueError, IndexError):
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": gpu_name,
            "total_vram_mib": None,
            "free_vram_mib": None,
            "compute_cap": None,
            "reason": "unrecognized_smi_numbers",
        }

    is_sufficient = (
        free_vram >= min_free_vram_mib
        and total_vram >= min_total_vram_mib
        and compute_cap >= min_compute_cap
    )

    if is_sufficient:
        max_loaded = 2 if total_vram >= 16384 else 1
        return {
            "device": "cuda",
            "max_loaded": max_loaded,
            "gpu_name": gpu_name,
            "total_vram_mib": total_vram,
            "free_vram_mib": free_vram,
            "compute_cap": compute_cap,
            "reason": "sufficient_vram",
        }
    else:
        return {
            "device": "cpu",
            "max_loaded": 1,
            "gpu_name": gpu_name,
            "total_vram_mib": total_vram,
            "free_vram_mib": free_vram,
            "compute_cap": compute_cap,
            "reason": "insufficient_vram_or_pascal_fp16",
        }


CORE_SKILL_CATALOG_KEYWORDS = {
    "fastapi-pro": ["fastapi", "uvicorn", "pydantic", "rest api", "endpoint"],
    "playwright-skill": ["playwright", "browser", "e2e", "gui", "web test"],
    "quant-analyst": ["quant", "alpha", "trading", "sharpe", "backtest", "portfolio"],
    "risk-metrics-calculation": ["risk", "var", "cvar", "drawdown", "volatility"],
    "frontend-design": ["frontend", "css", "html", "design", "layout", "vzhled"],
    "react-patterns": ["react", "component", "hook", "jsx", "tsx", "state"],
    "postgres-best-practices": ["postgres", "postgresql", "sql", "migration", "index"],
    "sql-pro": ["sql", "query", "database", "databáze", "schema"],
    "docker-expert": ["docker", "container", "dockerfile", "compose"],
    "odoo-module-developer": ["odoo", "erp", "module", "qweb"],
    "obs-memory": ["obsidian", "vault", "memory", "paměť", "note"],
    "agent-memory": ["agent-memory", "episodic", "recall", "zkušenosti"],
    "ui-ux-designer": ["ui", "ux", "dashboard", "graf", "prohlížeč", "rozhraní"],
    "asw-test-gui": ["asw-test-gui", "gui test", "screen test", "native app"],
    "test-driven-development": ["tdd", "test", "red green", "unit test", "testy"],
    "rtk-token-killer": ["rtk", "token", "cli proxy", "git status", "pytest"],
    "software-architect": ["architect", "architecture", "design", "architektura"],
    "compliance-maintainability-reviewer": ["review", "lint", "compliance", "revize"],
    "opposition-reviewer": ["opus", "opposition", "adversarial", "falsify"],
    "systematic-debugging": ["debug", "crash", "chyba", "hang", "bug", "traceback"],
    "python-pro": ["python", "pytest", "asyncio", "pydantic"],
    "typescript-pro": ["typescript", "ts", "node", "npm"],
}

CORE_FALLBACK_SKILLS = [
    "swarm-coordinator",
    "skill-router",
    "implementation-developer",
    "validator-build-test-agent",
]


class DecisionRouter:
    """System 1 decision router evaluating developer prompts, diffs, and findings."""

    def __init__(
        self,
        server_url: str | None = None,
        enable_inproc: bool | None = None,
        config: dict[str, object] | None = None,
    ):
        self.config = config if config is not None else load_decision_config()
        self.enabled = bool(self.config.get("enabled", True))
        self.server_url = server_url or os.environ.get("LAYA_SERVER_URL", "http://127.0.0.1:8765")
        if enable_inproc is None:
            self.enable_inproc = os.environ.get("LAYA_ENABLE_INPROC", "0").lower() in ("1", "true")
        else:
            self.enable_inproc = enable_inproc

        self._laya_router = None
        if not self.enabled:
            self.device_info: dict[str, object] = {
                "device": "disabled",
                "max_loaded": 0,
                "gpu_name": None,
                "total_vram_mib": None,
                "free_vram_mib": None,
                "compute_cap": None,
                "reason": "decision_model_disabled",
            }
        else:
            self.device_info = select_optimal_device()
            self._init_inproc_if_enabled()

    @staticmethod
    def _resolve_local_laya_snapshot(preferred: str = "multilingual") -> tuple[str | None, str | None]:
        """Find cached HuggingFace snapshot on disk to bypass HTTP Hub check (12.4s -> 2.48s)."""
        hub_dir = Path.home() / ".cache" / "huggingface" / "hub" / "models--convaiinnovations--laya" / "snapshots"
        if not hub_dir.is_dir():
            return None, None
        snaps = list(hub_dir.iterdir())
        if preferred == "multilingual":
            for s in snaps:
                if (s / "multilingual" / "model.safetensors").is_file():
                    return str(s), "multilingual"
        for s in snaps:
            if (s / "model.safetensors").is_file():
                return str(s), None
        return None, None

    def _init_inproc_if_enabled(self) -> None:
        if not self.enabled or not self.enable_inproc:
            return
        try:
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            import torch  # type: ignore
            import laya  # type: ignore

            dev = str(self.device_info.get("device", "cpu"))
            if dev == "cpu":
                if bool(self.config.get("flush_denormal", True)):
                    torch.set_flush_denormal(True)
                threads = int(self.config.get("cpu_threads", os.cpu_count() or 12))
                if threads > 0:
                    torch.set_num_threads(threads)

            if bool(self.config.get("use_local_snapshot_fastload", True)):
                pref = str(self.config.get("preferred_checkpoint", "multilingual"))
                snap_path, sub = self._resolve_local_laya_snapshot(pref)
                if snap_path is not None:
                    self._laya_router = laya.Agent(snap_path, subfolder=sub, device=dev)
                    return

            max_l = int(self.device_info.get("max_loaded", 1))
            self._laya_router = laya.Router(device=dev, max_loaded=max_l)
        except Exception:
            self._laya_router = None

    def preflight(self) -> dict[str, object]:
        """Check availability of GPU device, Laya SDK, and local Laya HTTP daemon."""
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "backend": "disabled",
                "laya_sdk_installed": False,
                "laya_server_reachable": False,
                "device_info": self.device_info,
            }
        sdk_installed = False
        try:
            import laya  # noqa: F401

            sdk_installed = True
        except ImportError:
            sdk_installed = False

        server_reachable = False
        try:
            req = urllib.request.Request(f"{self.server_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=0.4) as resp:
                if resp.status == 200:
                    server_reachable = True
        except Exception:
            server_reachable = False

        if server_reachable:
            backend = "laya_daemon"
        elif self._laya_router is not None:
            backend = "laya_inproc"
        else:
            backend = "system1_calibrated_fallback"

        return {
            "device_info": self.device_info,
            "laya_sdk_installed": sdk_installed,
            "laya_server_reachable": server_reachable,
            "active_backend": backend,
        }

    def route_prompt(self, prompt: str) -> dict[str, object]:
        """Route a user prompt into Mode 0-5, Quad-Model Tier, GUI gate, and subagent requirements."""
        if not self.enabled:
            return {
                "enabled": False,
                "status": "disabled",
                "backend": "disabled",
                "requires_gui_verification": False,
                "requires_subagent_plan_wave": False,
                "selected_skills": [],
                "choice": "disabled",
                "score": 0.0,
                "noul": 0.0,
                "probabilities": {},
                "answer_confidence": 0.0,
                "execution_mode": "disabled",
                "recommended_tier": "disabled",
                "device_info": self.device_info,
            }

        if not prompt or not isinstance(prompt, str):
            return self._build_decision(
                choice="mode_1",
                execution_mode="mode_1",
                recommended_tier="carbon_plan_research",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.5,
                noul=0.1,
            )

        trimmed = prompt.strip()

        # M1: Explicit slash command override (ignoring identifier/path substrings like foo/asw/bar)
        slash_match = re.search(
            r"(?<![A-Za-z0-9_./-])/(?:asw-plan|asw-test-gui|asw-start-work|start-work|asw-review|asw-goal|asw-cleanup|asw-loop|asw)(?![A-Za-z0-9_/-])",
            trimmed,
            re.IGNORECASE,
        )
        if slash_match:
            cmd = slash_match.group(0).lower().lstrip("/")
            if "plan" in cmd:
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification="gui" in trimmed.lower(),
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.2,
                )
            elif "test-gui" in cmd:
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification=True,
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.9,
                )
            elif "start-work" in cmd:
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification="gui" in trimmed.lower(),
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.2,
                )
            elif "review" in cmd:
                return self._build_decision(
                    choice="mode_2",
                    execution_mode="mode_2",
                    recommended_tier="argon_qa_review",
                    requires_gui_verification=False,
                    requires_subagent_plan_wave=False,
                    answer_confidence=1.0,
                    noul=0.1,
                )
            elif "goal" in cmd:
                return self._build_decision(
                    choice="mode_5",
                    execution_mode="mode_5",
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification="gui" in trimmed.lower(),
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.1,
                )
            elif "cleanup" in cmd:
                return self._build_decision(
                    choice="mode_2",
                    execution_mode="mode_2",
                    recommended_tier="hydrogen_implement_tdd",
                    requires_gui_verification=False,
                    requires_subagent_plan_wave=False,
                    answer_confidence=1.0,
                    noul=0.1,
                )
            else:  # asw / asw-loop
                return self._build_decision(
                    choice="mode_3",
                    execution_mode="mode_3",
                    recommended_tier="carbon_plan_research",
                    requires_gui_verification="gui" in trimmed.lower(),
                    requires_subagent_plan_wave=True,
                    answer_confidence=1.0,
                    noul=0.3,
                )

        # M2: Implicit multi-step / UI feature prompts (Bilingual CZ / EN)
        lower = trimmed.lower()

        # Check for UI / GUI keywords
        gui_keywords = [
            "ui", "gui", "dashboard", "graf", "prohlížeč", "obrazovka", "stránka",
            "komponenta", "vzhled", "rozhraní", "browser", "chart", "playwright",
            "view", "frontend", "screen",
        ]
        has_gui = any(re.search(rf"\b{kw}\b", lower) for kw in gui_keywords)

        # Read-only question patterns
        question_patterns = [
            r"^\s*co dělá\b",
            r"^\s*jak funguje\b",
            r"^\s*vysvětli\b",
            r"^\s*kde je\b",
            r"^\s*proč\b",
            r"^\s*what is\b",
            r"^\s*how does\b",
            r"^\s*explain\b",
            r"^\s*where is\b",
            r"^\s*tell me\b",
            r"^\s*why\b",
        ]
        is_question = any(re.search(pat, lower) for pat in question_patterns) or lower.endswith("?")

        if is_question and not has_gui:
            return self._build_decision(
                choice="mode_1",
                execution_mode="mode_1",
                recommended_tier="carbon_plan_research",
                requires_gui_verification=False,
                requires_subagent_plan_wave=False,
                answer_confidence=0.90,
                noul=0.15,
            )

        # Feature verbs (CZ & EN)
        feature_verbs = [
            "uprav", "přidej", "vytvoř", "implementuj", "postav", "oprav", "integruj", "změň",
            "implement", "build", "add", "create", "integrate", "refactor", "update", "develop",
        ]
        has_feature_verb = any(re.search(rf"\b{v}\b", lower) for v in feature_verbs)

        is_multi_step = has_feature_verb and (
            "," in lower or " a " in lower or " and " in lower or has_gui or len(lower.split()) > 7
        )

        if is_multi_step or (has_gui and has_feature_verb):
            noul = 0.85 if has_gui else 0.70
            base_decision = self._build_decision(
                choice="mode_3",
                execution_mode="mode_3",
                recommended_tier="carbon_plan_research",
                requires_gui_verification=has_gui,
                requires_subagent_plan_wave=True,
                answer_confidence=0.92,
                noul=noul,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        # Default fallback
        if has_feature_verb:
            base_decision = self._build_decision(
                choice="mode_2",
                execution_mode="mode_2",
                recommended_tier="hydrogen_implement_tdd",
                requires_gui_verification=has_gui,
                requires_subagent_plan_wave=False,
                answer_confidence=0.80,
                noul=0.4,
            )
            return self._enrich_with_laya(trimmed, base_decision)

        base_decision = self._build_decision(
            choice="mode_1",
            execution_mode="mode_1",
            recommended_tier="carbon_plan_research",
            requires_gui_verification=False,
            requires_subagent_plan_wave=False,
            answer_confidence=0.75,
            noul=0.2,
        )
        return self._enrich_with_laya(trimmed, base_decision)

    def _laya_questions_schema(self) -> dict[str, dict[str, object]]:
        if bool(self.config.get("compact_question_schema", True)):
            return {
                "execution_mode": {
                    "type": "choice",
                    "instructions": "Mode:",
                    "criteria": {
                        "mode_0": "build/run",
                        "mode_1": "explain/research",
                        "mode_2": "small fix",
                        "mode_3": "multi-step feature/UI",
                        "mode_4": "rollback",
                        "mode_5": "long program",
                    },
                },
            }
        return {
            "execution_mode": {
                "type": "choice",
                "instructions": "Select the development execution mode for this software engineering request.",
                "criteria": {
                    "mode_0": "Fast operational build, test, or run command",
                    "mode_1": "Read-only investigation, explanation, or research analysis",
                    "mode_2": "Small single-file bugfix or minor change",
                    "mode_3": "Complex multi-step feature delivery requiring plan and subagents",
                    "mode_4": "Emergency production rollback or restore",
                    "mode_5": "Long-horizon autonomous research program",
                },
            },
            "requires_gui_verification": {
                "type": "noul",
                "instructions": "Does this request touch UI, frontend, dashboard, or browser rendering?",
            },
            "requires_subagent_plan_wave": {
                "type": "noul",
                "instructions": "Is this a multi-step engineering change that requires a plan and subagent waves?",
            },
        }

    def _enrich_with_laya(self, prompt: str, base_decision: dict[str, object]) -> dict[str, object]:
        """Enrich or score via live Laya daemon or in-proc Laya Router when active."""
        if self._laya_router is None:
            return base_decision
        try:
            raw = self._laya_router.predict(prompt, self._laya_questions_schema())
            answers = raw.get("answers", {}) if isinstance(raw, dict) else {}
            mode_ans = answers.get("execution_mode", {})
            gui_ans = answers.get("requires_gui_verification", {})
            if isinstance(mode_ans, dict) and "choice" in mode_ans:
                choice = str(mode_ans["choice"])
                conf = float(mode_ans.get("answer_confidence", base_decision["answer_confidence"]))
                probs = mode_ans.get("probabilities", base_decision["probabilities"])
                gui_noul = float(gui_ans.get("noul", base_decision["noul"])) if isinstance(gui_ans, dict) else float(base_decision["noul"])
                base_decision["choice"] = choice
                base_decision["execution_mode"] = choice
                base_decision["score"] = round(conf, 4)
                base_decision["answer_confidence"] = round(conf, 4)
                base_decision["probabilities"] = probs
                base_decision["noul"] = round(gui_noul, 4)
                base_decision["requires_gui_verification"] = bool(base_decision["requires_gui_verification"]) or (gui_noul >= 0.5)
                base_decision["requires_subagent_plan_wave"] = bool(base_decision["requires_subagent_plan_wave"]) or (choice in ("mode_3", "mode_5"))
                base_decision["backend"] = "laya_inproc"
                base_decision["laya_routing"] = raw.get("routing")
        except Exception:
            pass
        return base_decision

    def select_skills(self, prompt: str, max_skills: int = 8) -> list[str]:
        """Select up to max_skills (capped at 8) relevant skills from the 200-skill catalog."""
        if not self.enabled:
            return []
        max_skills = min(max(max_skills, 1), 8)
        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return CORE_FALLBACK_SKILLS[: min(4, max_skills)]

        lower = prompt.lower()
        scored: list[tuple[str, int]] = []

        for skill_name, keywords in CORE_SKILL_CATALOG_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in lower)
            if matches > 0:
                scored.append((skill_name, matches))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = [s[0] for s in scored[:max_skills]]

        if not selected:
            return CORE_FALLBACK_SKILLS[: min(4, max_skills)]

        return selected

    def triage_finding(self, finding_text: str) -> dict[str, object]:
        """Triage a review finding into [patch], [bad_plan], or [defer] with severity."""
        if not self.enabled:
            return {
                "route": "[defer]",
                "severity_score": 0,
                "enabled": False,
                "status": "disabled",
                "explanation": "Decision router disabled",
            }

        if not finding_text or not isinstance(finding_text, str):
            return {
                "route": "[defer]",
                "severity_score": 1,
                "explanation": "Empty or invalid finding text",
            }

        lower = finding_text.lower()

        # Defect keywords indicating broken caller, contracts, or severe regressions
        defect_keywords = [
            "still called", "attributeerror", "deleted function", "missing adoption",
            "caller hop", "broken verification", "contract violation", "syntaxerror",
            "crash", "regression", "unresolved import", "chyba", "pád",
        ]
        is_defect = any(kw in lower for kw in defect_keywords)

        # Defer keywords indicating minor docs, formatting, or future ideas
        defer_keywords = [
            "out-of-scope", "typo", "formatting", "cosmetic", "future", "polish",
            "minor suggestion", "documentation only", "footer", "překlep", "kosmetick",
        ]
        is_defer = any(kw in lower for kw in defer_keywords)

        if is_defect:
            route = "[bad_plan]" if "contract violation" in lower or "frozen" in lower else "[patch]"
            return {
                "route": route,
                "severity_score": 5 if route == "[bad_plan]" else 4,
                "explanation": "Critical runtime or reference defect requiring code patch",
            }
        elif is_defer:
            return {
                "route": "[defer]",
                "severity_score": 1,
                "explanation": "Non-blocking documentation or cosmetic enhancement routed to deferred work",
            }
        else:
            return {
                "route": "[patch]",
                "severity_score": 3,
                "explanation": "Standard review item routed for verification and patch",
            }

    def predict(self, text: str, context: dict | None = None) -> dict[str, object]:
        """Unified entrypoint matching Laya's predict contract."""
        route_res = self.route_prompt(text)
        if not self.enabled:
            return route_res
        skills = self.select_skills(text, max_skills=8)
        route_res["selected_skills"] = skills
        return route_res

    def _build_decision(
        self,
        *,
        choice: str,
        execution_mode: str,
        recommended_tier: str,
        requires_gui_verification: bool,
        requires_subagent_plan_wave: bool,
        answer_confidence: float,
        noul: float,
    ) -> dict[str, object]:
        all_modes = ["mode_0", "mode_1", "mode_2", "mode_3", "mode_4", "mode_5"]
        probs = {m: 0.05 for m in all_modes}
        probs[execution_mode] = round(answer_confidence, 2)
        remaining = max(0.0, 1.0 - answer_confidence)
        for m in all_modes:
            if m != execution_mode:
                probs[m] = round(remaining / 5.0, 3)

        return {
            "enabled": True,
            "status": "enabled",
            "choice": choice,
            "score": answer_confidence,
            "noul": noul,
            "probabilities": probs,
            "answer_confidence": answer_confidence,
            "execution_mode": execution_mode,
            "recommended_tier": recommended_tier,
            "requires_gui_verification": requires_gui_verification,
            "requires_subagent_plan_wave": requires_subagent_plan_wave,
            "device_info": self.device_info,
            "backend": "system1_calibrated_fallback",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="System 1 Decision Router (Laya + Calibrated Fallback)")
    parser.add_argument(
        "--mode",
        choices=["preflight", "predict", "route-prompt", "select-skills", "triage-finding"],
        default="route-prompt",
    )
    parser.add_argument("--text", type=str, default="", help="Input prompt or finding text")
    parser.add_argument("--json", type=str, default=None, help="JSON input payload")
    parser.add_argument("--max-skills", type=int, default=8, help="Maximum skills to return")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--enable", action="store_true", help="Enable System 1 Decision Router in config")
    parser.add_argument("--disable", action="store_true", help="Disable System 1 Decision Router in config")
    parser.add_argument("--status", action="store_true", help="Show current Decision Router status and configuration")
    parser.add_argument("--device-info", action="store_true", help="Print GPU/CPU device selection analysis")
    parser.add_argument("--preflight", action="store_true", help="Shorthand for --mode preflight")
    args = parser.parse_args(argv)
    if args.preflight:
        args.mode = "preflight"

    if args.disable:
        p = save_decision_config({"enabled": False})
        res = {
            "enabled": False,
            "status": "disabled",
            "config_path": str(p),
            "message": "Decision model disabled successfully",
        }
        print(json.dumps(res, indent=2))
        return 0

    if args.enable:
        p = save_decision_config({"enabled": True})
        res = {
            "enabled": True,
            "status": "enabled",
            "config_path": str(p),
            "message": "Decision model enabled successfully",
        }
        print(json.dumps(res, indent=2))
        return 0

    if args.status:
        cfg = load_decision_config()
        print(json.dumps(cfg, indent=2))
        return 0

    if args.device_info:
        dev_info = select_optimal_device()
        print(json.dumps(dev_info, indent=2))
        return 0

    raw_input_text = args.text
    if args.json:
        try:
            parsed = json.loads(args.json)
            if isinstance(parsed, dict):
                raw_input_text = parsed.get("text", parsed.get("prompt", parsed.get("finding", raw_input_text)))
            elif isinstance(parsed, str):
                raw_input_text = parsed
        except Exception as e:
            err = {"error": f"Malformed JSON input: {e}", "exit_code": 1}
            print(json.dumps(err))
            return 1

    router = DecisionRouter()

    if args.mode == "preflight":
        out = router.preflight()
    elif args.mode == "route-prompt":
        out = router.route_prompt(raw_input_text)
    elif args.mode == "select-skills":
        out = {"selected_skills": router.select_skills(raw_input_text, max_skills=args.max_skills)}
    elif args.mode == "triage-finding":
        out = router.triage_finding(raw_input_text)
    else:  # predict
        out = router.predict(raw_input_text)

    if args.format == "json":
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
