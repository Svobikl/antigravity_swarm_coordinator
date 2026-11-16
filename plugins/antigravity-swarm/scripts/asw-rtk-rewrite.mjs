#!/usr/bin/env node
/**
 * asw-rtk-rewrite.mjs
 *
 * Rewrites developer CLI commands (git, pytest, python -m pytest) to use the
 * rtk (Token Killer) CLI proxy, reducing output tokens by 50% to 98%.
 *
 * Handles compound shell operators (;, &&, ||, |) while preserving quotes and
 * protects Windows platforms by bypassing `rtk tree` (avoiding tree.com parameter conflicts).
 */

export function splitCommandSegments(cmd) {
  const segments = [];
  let current = "";
  let inSingleQuote = false;
  let inDoubleQuote = false;
  let i = 0;

  while (i < cmd.length) {
    const char = cmd[i];
    const next = cmd[i + 1];

    if (char === "'" && !inDoubleQuote) {
      inSingleQuote = !inSingleQuote;
      current += char;
      i++;
    } else if (char === '"' && !inSingleQuote) {
      inDoubleQuote = !inDoubleQuote;
      current += char;
      i++;
    } else if (!inSingleQuote && !inDoubleQuote) {
      if ((char === "&" && next === "&") || (char === "|" && next === "|")) {
        segments.push({ text: current, operator: char + next });
        current = "";
        i += 2;
      } else if (char === ";" || char === "|" || char === "&") {
        segments.push({ text: current, operator: char });
        current = "";
        i++;
      } else {
        current += char;
        i++;
      }
    } else {
      current += char;
      i++;
    }
  }
  segments.push({ text: current, operator: "" });
  return segments;
}

export function rewriteSingleCommand(cmd, isWindows = process.platform === "win32") {
  if (!cmd || typeof cmd !== "string") return cmd;
  const trimmed = cmd.trim();

  // If already rtk prefixed or rtk itself, keep as-is
  if (/^rtk(?:\.exe)?(\s+|$)/i.test(trimmed)) {
    return cmd;
  }

  // Windows tree guard: NEVER rewrite tree on Windows
  if (/^tree(?:\.com|\.exe)?(\s+|$)/i.test(trimmed)) {
    if (isWindows) {
      return cmd;
    }
    return cmd.replace(/^tree(\s+|$)/i, "rtk tree$1");
  }

  // Pytest commands: `pytest ...`, `python -m pytest ...`, `python3 -m pytest ...`, `py -m pytest ...`
  const pytestModuleMatch = cmd.match(/^((?:python3?|py)(?:\.exe)?\s+-m\s+pytest(?:\.exe)?)(\s.*)?$/i);
  if (pytestModuleMatch) {
    const rest = pytestModuleMatch[2] || "";
    return `rtk pytest${rest}`;
  }

  const pytestDirectMatch = cmd.match(/^(pytest(?:\.exe)?)(\s.*)?$/i);
  if (pytestDirectMatch) {
    const rest = pytestDirectMatch[2] || "";
    return `rtk pytest${rest}`;
  }

  // Git commands: `git ...` (git status, git log, git diff, etc.)
  const gitMatch = cmd.match(/^(git(?:\.exe)?)(\s.*)?$/i);
  if (gitMatch) {
    const rest = gitMatch[2] || "";
    return `rtk git${rest}`;
  }

  return cmd;
}

export function rewriteCommandToRtk(cmd, isWindows = process.platform === "win32") {
  if (!cmd || typeof cmd !== "string") return cmd;
  if (process.env.DISABLE_RTK_REWRITE === "1" || process.env.DISABLE_RTK_REWRITE === "true") {
    return cmd;
  }

  const segments = splitCommandSegments(cmd);
  let rewritten = "";

  for (const seg of segments) {
    const match = seg.text.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!match || !match[2]) {
      rewritten += seg.text + seg.operator;
      continue;
    }
    const leading = match[1];
    const core = match[2];
    const trailing = match[3];

    const rewrittenCore = rewriteSingleCommand(core, isWindows);
    rewritten += leading + rewrittenCore + trailing + seg.operator;
  }

  return rewritten;
}

// Support CLI and stdin execution
const isMain = process.argv[1] && (
  process.argv[1].endsWith("asw-rtk-rewrite.mjs") ||
  import.meta.url === `file://${process.argv[1]}`
);

if (isMain) {
  if (process.argv[2]) {
    const isWin = process.platform === "win32";
    process.stdout.write(rewriteCommandToRtk(process.argv[2], isWin) + "\n");
  } else {
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { input += chunk; });
    process.stdin.on("end", () => {
      const raw = input.trim();
      if (!raw) {
        process.exit(0);
      }
      try {
        const parsed = JSON.parse(raw);
        if (typeof parsed === "object" && parsed !== null) {
          if (typeof parsed.command === "string") {
            parsed.command = rewriteCommandToRtk(parsed.command);
          } else if (parsed.args && typeof parsed.args.CommandLine === "string") {
            parsed.args.CommandLine = rewriteCommandToRtk(parsed.args.CommandLine);
          } else if (parsed.CommandLine && typeof parsed.CommandLine === "string") {
            parsed.CommandLine = rewriteCommandToRtk(parsed.CommandLine);
          }
          process.stdout.write(JSON.stringify(parsed));
          return;
        }
      } catch {
        // Not JSON, treat as raw string
      }
      process.stdout.write(rewriteCommandToRtk(raw) + "\n");
    });
  }
}
