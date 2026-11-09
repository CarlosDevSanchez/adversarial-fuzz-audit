#!/usr/bin/env bash
# Run the adversarial pass on a DIFFERENT model's agent CLI, with an independence guard.
#
# Usage:
#   run_adversary.sh --agent <claude|codex|gemini|opencode|aider> --author <anthropic|openai|google|other|unknown>
#                    --target <path-or-glob> [--spec FILE] [--plan FILE] [--out DIR]
#                    [--model MODEL] [--budget-minutes N] [--allow-same-model] [--dry-run]
#
# The script:
#   1. maps the agent to its vendor and refuses when vendor == --author unless --allow-same-model
#   2. assembles the prompt from assets/prompts/adversary_prompt.md + intake + plan + target list
#   3. invokes the agent in non-interactive mode, writes transcript/result files under --out
#   4. prints the path of the agent's final message so the caller can turn it into findings.json
#
# Flags for each CLI change between releases; run `<agent> --help` if an invocation fails and
# adjust ADVERSARY_EXTRA_ARGS (env var, appended verbatim to the agent command).
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT="" AUTHOR="unknown" TARGET="" SPEC="" PLAN="" OUT="adversarial/02-adversary" MODEL="" BUDGET=15 ALLOW_SAME=0 DRY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2;;
    --author) AUTHOR="$2"; shift 2;;
    --target) TARGET="$2"; shift 2;;
    --spec) SPEC="$2"; shift 2;;
    --plan) PLAN="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --budget-minutes) BUDGET="$2"; shift 2;;
    --allow-same-model) ALLOW_SAME=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

[[ -z "$AGENT" || -z "$TARGET" ]] && { echo "--agent and --target are required (see --help)" >&2; exit 2; }

