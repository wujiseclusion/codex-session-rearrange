# Codex Session Rearrange — 整理 Codex 对话

[简体中文](README.zh-CN.md) · English

An experimental, local Codex skill and Python CLI to **clean capacity-error interruptions and regroup chat history into foldable rounds**. Keywords: **整理codex对话**, **删除codex上下文的报错信息**, Codex conversation cleanup, Codex context error cleanup, 429 Too Many Requests, selected model is at capacity, reasoning collapse, chat history repair.

**Independent copies only. Mandatory backups. Not an official OpenAI tool.** This changes the stored/displayed history of a new copy; it does not repair a provider outage, reduce an account's rate limits, or guarantee that future model context will shrink.

## What it does

- Copies the effective local history chain, including `.jsonl.zst` ancestors and inherited cutoffs.
- Assigns a fresh session UUID and removes history inheritance dependencies.
- Groups intermediate messages, reasoning summaries, tool calls and file changes until a genuine final model answer; async questions are retained inside the round.
- Rebuilds continuous ordinals, UTF-8 byte offsets and matching round/item indices to avoid the known missing-ordinal and blank-page failures.
- Leaves unanswered work unfinished and calculates elapsed time only from available timestamps. Codex chooses the collapse label; neither “previous n messages” nor a duration label is forced.
- Includes `prepare`, `verify` and `install`; preparation never registers a chat.

## Error support — please read

| Situation | Current behavior |
|---|---|
| Explicit 429 / at-capacity completion or standalone error event | Removes old completion boundaries / recognized error display events in the copy; original details remain in backups |
| Other old completion/abort boundaries, including failures | Regroups across them; the old boundary and its embedded error metadata are not reproduced in the cleaned rollout. Read the original backup for their details |
| Other standalone error events (500, tool errors, etc.) | Retained; this is **not** a universal error-redaction tool |
| An assistant's substantive message mentioning an error | Retained; no global text substitution |
| Unsupported record format or missing native UI projection | Stops when detected; no in-place fallback |
| Real API, network, build or tool failure | Does not fix it or turn it into a success |

Grouping can work across other interruptions when the same storage schema applies. Automatic identification of removable standalone errors is currently limited to capacity errors. New error types require an explicit rule and a regression test. Review the copy before deleting anything.

## Requirements and compatibility

- Python 3.10+; `zstandard` only for compressed ancestors.
- The observed `state_5.sqlite` / `thread_history_1.sqlite` layout. Select a stopped source chat with a known UUID and a fully materialized UI history index.
- Manual workflow validated on Windows / Codex Desktop **26.1027.30824**. Internal schemas are version-sensitive. No claim of compatibility with every Codex release or ChatGPT cloud conversations.
- Native UI item JSON is reused by stable item ID from the local history index, preferring the source and then other indexed copies. Missing visible-item templates cause preparation to stop; bookkeeping Extension records are retained in raw history.

## Install the skill

Clone into a **new** skill directory. If it already exists, back it up and inspect it before updating.

PowerShell:

```powershell
$skillDir = Join-Path $HOME '.codex/skills/codex-session-rearrange'
if (Test-Path -LiteralPath $skillDir) { throw 'Skill already exists; back it up before updating.' }
git clone https://github.com/wujiseclusion/codex-session-rearrange.git $skillDir
python -m pip install -r "$skillDir/requirements.txt"
```

macOS/Linux (CLI setup only; desktop UI compatibility not established):

```sh
test ! -e "$HOME/.codex/skills/codex-session-rearrange" || exit 1
git clone https://github.com/wujiseclusion/codex-session-rearrange.git "$HOME/.codex/skills/codex-session-rearrange"
python3 -m pip install -r "$HOME/.codex/skills/codex-session-rearrange/requirements.txt"
```

Use a virtual environment if your Python requires one. Start a new Codex chat if skill discovery has not refreshed. Invoke **`$codex-session-rearrange`**, or ask **“整理codex对话”** / **“删除codex上下文的报错信息”**. The skill description includes these phrases. Search-engine indexing and ranking are outside this repository's control.

This repository is a skill + CLI, not a registered Codex marketplace plugin.

## Use the CLI

Ask Codex to find the exact source UUID by title, confirm it is stopped, then run:

```powershell
$repairScript = Join-Path $HOME '.codex/skills/codex-session-rearrange/scripts/rearrange.py'
python $repairScript prepare --source '<SOURCE-UUID>' --title 'My chat (cleaned copy)'
python $repairScript verify '<BUNDLE-DIRECTORY>'
python $repairScript install '<BUNDLE-DIRECTORY>'
```

`prepare` prints the new ID and bundle path. It creates `~/.codex/session-rearrange-backups/<new-UUID>/` by default; use `--output` for another durable directory and `--home` for an isolated Codex data directory. Do not put backups in a public repository.

`install` repeats validation and inserts only the fresh UUID. It refuses overwriting an existing session. The script neither sends a chat message nor resumes engineering work. Open the exact title/UUID in Codex, check early/middle/latest history and folding, and verify file changes remain in the intended round. A zero exit status or `registered: true` does not prove UI acceptance or future execution reliability.

For full mechanics, see [CLI reference](references/cli.md) and [workflow](references/workflow.md).

## Backup, deletion and recovery

Every preparation keeps `original/` record copies, complete SQLite backups, `manifest.json` hashes/counts, the independent `rollout.jsonl`, and `projection.sqlite`. Sources are opened read-only; no in-place editing mode exists. File hashes are rechecked, but separate file/database snapshots are not an atomic snapshot of an active application. Stop the source first. Keep enough free disk space for large histories and complete database copies.

**Database backups can contain all of your local chats, private data and tool output. Never upload bundles, manifests, JSONL histories or SQLite files to issues or this repository.** They are local backups, not distributable artifacts.

The main copied history has independent files/indices and no `history_base` / `forked_from_id`. An isolated test confirms the copy survives deletion of the fixture source. **Child-agent conversations, attachments, images and project files are not recursively copied.** Old agent IDs remain historical references. Do not delete the original and child chats until those dependencies are separately backed up and checked. Reading history does not prove that old agents can resume.

On ordinary install errors, the script rolls back its transaction and newly copied rollout. Power loss across WAL-backed databases is not guaranteed atomic. After UI acceptance, use Codex's normal archive/delete operations for a disposable copy. Full-database restoration is a manual disaster-recovery operation: close Codex first and understand it can revert **all chats**, not only this copy. Never overwrite live databases while Codex is running.

## Tests

```powershell
python "$HOME/.codex/skills/codex-session-rearrange/scripts/test_rearrange.py"
```

Offline isolated tests cover cutoffs, Unicode offsets, async questions, diffs, final-answer grouping, unfinished tails, non-capacity error retention, copy registration, overwrite refusal, source deletion independence, tamper rejection, and optional zstd decoding. CI runs on Windows/Ubuntu and Python 3.10/3.13.

A real offline preparation reproduced **28,950 indexed items, 87 async questions and 52 completed rounds** from a previously user-accepted repair. A script-installed output still needs its own UI verification. Further agent execution was not validated.

## Disclaimer and attribution

This is an independent community utility, **not made, endorsed or supported by OpenAI**. Codex and ChatGPT are OpenAI products. The workflow was developed through local experimentation with Codex's stored history; those internal formats are not a stable public import API.

Use at your own risk. The software is provided **AS IS**, without warranty of correctness, compatibility, fitness, data preservation or future usability. Back up your data, inspect the output and retain a recovery path. To the extent permitted by law, authors/contributors are not liable for data loss, corruption, downtime or other damages. See [MIT License](LICENSE).
