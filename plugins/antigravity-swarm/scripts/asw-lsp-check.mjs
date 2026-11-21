#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { extname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { safeMode } from "./asw-redact.mjs";

let payload = {};
try {
  const raw = readFileSync(0, "utf8");
  payload = raw.trim() ? JSON.parse(raw) : {};
} catch {
  // Antigravity treats an empty JSON object as a successful no-op hook result.
}

if (safeMode(payload)) {
  process.stdout.write("{}");
  process.exit(0);
}

function resolveWorkspaceDir(p) {
  const candidates = [
    p?.cwd,
    Array.isArray(p?.workspacePaths) ? p.workspacePaths[0] : undefined,
    Array.isArray(p?.workspaceUris) ? p.workspaceUris[0] : undefined,
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

function isPostToolUseEvent(p) {
  const idx = process.argv.indexOf("--event");
  const argEvent = idx >= 0 ? String(process.argv[idx + 1] ?? "") : "";
  const ev = argEvent || String(p?.hookEventName ?? p?.event ?? "");
  return ev.trim().toLowerCase() === "posttooluse";
}

function extractTargetFile(p) {
  const args = p?.toolCall?.args || p?.toolArgs || p?.arguments || p?.input || p?.tool_input || {};
  return (
    args.Path ||
    args.TargetFile ||
    args.targetFile ||
    args.file_path ||
    args.path ||
    p?.filePath ||
    ""
  );
}

function checkFileIntegrity(filePath) {
  if (!filePath || typeof filePath !== "string" || !existsSync(filePath)) {
    return null;
  }
  const ext = extname(filePath).toLowerCase();
  try {
    if (ext === ".json") {
      JSON.parse(readFileSync(filePath, "utf8"));
    } else if (ext === ".js" || ext === ".mjs" || ext === ".cjs") {
      execFileSync(process.execPath, ["--check", filePath], {
        stdio: "pipe",
        timeout: 4000,
      });
    } else if (ext === ".py") {
      const pyBin = process.platform === "win32" ? "python" : "python3";
      execFileSync(pyBin, ["-m", "py_compile", filePath], {
        stdio: "pipe",
        timeout: 4000,
      });
    }
  } catch (err) {
    const msg = String(err?.stderr || err?.message || "Syntax error").slice(0, 300);
    return `Layer-1 Static Check FAILED on ${filePath}: ${msg}`;
  }
  return null;
}

const repoDir = resolveWorkspaceDir(payload);
const rawTarget = extractTargetFile(payload);
const targetFile =
  rawTarget && typeof rawTarget === "string"
    ? isAbsolute(rawTarget)
      ? rawTarget
      : resolve(repoDir, rawTarget)
    : "";
const diagnostic = checkFileIntegrity(targetFile);

if (isPostToolUseEvent(payload)) {
  if (diagnostic) {
    try {
      const aswDir = join(repoDir, ".asw");
      mkdirSync(aswDir, { recursive: true });
      writeFileSync(
        join(aswDir, ".pending-lsp-diagnostic.json"),
        JSON.stringify({ diagnostic, ts: Date.now() }),
        "utf8"
      );
    } catch {
      // fail-open
    }
  }
  process.stdout.write("{}");
} else if (diagnostic) {
  process.stdout.write(
    JSON.stringify({
      injectSteps: [
        {
          ephemeralMessage: `ASW POST-EDIT DIAGNOSTIC: ${diagnostic}. Fix the syntax/structural error before proceeding to Layer-2 and Layer-3 verification.`,
        },
      ],
    })
  );
} else {
  process.stdout.write("{}");
}

