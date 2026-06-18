# Recover Codex Sidebar Threads Skill

用于修复 Codex Desktop 侧边栏中丢失的线程、本地项目对话和项目分组。

如果你从 `.codex_old` 恢复过数据、在 Windows 和 WSL 之间切换过、修复过 `state_5.sqlite`，或者重建过本地历史索引，Codex Desktop 可能会出现一种很烦人的状态：侧边栏能看到项目文件夹，但每个项目都显示没有对话；或者线程恢复了，却被放进普通聊天，而不是原来的本地项目分组。

这个仓库包含的 Codex skill 位于：

```text
skills/repair-codex-sidebar
```

## 它修复什么

Codex Desktop 的侧边栏依赖多个本地状态文件和索引。如果这些文件之间不一致，就可能导致项目对话无法正确显示：

- `state_5.sqlite`
- `.codex-global-state.json`
- `session_index.jsonl`
- `sessions/**/*.jsonl` 首行里的 `session_meta.cwd`

仓库内脚本会先备份当前 Codex home，然后从 `.codex_old` 合并安全的用户数据，修复线程元数据，规范化 Windows/WSL 路径，并更新 session JSONL 元数据，让项目对话重新出现在侧边栏中。

它还包含一个轻量的 v2 修复路径，用于处理常见的第二阶段问题：线程已经恢复，但由于 `.codex-global-state.json` 里的项目索引字段陈旧或类型错误，侧边栏仍然无法把线程归入本地项目。

## 安装 Skill

把 skill 文件夹复制到 Codex skills 目录：

```powershell
Copy-Item -Recurse .\skills\repair-codex-sidebar "$env:USERPROFILE\.codex\skills\repair-codex-sidebar"
```

安装后重启 Codex。

## 手动运行

完整修复路径。运行前请先关闭所有 Codex 窗口：

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --codex-home "$env:USERPROFILE\.codex" --old-codex-home "$env:USERPROFILE\.codex_old"
```

如果线程已经恢复，但仍然没有出现在侧边栏或项目分组里，可以使用轻量的 global-state 修复：

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --codex-home "$env:USERPROFILE\.codex"
```

如果项目根目录本身缺失，可以通过 `--project-root` 显式传入，或者让脚本包含线程元数据中提示过的根目录：

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --include-hinted-roots
```

如果 Codex 在打开状态下持续覆盖修复后的状态，可以运行短时 watch 修复循环。完全退出 Codex，等待几秒后再重新打开：

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --global-state-only --allow-running-codex --watch-minutes 30 --watch-interval-seconds 1
```

只做诊断，不修改文件：

```powershell
python .\skills\repair-codex-sidebar\scripts\repair_codex_sidebar.py --diagnose-only
```

## 安全性

脚本会创建类似这样的备份目录：

```text
C:\Users\<user>\.codex_sidebar_repair_backup_<timestamp>
```

默认不会从 `.codex_old` 复制这些敏感或高风险文件：

- `auth.json`
- `installation_id`
- `cap_sid`
- `state_5.sqlite*`

轻量修复会重建或修正：

- `electron-saved-workspace-roots`
- `electron-workspace-root-labels`
- `active-workspace-roots`，确保它是数组
- `project-order`
- `projectless-thread-ids`，修复被错误标记为无项目的项目线程

## 适用人群

这个 skill 适合遇到以下问题的 Codex Desktop 用户：

- 侧边栏项目存在，但项目里没有历史对话
- 历史线程恢复了，但不在原来的本地项目分组里
- 从 `.codex_old` 恢复数据后，项目索引不一致
- Windows/WSL 路径混用后，Codex 无法识别原来的项目根目录

如果你不确定当前状态，先运行 `--diagnose-only`。
