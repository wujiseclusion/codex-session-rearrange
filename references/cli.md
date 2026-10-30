# Runnable workflow

The authoritative installed skill lives under `~/.codex/skills/codex-session-rearrange`. Workspace files are staging only. The script has no in-place edit mode and does not use forks.

## Prerequisites

Use Python 3.10+ and the observed `state_5.sqlite` / `thread_history_1.sqlite` storage schema. Compressed ancestors require `python -m pip install zstandard`. Select an exact source UUID with app tools and confirm it is stopped; the script detects file changes but cannot reliably determine active agent state. Live app access is still needed for UI acceptance.

In PowerShell, set a task-specific script path:

```powershell
$repairScript = "$HOME/.codex/skills/codex-session-rearrange/scripts/rearrange.py"
python $repairScript --help
python $repairScript prepare --source '<source-UUID>' --title 'My chat (cleaned copy)'
```

`prepare` reads live databases in read-only mode, copies effective history segments, backs up both databases, writes a standalone rollout and a separate projection database, and validates them. It does not register a chat or change source records. Backups may contain sensitive history from other chats because the database backup is complete; keep them local. They are not included in the skill package.

Default output: `~/.codex/session-rearrange-backups/<fresh-UUID>/`. Set `--output <directory>` to choose durable local storage; a UUID child directory is always created. `--home <directory>` selects an isolated Codex data directory for testing.

The bundle contains:

- `original/`: immutable input copies and the two database backups.
- `rollout.jsonl`: independent regrouped history with continuous ordinals.
- `projection.sqlite`: matching round, item and cursor indices.
- `manifest.json`: source and new IDs, source row, file hashes, counts and explicit unverified UI/execution status.

If a source changes or a needed UI item projection cannot be found, preparation stops. A failed partial bundle can be inspected but cannot be installed without its completed manifest and successful validation. Preserve the backup while diagnosing the error.

```powershell
python $repairScript verify '<bundle-directory>'
python $repairScript install '<bundle-directory>'
```

`verify` checks hashes, JSON, continuous ordinals, byte offsets, independence, item/round associations, final-answer links, counts and projection cursor. `install` repeats validation, copies the rollout, then inserts only the new UUID into the live state and history databases. It refuses overwrites and rolls back its transaction and newly copied file on ordinary installation errors. It does not promise power-loss atomicity across SQLite files in WAL mode. Do not interrupt installation or manually edit its bundle/live files.

Use `set_thread_title` if the app needs its sidebar title refreshed. Read the installed UUID through `read_thread` to check actual content before claiming success. Open that exact copy in the UI and inspect folding. A returned `registered: true` is not UI acceptance. The script does not launch chats, send messages or resume project work.

## Tests and practical limits

```powershell
python "$HOME/.codex/skills/codex-session-rearrange/scripts/test_rearrange.py"
```

The integration test creates isolated databases and exercises history cutoffs, Chinese UTF-8 byte offsets, async questions, a file-change item, final-answer grouping, unfinished tails, copy-only registration, overwrite refusal, source preservation and tamper rejection. It never points at real session data. A separate optional test exercises compressed decoding and inherited byte cutoffs when zstandard is installed.

A real offline run on the successful v4 history reproduced 28,950 indexed items, 87 async questions and 52 completed rounds. Earlier user acceptance established the manual workflow's UI behavior; the automated script's newly installed output still requires its own UI check. It has not been used to start further agent work.

Native UI item serialization is version-sensitive. The script reuses indexed native items by stable item ID, preferring the selected source and then other indexed copies. It stops on missing display-item templates; `Extension` records without UI templates are retained in raw history and counted as bookkeeping. It deliberately does not guess arbitrary new raw-to-UI mappings. Revisit this assumption for new versions or new visible Extension types.

No forced “上 n 条消息” label is implemented: reliable round structure and genuine/null timing are stored, and Codex chooses its presentation. A completed round means a final model answer exists, not that all engineering tasks succeeded.
