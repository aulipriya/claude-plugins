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

## License

MIT — see [LICENSE](./LICENSE).