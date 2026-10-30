# Local Codex history cleanup workflow

## Proven case and limits

On 2026-10-30, a user confirmed successful UI display and folding after the manual v4 repair. Starting further engineering work from that copy was not tested. The automated script still requires UI acceptance on each new output.

Observed environment: Windows, Codex Desktop 26.1027.30824. Inspect current schemas before reuse. Preserve unrelated rows and runtime settings. Do not restart the app or stop other chats merely to test a copy.

## Snapshot

Resolve `threads.rollout_path` from a read-only connection to `state_5.sqlite`, plus all ancestors referenced by session metadata. Record the selected title, ID and active state using app tools. Use direct file copying for an independent backup; a fork can retain `forked_from_id` or `history_base` dependencies and is not evidence of independence.

Keep immutable source snapshots and a separate transformation candidate. Hash copied files and compare with the source after copying. Read live databases using SQLite read-only connections; use the backup API for coherent individual database snapshots. Separate snapshots of records and databases are not an atomic system snapshot. Prefer a stopped source; if it is running, disclose snapshot limitations. Use durable storage for retained backups. Temporary directories in this case were a workaround for a failed workspace write, not a retention policy.

Use a durable backup directory outside your published repository. Do not upload session backups or manifests.

## Materialize history

Session metadata can include `history_mode: paginated` and `history_base` with `thread_id`, `end_ordinal_exclusive`, and `end_byte_offset`. Ancestor segment filenames may contain both the public session ID and an internal segment ID. Resolve the referenced ID exactly; detect missing ancestors or cycles.

Decompress `.jsonl.zst` before interpreting decompressed byte cutoffs. Walk the inheritance chain in chronological order and include each ancestor only up to the inherited cutoff. Check ordinal semantics and cutoff alignment against current records. Include the newest selected segment once. Retain one session metadata record, assign a fresh UUID, and remove inheritance/fork dependencies from the new standalone metadata. Remap only the copy's identity and structural round references; preserve tool receiver IDs and historical project paths as evidence.

The first independent experiment found 41 capacity-error completion events in the effective chain versus 44 across all untrimmed segments. The distinction matters: raw matching files include records outside inherited cutoffs.

## Define rounds

A genuine final model answer closes a round. `AgentMessage.phase == final_answer` alone is insufficient: async user-input requests were also encoded this way. In this case, exclude items with `delivery == async` or nonempty `questions`; preserve them as intermediate messages and preserve their question payloads. Use current schema evidence to identify any equivalent variants. Maintain consistency with matching response items, metadata and IDs.

Keep all intermediate user replies, progress messages, tool calls/results, file changes and reasoning summaries in the round ending at the next genuine final answer. A clarification request does not itself finish the working round. Preserve content and order. Remap `turn_id`, `root_turn_id`, turn attribution, relevant context metadata and index rows consistently. Do not recursively overwrite unrelated nested tool-result data just because it contains a similarly named key.

Remove obsolete task-start/task-end/abort boundaries inside a merged round. Emit a valid start and completion boundary for the resulting round, preserving required fields from a current valid record. Leave a substantive tail without a final answer unfinished; do not invent an answer or a success claim. Ignore non-display bookkeeping-only tails when appropriate after verifying their contents.

Clean explicit 429 / at-capacity error events or error-display fields. Do not globally remove the substring `429`: it occurs in UUIDs, quantities, commands and legitimate text. Keep substantive messages mentioning interruption unless separately asked to redact them. Removing an error field does not mean the underlying task succeeded; record transformations in a manifest.

In this case: 139 nominal `final_answer` items included 87 async questions. Correct grouping produced 52 completed rounds plus a bookkeeping tail, represented as 53 indexed rounds in v4.

## Timing and folding

Derive elapsed time from persisted timestamps only when both endpoints are valid and ordered. Treat Unix seconds, milliseconds and ISO timestamps explicitly. Cross-day merged work may have a long wall-clock duration; do not label it model compute time. If timing is unavailable, preserve null/absent timing according to the current schema. The user observed both “用时 n 秒” and “上 n 条消息” UI forms. No supported storage field to force the latter was established. Do not promise a particular label or invent a duration to trigger folding.

An intervening diff card can indicate a remaining round boundary, but diff cards alone do not prove misgrouping. Inspect the file-change item's round and the eventual final answer's round. In this case an async question had incorrectly split those records.

## Record and index contract

Every paginated non-metadata record needs a correctly ordered `ordinal`; preserve the numbering convention observed in current valid records. Never retain stale ordinals after inserting/deleting boundaries. Compute byte offsets using the actual UTF-8 bytes written, including newline bytes, not character counts.

Observed tables in `thread_history_1.sqlite`:

- `thread_turns`: session/round IDs, start ordinal, status, error, start/end/duration, first user item, final agent item, start/end byte offsets and ordinals, root round ID.
- `thread_items`: session/round/item IDs, ordinal, creation time, serialized UI item, item type and optional timing/update ordinal.
- `thread_history_projection_state`: session ID, next byte offset, next ordinal.
- `thread_realtime_items`: separate realtime items when present.

Inspect all schemas and source indices before implementing. Do not infer API/UI item JSON by merely lowercasing raw event types. Either let a verified materializer rebuild the copy consistently or build all necessary copy-only projection rows using the current schema and validated UI item shapes. An existing experimental projection may supply item shapes, but verify round IDs, item ordinals and timing against the newly written candidate. Fields omitted in the historical repair should not become a reusable default.

Register the new ID and file in `state_5.sqlite` only after offline validation. Use explicit-column, parameterized transactions scoped to the new ID. Preserve source settings needed for reading; clear inherited parent linkage and stale indexing state. Session registration and history projection are separate operations; coordinate them and roll back/delete only newly created rows on failure. Avoid editing a candidate while the app has it loaded: use a new copy or unload it through a supported operation. Never stop the original as a side effect.

## Failure diagnosis learned here

- Load error: `final paginated rollout record ... is missing an ordinal`. Newly synthesized boundary events lacked ordinals. Numbering must include new events, not just retained events.
- Blank page: 28,950 item rows existed but zero `thread_turns`. The UI had nothing to page as rounds. Rebuilding round indices made app-backed history reads return content.
- Logs also showed duplicate/regressed ordinals, skipped ranges, invalid trailing content, and stale projection byte offsets after file rewrites. Fix the whole record/index contract rather than patching only the last reported error.
- `notLoaded` with an empty `turns` result is not a successful load. A shell deep-link launch returning exit code zero is not proof the requested chat was opened.

For logs, inspect `logs_2.sqlite` read-only and select a bounded range around the copy ID. Useful terms: `thread/resume`, `thread_history_materialization`, `ordinal`, `projection`, `deserialize`, `Failed to create session`. Avoid dumping unrelated conversations or credentials.

## Acceptance

1. Offline: all JSONL parses; inheritance is absent; ordinals and byte offsets match; unique IDs and valid associations; genuine final-answer count matches completed rounds; async question content survives; unfinished work remains unfinished; source hashes/rows unchanged except independent app activity.
2. Backend: `read_thread` returns real rounds, messages, commands and final answers. Check early, middle and last pages and ensure the expected records are present. Verify the previously split diff and final answer share a round.
3. UI: open the exact copy by title/ID, verify nonblank history, expand/collapse at least an early and latest round and the previously broken example. User observation is acceptable evidence when direct UI inspection is unavailable.
4. Report UI acceptance separately from ability to resume execution. Do not start project work merely to prove readability.

Keep an immutable backup, a manifest of counts and mappings, and a copy-only rollback route. If importing fails, inspect evidence and repair the independent candidate; do not redirect modifications to the source.
