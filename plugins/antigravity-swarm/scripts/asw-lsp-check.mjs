#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { extname } from "node:path";
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

function extractTargetFile(p) {
  const args = p?.toolArgs || p?.arguments || p?.input || p?.tool_input || {};
  return (
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
    }
  } catch (err) {
    const msg = String(err?.stderr || err?.message || "Syntax error").slice(0, 300);
    return `Layer-1 Static Check FAILED on ${filePath}: ${msg}`;
  }
  return null;
}

const targetFile = extractTargetFile(payload);
const diagnostic = checkFileIntegrity(targetFile);

if (diagnostic) {
  process.stdout.write(
    JSON.stringify({
      injectSteps: [
        {
          userMessage: `ASW POST-EDIT DIAGNOSTIC: ${diagnostic}. Fix the syntax/structural error before proceeding to Layer-2 and Layer-3 verification.`,
        },
      ],
    })
  );
} else {
  process.stdout.write("{}");
}

