#!/usr/bin/env node

import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { safeMode } from "./asw-redact.mjs";

const MAX_AUTO_CONTINUES = 3;
const ACTIVE_PLAN_WINDOW_MS = 6 * 60 * 60 * 1000; // 6 hours

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
    const startWorkActive = existsSync(join(cwd, ".asw", "start-work"));

    if (uncheckedMatches.length > 0 && (checkedMatches.length > 0 || startWorkActive)) {
      const stateDir = join(cwd, ".asw", "start-work");
      const guardFile = join(stateDir, ".stop-guard.json");
      const signature = `${latest.name}:${checkedMatches.length}:${uncheckedMatches.length}`;
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
        nextItem: uncheckedMatches[0].trim(),
      };
    }
  } catch {
    return null;
  }
  return null;
}

const payload = readPayload();
const cwd = payload.cwd || process.cwd();

if (safeMode(payload)) {
  process.stdout.write(JSON.stringify({ decision: "" }));
} else if (payload.fullyIdle === false) {
  process.stdout.write(JSON.stringify({
    decision: "continue",
    reason: "Antigravity Swarm detected active background work. Continue until spawned work is idle, verified, and cleaned up.",
  }));
} else {
  const unfinishedPlan = findUncheckedActivePlan(cwd);
  if (unfinishedPlan) {
    process.stdout.write(JSON.stringify({
      decision: "continue",
      reason: `Zero-Unchecked-Plan Gate: Active plan '.asw/plans/${unfinishedPlan.planName}' still has ${unfinishedPlan.uncheckedCount} unchecked task(s) (${unfinishedPlan.checkedCount} completed). Next unchecked item: "${unfinishedPlan.nextItem}". Dispatch Gemini 3.8 Flash (High) to complete and verify remaining items or explicitly log a blocker.`,
    }));
  } else {
    process.stdout.write(JSON.stringify({ decision: "" }));
  }
}

