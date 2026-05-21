---
name: repair-codex-sidebar
description: Recover missing local Codex Desktop project conversations after copying .codex_old, Windows/WSL path mismatches, SQLite state repairs, or project sidebar entries showing "no conversations" even though session JSONL files exist. Use when Codex needs to diagnose or repair the Codex Desktop sidebar, local project conversation history, state_5.sqlite thread records, .codex-global-state.json project roots, session_index.jsonl, or sessions/*.jsonl session_meta cwd values.
---

# Repair Codex Sidebar

Use this skill to recover local Codex Desktop project conversations when the project list exists but project rows show no conversations, especially after restoring from `.codex_old`, switching between Windows and WSL, or repairing `state_5.sqlite`.

## Safety Rules

- Close all Codex Desktop windows before making changes.
- Always create a backup of the current Codex home before writing.
- Do not replace `state_5.sqlite` wholesale unless the user explicitly asks and accepts the risk.
- Do not copy `auth.json`, `installation_id`, `cap_sid`, or `state_5.sqlite*` from an old directory by default.
- Prefer repairing indexes and metadata over deleting caches or resetting the app.
- Preserve user conversation JSONL contents. Only update metadata fields such as `session_meta.cwd` and `thread_source`.

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

## Diagnostic Checks

After repair, verify these counts:

```powershell
python scripts/repair_codex_sidebar.py --diagnose-only
```

Healthy signs:

- `visible_user_threads` is greater than zero.
- `active_project_roots` includes the expected project folders.
- `session_meta_checked` is greater than zero.
- `session_meta_changed` is zero on a second run.

If the sidebar still does not show conversations, inspect whether Codex rewrote any path format on launch. Re-run the script after closing Codex, then compare `state_5.sqlite` `threads.cwd` and the first `session_meta.cwd` in affected JSONL files.

## Recovery

Every write run prints a backup directory named like:

```text
C:\Users\<user>\.codex_sidebar_repair_backup_<timestamp>
```

To roll back, close Codex and restore files from that backup. Prefer restoring only the changed files first: `.codex-global-state.json`, `session_index.jsonl`, `state_5.sqlite*`, and `sessions/`.
