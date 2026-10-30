---
name: codex-session-rearrange
description: Clean capacity-error interruptions and regroup local Codex session copies into foldable rounds. Use for 整理codex对话, 删除codex上下文的报错信息, cluttered local Codex chat history or blank experimental copies; preserve the source conversation.
---

# Codex session rearrange

Create an independent, reviewable copy of a local Codex conversation. Work only within the user's authorized target. Default to a new session ID and copied history; altering the source requires explicit authorization.

Read [the workflow](references/workflow.md) before transforming records or registering a copy. This is a version-sensitive local repair procedure, not an official import API.

Use the bundled [script](scripts/rearrange.py) rather than recreating the transformation. Read [CLI usage](references/cli.md) for commands, prerequisites and validation boundaries. Run `prepare`, then `verify`; use `install` only within the user's authorized scope. The script always generates a fresh ID, never rewrites a source, and rejects an already registered copy.

## Execution

1. Identify the source by app title and ID. Confirm whether it is running. Snapshot records and relevant SQLite state before transformation; record paths, hashes, app version, and schema. Keep the source unchanged.
2. Materialize the effective history chain into independent files. Follow metadata inheritance cutoffs rather than concatenating every matching file wholesale.
3. Regroup messages until a genuine final model answer. Preserve async questions, progress messages, reasoning summaries, commands, and diffs inside that round. Capacity errors are display artifacts to clean, not proof of successful work.
4. Preserve the storage contract: sequence ordinals, event shape, round IDs, item associations, byte offsets, and projection positions. Register only the independent copy. Rebuild its round and item indices together.
5. Verify file structure, then app-backed history reads, then visible loading and folding. A successful file write or registration is not a successful UI repair.

## Report

Name the copy and give its ID, source backup location, changed-event counts, completed-round count, unfinished tail status, and validation result. Distinguish backend readability, UI loading, folding, and continued execution. User confirmation of folding does not prove continued agent execution.
