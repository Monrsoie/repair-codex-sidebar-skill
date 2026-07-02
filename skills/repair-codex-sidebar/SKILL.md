---
name: repair-codex-sidebar
description: Recover Codex Desktop sidebar threads, conversations, history items, and local project groups after copying .codex_old, Windows/WSL path mismatches, SQLite state repairs, or cases where restored threads appear only under general chats. Use when Codex needs to diagnose or repair missing sidebar conversations, local project conversation history, state_5.sqlite thread records, .codex-global-state.json project roots and labels, active-workspace-roots, projectless-thread-ids, session_index.jsonl, or sessions/*.jsonl session_meta cwd values.
---

# Repair Codex Sidebar

Use this skill to recover Codex Desktop sidebar conversations when threads exist on disk but are missing from the sidebar, appear only under general chats, or do not group under local projects. It covers both full history/index repair and the lighter second-stage global-state repair.

## Safety Rules

- Close all Codex Desktop windows before making changes.
- Always create a backup of the current Codex home before writing.
- Do not replace `state_5.sqlite` wholesale unless the user explicitly asks and accepts the risk.
- Do not copy `auth.json`, `installation_id`, `cap_sid`, or `state_5.sqlite*` from an old directory by default.
- Prefer repairing indexes and metadata over deleting caches or resetting the app.
- Preserve user conversation JSONL contents. Only update metadata fields such as `session_meta.cwd` and `thread_source`.
- If only `.codex-global-state.json` needs repair, prefer `--global-state-only` before touching SQLite or session JSONL files.

## Quick Start

Use the bundled repair script:

```powershell
python scripts/repair_codex_sidebar.py
```

Common explicit form:

```powershell
python scripts/repair_codex_sidebar.py --codex-home "$env:USERPROFILE\.codex" --old-codex-home "$env:USERPROFILE\.codex_old"
```

If Codex is still running, stop and ask the user to close it. Only pass `--allow-running-codex` when you are certain the app is not using the target Codex home.

If threads were restored but still do not appear under the expected sidebar project groups, run the lightweight path:

```powershell
python scripts/repair_codex_sidebar.py --global-state-only
```

If the project roots themselves are missing, pass known roots explicitly with `--project-root`, or use `--include-hinted-roots` to add roots found in `thread-workspace-root-hints`. Pair that with `--exclude-root-prefix` when recovery workspaces or temporary agent folders should not become sidebar projects.

If `thread-workspace-root-hints` is empty but `state_5.sqlite` is healthy, add `--rebuild-hints-from-state-db`. This reads active thread rows from SQLite and rebuilds global-state hints without writing SQLite.

If the current global-state file is nearly empty after a crash or reset, add `--seed-roots-from-backups` to recover saved project roots from the global-state backup with the largest `electron-saved-workspace-roots` list.

If Codex keeps rewriting `.codex-global-state.json` from memory, run a short loop while the user fully quits and reopens Codex:

```powershell
python scripts/repair_codex_sidebar.py --global-state-only --allow-running-codex --watch-minutes 30 --watch-interval-seconds 1
```

## What The Script Repairs

The sidebar can depend on several stores at once. Repair all of them together:

1. `sessions/**/*.jsonl`: conversation bodies and first-line `session_meta`.
2. `session_index.jsonl`: lightweight conversation index.
3. `.codex-global-state.json`: project list, ordering, projectless ids, and `thread-workspace-root-hints`.
4. `state_5.sqlite`: thread rows, cwd, archive status, source, thread_source, and user-event flags.

The script:

- Backs up the current Codex home.
- Copies old user data directories from `.codex_old` when present.
- Merges `session_index.jsonl`.
- Merges global state while disabling `runCodexInWindowsSubsystemForLinux`.
- Imports old `state_5.sqlite` thread-side data when schemas match, excluding `_sqlx_migrations`.
- Normalizes thread cwd and session metadata paths to Windows extended paths like `\\?\C:\Users\...`.
- Sets `has_user_event=1` for ordinary user threads with `first_user_message`.
- Sets missing `thread_source` to `user` for ordinary user threads.
- Rebuilds `thread-workspace-root-hints` from active user thread rows.
- Ensures `active-workspace-roots` is an array, because affected Desktop builds ignore a scalar string value.
- Rebuilds `electron-workspace-root-labels` so restored project roots have sidebar display names.
- Rebuilds `project-order` and removes project-backed thread ids from `projectless-thread-ids`.

## Diagnostic Checks

After repair, verify these counts:

```powershell
python scripts/repair_codex_sidebar.py --diagnose-only
```

Healthy signs:

- `visible_user_threads` is greater than zero.
- `active_project_roots` includes the expected project folders.
- `active_workspace_roots_type` is `list`.
- `workspace_root_labels` is greater than zero when project roots exist.
- `session_meta_checked` is greater than zero.
- `session_meta_changed` is zero on a second run.

If the sidebar still does not show conversations, inspect whether Codex rewrote any path format on launch. Re-run the script after closing Codex, then compare `state_5.sqlite` `threads.cwd` and the first `session_meta.cwd` in affected JSONL files.

## Recovery

Every write run prints a backup directory named like:

```text
C:\Users\<user>\.codex_sidebar_repair_backup_<timestamp>
```

To roll back, close Codex and restore files from that backup. Prefer restoring only the changed files first: `.codex-global-state.json`, `session_index.jsonl`, `state_5.sqlite*`, and `sessions/`.