case "$AGENT" in
  claude) VENDOR=anthropic;;
  codex|copilot) VENDOR=openai;;
  gemini) VENDOR=google;;
  opencode|aider|cursor-agent|goose)
    VENDOR=multi
    if [[ -n "$MODEL" ]]; then
      case "$MODEL" in
        *claude*|anthropic/*) VENDOR=anthropic;;
        *gpt*|*codex*|*o[0-9]*|openai/*) VENDOR=openai;;
        *gemini*|google/*) VENDOR=google;;
        *) VENDOR=other;;
      esac
    fi;;
  *) echo "unsupported agent: $AGENT" >&2; exit 2;;
esac

# ---- independence guard -----------------------------------------------------------------
if [[ "$VENDOR" == "$AUTHOR" && $ALLOW_SAME -eq 0 ]]; then
  cat >&2 <<MSG
INDEPENDENCE GUARD: adversary '$AGENT' resolves to vendor '$VENDOR', which is the recorded author vendor.
A model grading its own work shares its blind spots and shows self-preference bias.
Choose another agent/model, or ask the user and re-run with --allow-same-model to record an explicit override.
MSG
  exit 3
fi
if [[ "$VENDOR" == "multi" ]]; then
  echo "note: '$AGENT' routes to whichever provider is configured; pass --model so the vendor can be checked." >&2
fi
INDEPENDENCE="cross-vendor"
[[ "$VENDOR" == "$AUTHOR" ]] && INDEPENDENCE="same-model-user-override"
[[ "$VENDOR" == "multi" ]] && INDEPENDENCE="unverified-provider"

mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PROMPT_FILE="$OUT/prompt-$STAMP.md"

# ---- assemble prompt ---------------------------------------------------------------------
{
  cat "$SKILL_DIR/assets/prompts/adversary_prompt.md"
  echo; echo "## Engagement parameters"
  echo "- Target(s): $TARGET"
  echo "- Author vendor (do not trust their tests): $AUTHOR"
  echo "- Your vendor: $VENDOR  (independence: $INDEPENDENCE)"
  echo "- Budget: $BUDGET minutes wall-clock. Stop and write findings when it is spent."
  echo "- Write ONLY under: adversarial/  (harnesses, corpora, findings.json). Never edit the target or its tests."
  echo "- Skill scripts available at: $SKILL_DIR/scripts/  (gen_malformed.py, test_smells.py, quick_mutants.py, report_builder.py)"
  echo "- Findings schema: $SKILL_DIR/assets/findings_schema.json"
  if [[ -n "$SPEC" && -f "$SPEC" ]]; then echo; echo "## Intake / specification"; cat "$SPEC"; fi
  if [[ -n "$PLAN" && -f "$PLAN" ]]; then echo; echo "## Attack plan so far"; cat "$PLAN"; fi
  echo; echo "## Deliverable"
  echo "Write adversarial/findings.json conforming to the schema, then print a 10-line summary: verdict on the claim, number of findings by severity, surviving mutants, what you could not test."
} > "$PROMPT_FILE"

echo "prompt: $PROMPT_FILE  (agent=$AGENT vendor=$VENDOR author=$AUTHOR independence=$INDEPENDENCE)"
EXTRA=${ADVERSARY_EXTRA_ARGS:-}

# ---- invocation --------------------------------------------------------------------------
case "$AGENT" in
  claude)
    CMD=(claude -p "__PROMPT__" --output-format json --permission-mode acceptEdits --add-dir "$(pwd)/adversarial")
    [[ -n "$MODEL" ]] && CMD+=(--model "$MODEL")
    CMD+=(--max-turns 60);;
  codex)
    CMD=(codex exec --sandbox workspace-write --json -o "$OUT/codex-result-$STAMP.json")
    [[ -n "$MODEL" ]] && CMD+=(-m "$MODEL")
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || CMD+=(--skip-git-repo-check)
    CMD+=("__PROMPT__");;
  gemini)
    CMD=(gemini -p "__PROMPT__" --output-format json --yolo)
    [[ -n "$MODEL" ]] && CMD+=(-m "$MODEL");;
  opencode)
    CMD=(opencode run "__PROMPT__")
    [[ -n "$MODEL" ]] && CMD+=(--model "$MODEL");;
  aider)
    CMD=(aider --yes --no-auto-commits --message "__PROMPT__")
    [[ -n "$MODEL" ]] && CMD+=(--model "$MODEL");;
  copilot)
    CMD=(copilot -p "__PROMPT__" --allow-all-tools)
    [[ -n "$MODEL" ]] && CMD+=(--model "$MODEL");;
esac
# shellcheck disable=SC2206
[[ -n "$EXTRA" ]] && CMD+=($EXTRA)

{
  echo "agent=$AGENT"; echo "vendor=$VENDOR"; echo "author=$AUTHOR"; echo "model=${MODEL:-default}"
  echo "independence=$INDEPENDENCE"; echo "budget_minutes=$BUDGET"; echo "started=$STAMP"
  echo "prompt_file=$PROMPT_FILE"
  printf 'command='; printf '%q ' "${CMD[@]}"; echo
} > "$OUT/run-$STAMP.meta"

if [[ $DRY -eq 1 ]]; then
  echo "dry run; would execute (__PROMPT__ = contents of $PROMPT_FILE):"; printf '  %q' "${CMD[@]}"; echo
  exit 0
fi
command -v "${CMD[0]}" >/dev/null || { echo "agent CLI '${CMD[0]}' not found on PATH" >&2; exit 4; }
PROMPT_TEXT="$(cat "$PROMPT_FILE")"
for i in "${!CMD[@]}"; do [[ "${CMD[$i]}" == "__PROMPT__" ]] && CMD[$i]="$PROMPT_TEXT"; done

set +e
timeout "$((BUDGET * 60 + 120))" "${CMD[@]}" >"$OUT/stdout-$STAMP.log" 2>"$OUT/stderr-$STAMP.log"
RC=$?
set -e
echo "exit=$RC" >> "$OUT/run-$STAMP.meta"
echo "agent exit code $RC; stdout: $OUT/stdout-$STAMP.log  stderr: $OUT/stderr-$STAMP.log"
[[ -f adversarial/findings.json ]] && echo "findings: adversarial/findings.json" || echo "no adversarial/findings.json produced; read the stdout log and build it by hand"
exit $RC
