# claude-plugins

A personal collection of [Claude Code](https://claude.com/claude-code) plugins, served as a self-hosted plugin marketplace.

## Installation

### 1. Add this marketplace (once)

In any Claude Code session, run:

```
/plugin marketplace add aulipriya/claude-plugins
```

This registers the marketplace under the name `aulipriya-plugins`.

### 2. Install a plugin

```
/plugin install <plugin-name>@aulipriya-plugins
```

For example:

```
/plugin install google-docstring@aulipriya-plugins
```

Then restart the CLI (or run `/reload-plugins`) so the plugin's skills are picked up.

### Managing plugins

- `/plugin` — browse installed plugins and marketplaces interactively
- `/plugin marketplace update aulipriya-plugins` — pull the latest plugin versions
- `/plugin uninstall <plugin-name>@aulipriya-plugins` — remove a plugin

## Plugins

### `google-docstring`

Ensures every function/method in a Python file has a correct Google-style docstring. Two things make it different from most docstring tools:

- **Caller-grep type inference** — argument types are taken from what the top two real call sites actually pass in, not from stale annotations or generic guesses.
- **`--check` surgical-fix mode** — repairs docstrings that are already Google-style but have wrong types, stale arg lists, or missing sections, instead of rewriting them from scratch.

#### Usage

```
/google-docstring <file_path> [function_name] [--check]
```

- `<file_path>` (required): a `.py` file.
- `[function_name]` (optional): restrict to one function.
- `[--check]` (optional): also fix mistakes in docstrings that are already Google-style.

#### Examples

Generate missing docstrings across a file:

```
/google-docstring src/api/routes.py
```

Convert Sphinx/NumPy/prose docstrings in one function to Google style:

```
/google-docstring src/utils/parser.py parse_config
```

Fix an existing Google-style docstring whose types have drifted:

```
/google-docstring src/api/routes.py --check
```

#### How it works

Types are inferred from real call sites: for each function, the tool greps for the top two invocations and reads what the caller actually passes in. That's usually more accurate than trusting whatever annotation happens to be on the parameter, especially in codebases where annotations lag behind reality. Module docstrings are left untouched. Non-`.py` files are refused outright.

### `eod-summary`

Writes an end-of-day work summary and publishes it as a Google Doc. It reconstructs the day from up to **four** sources — two always on, two opt-in — which is what makes it different from a git-log-to-markdown script:

- **Git activity** — commits and working-tree changes across every repo under `~/Documents`.
- **Claude Code session transcripts** — the day's sessions, distilled off disk. This is the layer that captures exploration, measurements, and decisions that never produced a commit.
- **Chrome history** *(opt-in, `--browser`)* — which sites were worked in that day: ticket keys, meetings, consoles, dashboards. Used only to name work items; the report never lists browsing.
- **A Google Drive folder** *(opt-in, `--drive-folder NAME`)* — files updated that day anywhere in that folder's tree.

The report reads like your own end-of-day notes for self-review: a `Wins` section first (the day's 2–4 biggest achievements), then a few casual, notebook-style bullets per project, and a short "For tomorrow" list of loose ends. It's brief (200–350 words) and about what you achieved — not a log of what the assistant did. No session or thread counts, no run statistics.

#### Usage

```
/eod-summary [--date YYYY-MM-DD] [--path DIR] [--dry-run] [--no-sessions] [--max-sessions N]
             [--browser] [--browser-profile NAME] [--open-tabs]
             [--drive-folder NAME]
```

- `--date` (default: today) — rebuild any past day; every source is history.
- `--path` (default: `~/Documents`) — root to scan for repos, and the filter for which sessions count.
- `--dry-run` — print the summary in chat, don't create the doc.
- `--no-sessions` — git layer only; fast and cheap.
- `--max-sessions` (default: 10) — cap on how many sessions get summarized.
- `--browser` — include Chrome history (off by default). `--browser-profile NAME` limits it to one profile (handy when another profile is personal). `--open-tabs` also reads the tabs open right now; macOS will ask you to allow your terminal to control Chrome the first time. Either implies `--browser`.
  Only the day's hosts, page titles, ticket keys and meeting titles are read from Chrome's local History file; query strings and e-mail addresses are stripped, and personal and auth hosts are excluded, before anything leaves the script.
- `--drive-folder NAME` — include files updated that day in the named Google Drive folder (off by default; no default folder).

It also triggers conversationally — "I'm done for today", "wrap up my day".

#### Examples

```
/eod-summary --dry-run
/eod-summary --date 2026-09-02
/eod-summary --path ~/code --no-sessions
/eod-summary --browser --drive-folder "Team Docs"
```

#### How it works

`scripts/discover.py` finds the day's active repos (a commit, or a file whose mtime is that day) and the day's session transcripts, grouped by working directory and including each session's subagents. `scripts/distill.py` then compresses each transcript: user and assistant prose is kept, every tool call is reduced to a one-line label, and tool *results* — which are the bulk of the bytes and almost none of the meaning — are dropped. That runs about 400:1 in practice; a 24 MB transcript becomes roughly 14k tokens.

`scripts/browser.py` copies each Chrome profile's History database (Chrome keeps the live one locked) and aggregates the day's visits by host, pulling out Jira-style issue keys and Google Meet titles. Query strings and e-mail addresses are stripped before anything leaves the script, and personal and auth hosts are excluded by default. The Drive layer runs through the Drive connector: one search for the day's modified files, then a parent walk to keep only those inside the target folder.

One subagent then summarizes each session from its digest, and the merge step folds those reports together with the git, browser and Drive layers, deduplicating work that shows up in more than one. A privacy pass strips credential-shaped strings, unrelated private paths, and anything from the browser layer that is not unambiguously work before the doc is created.

**Requires** the Google Drive connector for publishing (`--dry-run` works without it). The connector has no update/edit tool, so it creates one dated doc per day rather than appending to a running one.

## License

MIT — see [LICENSE](./LICENSE).