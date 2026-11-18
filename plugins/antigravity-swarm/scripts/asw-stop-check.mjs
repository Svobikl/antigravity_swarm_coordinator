#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { safeMode } from "./asw-redact.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MAX_AUTO_CONTINUES = 3;
const ACTIVE_PLAN_WINDOW_MS = 6 * 60 * 60 * 1000; // 6 hours

function foldTranscriptOnStop(payload, repoDir) {
  const envVal = String(process.env.ASW_TOKEN_ECONOMIZER_ENABLED ?? "").trim().toLowerCase();
  if (envVal === "0" || envVal === "false" || envVal === "no" || envVal === "off") return;
  const transcriptPath = payload?.transcriptPath;
  if (typeof transcriptPath !== "string" || !transcriptPath.trim() || !existsSync(transcriptPath)) return;
  const candidates = [
    join(__dirname, "..", "..", "..", ".antigravity", "scripts", "token_economizer.py"),
    repoDir ? join(repoDir, ".antigravity", "scripts", "token_economizer.py") : "",
    join(process.cwd(), ".antigravity", "scripts", "token_economizer.py"),
    join(homedir(), ".gemini", "scripts", "token_economizer.py"),
    join(homedir(), ".gemini", ".antigravity", "scripts", "token_economizer.py"),
  ].filter(Boolean);
  const tePath = candidates.find((c) => existsSync(c));
  if (!tePath) return;
  try {
    spawnSync(
      process.platform === "win32" ? "python" : "python3",
      [tePath, "--fold", transcriptPath, "--repo", repoDir, "--json"],
      { timeout: 1500, encoding: "utf8" }
    );
  } catch {
    // fail-open
  }
}

function resolveWorkspaceCwd(payload) {
  const candidates = [
    payload?.cwd,
    Array.isArray(payload?.workspacePaths) ? payload.workspacePaths[0] : undefined,
    Array.isArray(payload?.workspaceUris) ? payload.workspaceUris[0] : undefined,
  ];
  for (const raw of candidates) {
    if (typeof raw === "string" && raw.trim()) {
      try {
        if (raw.startsWith("file://")) {
          return fileURLToPath(raw);
        }
        return raw.trim();
      } catch {
        // continue
      }
    }
  }
  return process.cwd();
}

function readPayload() {
  try {
    const raw = readFileSync(0, "utf8");
    return raw.trim() ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function findUncheckedActivePlan(cwd) {
  try {
    const plansDir = join(cwd, ".asw", "plans");
    if (!existsSync(plansDir)) return null;

    const files = readdirSync(plansDir)
      .filter((f) => f.endsWith(".md"))
      .map((f) => {
        const fullPath = join(plansDir, f);
        const st = statSync(fullPath);
        return { name: f, fullPath, mtimeMs: st.mtimeMs };
      })
      .sort((a, b) => b.mtimeMs - a.mtimeMs);

    if (files.length === 0) return null;
    const latest = files[0];
    if (Date.now() - latest.mtimeMs > ACTIVE_PLAN_WINDOW_MS) return null;

    const content = readFileSync(latest.fullPath, "utf8");
    // Only enforce continuation when at least one item is already checked (- [x]) or start-work is active,
    // so we don't force execution during a pure planning phase before user approval.
    const checkedMatches = content.match(/^[ \t]*-\s+\[[xX]\]\s+/gm) || [];
    const uncheckedMatches = content.match(/^[ \t]*-\s+\[ \]\s+.+$/gm) || [];
    const unresolvedTriageMatches = (content.match(/^[ \t]*-\s*\[(?:intent_gap|bad_plan|patch)\][^\r\n]*$/gim) || [])
      .filter((line) => !/\b(?:RESOLVED|REVERTED|DONE|FIXED)\b/i.test(line));
    const startWorkActive = existsSync(join(cwd, ".asw", "start-work"));

    if ((uncheckedMatches.length > 0 || unresolvedTriageMatches.length > 0) && (checkedMatches.length > 0 || startWorkActive)) {
      const stateDir = join(cwd, ".asw", "start-work");
      const guardFile = join(stateDir, ".stop-guard.json");
      const signature = `${latest.name}:${checkedMatches.length}:${uncheckedMatches.length}:${unresolvedTriageMatches.length}`;
      let guard = { signature: "", count: 0 };
      if (existsSync(guardFile)) {
        try {
          guard = JSON.parse(readFileSync(guardFile, "utf8"));
        } catch {
          guard = { signature: "", count: 0 };
        }
      }
      if (guard.signature === signature) {
        if (guard.count >= MAX_AUTO_CONTINUES) {
          return null; // Prevent infinite loop if genuinely waiting on user decision/blocker
        }
        guard.count += 1;
      } else {
        guard = { signature, count: 1 };
      }
      mkdirSync(stateDir, { recursive: true });
      writeFileSync(guardFile, JSON.stringify(guard, null, 2), "utf8");

      return {
        planName: latest.name,
        uncheckedCount: uncheckedMatches.length,
        checkedCount: checkedMatches.length,
        unresolvedTriageCount: unresolvedTriageMatches.length,
        nextItem: uncheckedMatches.length > 0 ? uncheckedMatches[0].trim() : unresolvedTriageMatches[0].trim(),
      };
    }
  } catch {
    return null;
  }
  return null;
}

const payload = readPayload();
const cwd = resolveWorkspaceCwd(payload);

if (safeMode(payload) || payload.fullyIdle === false) {
  // When fullyIdle === false, an async subagent or background task is running and Antigravity's
  // reactive wakeup system will automatically resume this conversation when it finishes.
  process.stdout.write(JSON.stringify({ decision: "" }));
} else {
  const unfinishedPlan = findUncheckedActivePlan(cwd);
  if (unfinishedPlan) {
    const gateLabel = unfinishedPlan.unresolvedTriageCount > 0 && unfinishedPlan.uncheckedCount === 0
      ? `BMAD Review Triage Gate: Active plan '.asw/plans/${unfinishedPlan.planName}' has ${unfinishedPlan.unresolvedTriageCount} unresolved [intent_gap]/[bad_plan]/[patch] finding(s) in Review Triage Log.`
      : `Zero-Unchecked-Plan Gate: Active plan '.asw/plans/${unfinishedPlan.planName}' still has ${unfinishedPlan.uncheckedCount} unchecked task(s) (${unfinishedPlan.checkedCount} completed).`;
    process.stdout.write(JSON.stringify({
      decision: "continue",
      reason: `${gateLabel} Next item: "${unfinishedPlan.nextItem}". Dispatch Gemini 4 Hydrogen (High) to complete and verify remaining items or explicitly log a blocker.`,
    }));
  } else {
    if (payload.terminationReason === "NO_TOOL_CALL" || payload.fullyIdle === true) {
      foldTranscriptOnStop(payload, cwd);
    }
    process.stdout.write(JSON.stringify({ decision: "" }));
  }
}
