# Adversary routing: choosing a model that is not the author

## Step 1. Detect what is reachable

```bash
python3 scripts/detect_agents.py --json
```

Reports, as JSON:

- `clis`: for each of `claude`, `codex`, `gemini`, `opencode`, `aider`, `copilot`,
  `cursor-agent`, `goose`, `amp`, `qwen`, `kimi`: present on PATH, version string, vendor,
  default model family.
- `api_keys`: which of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` /
  `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`,
  `DEEPSEEK_API_KEY`, `XAI_API_KEY` are set (names only, never values).
- `current_session`: best guess of the model running this session, from
  `CLAUDE_CODE_*`/`ANTHROPIC_MODEL` environment, `CODEX_*`, `GEMINI_*`, or the harness.
  When the harness exposes its model identity (this session can call its own session-info
  tool), prefer that.

## Step 2. Apply the routing table

Vendor families: **anthropic** (Claude), **openai** (GPT, Codex), **google** (Gemini),
**other** (Mistral, DeepSeek, Qwen, Kimi, Llama via OpenRouter/Groq/Ollama). Independence is
satisfied when adversary vendor != author vendor. Same vendor, different model (e.g. Opus
grading Sonnet) is a weak second choice: it reduces shared training bias somewhat but not
shared product behavior. Record which tier you achieved.

| Author(s) of code / tests | Preferred adversary | Acceptable | Forbidden without user override |
|---|---|---|---|
| anthropic / anthropic | openai or google CLI | other vendor via API | any Claude |
| openai / openai | anthropic or google CLI | other vendor via API | any GPT/Codex |
| google / google | anthropic or openai CLI | other vendor via API | any Gemini |
| anthropic / openai (split) | google | anthropic attacks tests, openai attacks code, cross-check | a single one of the two grading its own half |
| human / model M | any vendor != M | same vendor, different model | M |
| model M / human | any vendor != M | same vendor, different model | M (human tests are still audited) |
| none yet, we (model X) will write tests | any vendor != X | same vendor, different model | X |

If the current session's model already satisfies "vendor != author", the current session
**is** the adversary and no external call is needed. Say so in the report.

## Step 3. Invoke the external adversary

`scripts/run_adversary.sh` handles the mechanics:

```bash
scripts/run_adversary.sh \
  --agent codex \                       # claude | codex | gemini | opencode | aider
  --author anthropic \                  # vendor recorded in 01-provenance.json
  --target "src/pagination.py" \
  --spec adversarial/00-intake.md \
  --out adversarial/02-adversary/ \
  [--model gpt-5.1-codex] [--budget-minutes 15] [--allow-same-model]
```

It assembles the prompt from `assets/prompts/adversary_prompt.md` plus the intake and the
attack plan, runs the agent in its non-interactive mode with write access limited to
`adversarial/`, and saves stdout, stderr, and the agent's final message. It exits non-zero
with a clear message when the agent's vendor equals `--author` and `--allow-same-model` is
absent.

Non-interactive invocations it uses (verify with `--help` on the installed version; flags
move):

| Agent | Command shape | Notes |
|---|---|---|
| Claude Code | `claude -p "<prompt>" --model <alias> --output-format json --permission-mode acceptEdits --add-dir adversarial --max-turns N` | `--allowedTools "Bash(python3 *) Read Write Edit"` to narrow further; `--json-schema` for structured findings |
| Codex CLI | `codex exec "<prompt>" -m <model> --sandbox workspace-write --json -o adversarial/02-adversary/codex-result.json` | `--output-schema <file>` constrains the final message; `--skip-git-repo-check` outside a repo |
| Gemini CLI | `gemini -p "<prompt>" -m <model> --output-format json` | `--yolo` auto-approves tool calls; prefer a sandbox |
| OpenCode | `opencode run "<prompt>" --model <provider/model>` | model string is `provider/model` |
| Aider | `aider --model <model> --yes --message "<prompt>" <files>` | edits files directly; point it only at `adversarial/` |

Prompt-size limits differ. Put long context (intake, plan, test listings) in files and tell
the agent to read them rather than inlining everything.

## Step 4. Direct API fallback

When no second CLI exists but a second vendor's API key does, the adversary can be a plain
chat completion: send `adversary_prompt.md`, the spec, the public signatures, and the
existing tests, and ask for attack cases and properties in the findings JSON schema. The
current session then executes those cases locally. This preserves independence of the
*oracle design* (the part self-preference corrupts) while execution stays local. Record it
as `adversary_mode: api-oracle-only`.

## Step 5. When independence is impossible

Stop. Tell the user, in one short message:

> The code and tests were written by <model>. The only model I can run is <same model>.
> Running the adversarial pass with the author model weakens the result: it shares the
> author's blind spots and tends to rate its own work favorably. Options: (a) install or
> authorize another agent CLI or API key, (b) proceed same-model with a prominent warning in
> the report, (c) stop here.

Proceed only on an explicit (b). Then:

- Start the adversary in a **fresh process** with `--append-system-prompt` (or equivalent)
  containing the adversary prompt, never in the authoring conversation.
- Deny the adversary read access to the author's tests during the blind pass (do not list
  or open them until the informed pass).
- Add `INDEPENDENCE WARNING: same-model adversary by user decision` to the report header
  and to every finding's `independence` field.

## Step 6. Record the decision

`adversarial/02-routing.json`:

```json
{
  "author_vendors": ["anthropic"],
  "adversary": {"agent": "codex", "model": "gpt-5.1-codex", "vendor": "openai"},
  "independence": "cross-vendor",
  "user_override": false,
  "detected": { "clis": ["claude", "codex"], "api_keys": ["ANTHROPIC_API_KEY"] }
}
```

`independence` is one of `cross-vendor`, `same-vendor-different-model`,
`same-model-user-override`, `api-oracle-only`.
