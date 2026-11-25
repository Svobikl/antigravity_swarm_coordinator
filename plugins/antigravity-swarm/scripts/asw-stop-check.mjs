#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { safeMode } from "./asw-redact.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const MAX_AUTO_CONTINUES = 3;
const ACTIVE_PLAN_WINDOW_MS = 6 * 60 * 60 * 1000; // 6 hours
const IGNORED_PLAN_NAMES = new Set(["deferred-work.md"]);
const INACTIVE_PLAN_STATUSES = new Set([
  "done",
  "completed",
  "deferred",
  "archived",
  "cancelled",
  "canceled",
]);
const TERMINAL_STATE_STATUS_RE = /^(?:orchestration\s+complete|complete(?:d)?|done|cancell?ed|failed|aborted|stopped|expired)$/i;

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

function extractFrontmatterStatus(content) {
  const clean = String(content ?? "").replace(/^\uFEFF/, "");
  const fmMatch = clean.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!fmMatch) return "";
  const statusMatch = fmMatch[1].match(/^[ \t]*status:[ \t]*(.+)$/im);
  if (!statusMatch) return "";
  let val = statusMatch[1].trim();
  if ((val.startsWith('"') && val.includes('"', 1)) || (val.startsWith("'") && val.includes("'", 1))) {
    const quote = val[0];
    val = val.slice(1, val.indexOf(quote, 1));
  } else {
    val = val.replace(/\s+#.*$/, "").replace(/^#.*$/, "");
  }
  return val.trim().replace(/^["']|["']$/g, "").trim().toLowerCase();
}

function readStartWorkState(cwd) {
  const stateDir = join(cwd, ".asw", "start-work");
  const guardFile = join(stateDir, ".stop-guard.json");
  if (existsSync(guardFile)) {
    try {
      const gst = statSync(guardFile);
      if (Date.now() - gst.mtimeMs > ACTIVE_PLAN_WINDOW_MS) {
        unlinkSync(guardFile);
      }
    } catch {
      // ignore cleanup errors
    }
  }

  const stateFile = join(stateDir, "state.json");
  if (!existsSync(stateFile)) return null;
  try {
    const st = statSync(stateFile);
    const parsed = JSON.parse(readFileSync(stateFile, "utf8"));
    const rawStatus = String(parsed?.status ?? "").trim();
    const statePlan = typeof parsed?.plan === "string" && parsed.plan.trim()
      ? basename(parsed.plan.trim())
      : "";
    return {
      isFresh: Date.now() - st.mtimeMs <= ACTIVE_PLAN_WINDOW_MS,
      isTerminal: TERMINAL_STATE_STATUS_RE.test(rawStatus),
      hasStatus: Boolean(rawStatus),
      planName: statePlan,
    };
  } catch {
    return null;
  }
}

function isPlanTerminalInState(stateInfo, candidateName) {
  if (!stateInfo || !stateInfo.isFresh) return false;
  if (!stateInfo.isTerminal) return false;
  return !stateInfo.planName || stateInfo.planName === candidateName;
}

function isStartWorkActiveForPlan(cwd, candidateName, frontmatterStatus, stateInfo = readStartWorkState(cwd)) {
  if (isPlanTerminalInState(stateInfo, candidateName)) {
    return false;
  }
  if (
    stateInfo &&
    stateInfo.isFresh &&
    stateInfo.hasStatus &&
    !stateInfo.isTerminal &&
    (!stateInfo.planName || stateInfo.planName === candidateName)
  ) {
    return true;
  }
  return frontmatterStatus === "in-progress";
}

function findUncheckedActivePlan(cwd) {
  try {
    const stateInfo = readStartWorkState(cwd);
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

    const nowMs = Date.now();
    for (const candidate of files) {
      if (nowMs - candidate.mtimeMs > ACTIVE_PLAN_WINDOW_MS) break;
      if (IGNORED_PLAN_NAMES.has(candidate.name.toLowerCase())) continue;
      if (isPlanTerminalInState(stateInfo, candidate.name)) continue;

      const content = readFileSync(candidate.fullPath, "utf8");
      const frontmatterStatus = extractFrontmatterStatus(content);
      if (INACTIVE_PLAN_STATUSES.has(frontmatterStatus)) continue;

      // Only enforce continuation when at least one item is already checked (- [x]) or start-work is active
      // for this specific plan, so we don't force execution during a pure planning phase before user approval.
      const checkedMatches = content.match(/^[ \t]*-\s+\[[xX]\]\s+/gm) || [];
      const uncheckedMatches = content.match(/^[ \t]*-\s+\[ \]\s+.+$/gm) || [];
      const unresolvedTriageMatches = (content.match(/^[ \t]*-\s*\[(?:intent_gap|bad_plan|patch)\][^\r\n]*$/gim) || [])
        .filter((line) => !/\b(?:RESOLVED|REVERTED|DONE|FIXED)\b/i.test(line));
      const startWorkActive = isStartWorkActiveForPlan(cwd, candidate.name, frontmatterStatus, stateInfo);

      if ((uncheckedMatches.length > 0 || unresolvedTriageMatches.length > 0) && (checkedMatches.length > 0 || startWorkActive)) {
        const stateDir = join(cwd, ".asw", "start-work");
        const guardFile = join(stateDir, ".stop-guard.json");
        const signature = `${candidate.name}:${checkedMatches.length}:${uncheckedMatches.length}:${unresolvedTriageMatches.length}`;
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
          planName: candidate.name,
          uncheckedCount: uncheckedMatches.length,
          checkedCount: checkedMatches.length,
          unresolvedTriageCount: unresolvedTriageMatches.length,
          nextItem: uncheckedMatches.length > 0 ? uncheckedMatches[0].trim() : unresolvedTriageMatches[0].trim(),
        };
      }
    }
  } catch {
    return null;
  }
  return null;
}

const payload = readPayload();
const cwd = resolveWorkspaceCwd(payload);

if (
  safeMode(payload) ||
  payload.fullyIdle === false ||
  payload.continuationActive === true ||
  (payload.terminationReason && payload.terminationReason !== "NO_TOOL_CALL")
) {
  // When fullyIdle === false, continuationActive === true, or terminationReason is USER_CANCELED/ERROR/MAX_INVOCATIONS,
  // never override termination or inject continuation.
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
