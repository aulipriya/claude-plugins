---
name: google-docstring
description: Ensure every function/method in a Python file has a correct Google-style docstring. Generates missing ones, converts Sphinx/NumPy/prose to Google style, and with `--check` fixes mistakes (wrong types, stale args, missing/extra sections) in existing Google-style docstrings. Types come from the top two caller sites via grep. Use when the user invokes `/google-docstring <file_path> [function_name] [--check]`.
---

# google-docstring

## Invocation

```
/google-docstring <file_path> [function_name] [--check]
```

- `<file_path>` (required): path to a `.py` file.
- `[function_name]` (optional): restrict to one function.
- `[--check]` (optional): also fix mistakes in docstrings that are already Google-style.

Module docstrings are not touched. Non-`.py` files: stop and tell the user.

## Per-function action

| State of existing docstring        | Default      | With `--check`        |
|------------------------------------|--------------|------------------------|
| None                               | **GENERATE** | **GENERATE**           |
| Non-Google (Sphinx/NumPy/prose)    | **CONVERT**  | **CONVERT**            |
| Google-style                       | LEAVE        | **FIX** (surgical)     |

A docstring is Google-style if it has `Args:`, `Returns:`, `Raises:`, `Yields:`, or `Attributes:` on its own line. Otherwise it's non-Google.

## Procedure

### 1. Triage

Read the file. For each `def` (or just the named one), determine its action from the table above. Capture the signature, body (for `raise`/`return` detection), and existing docstring shape.

### 2. Grep callers (mandatory for every GENERATE/CONVERT/FIX)

```bash
grep -rn --include='*.py' -E "\b<func_name>\(" <repo_root>
```

For methods, also try `\.<func_name>\(`. Take the top two distinct caller sites and read ~5 lines of context around each. If fewer than two callers exist, fall back to existing annotations, defaults, and body usage; mark unknowns as `Any`.

### 3. Infer types from callers

For each parameter, look at the value passed at the call site:
- Literals → the obvious type (`"x"` → `str`, `1` → `int`, `[a, b]` → `List[...]`, etc.).
- A `Foo(...)` call expression → `Foo`.
- A variable → its annotation if reachable, otherwise its name's apparent meaning.

Reconciling two callers: same type → use it; compatible (e.g. `str` and `Path`) → `Union`; conflicting → existing annotation, else `Any`. Caller-inferred types override what an old docstring claimed. Never invent preconditions not visible in the body.

### 4. Apply the action

**Template** (target shape for all three actions):

```python
"""<One-line imperative summary, ending with a period.>

<Optional extended description.>

Args:
    arg_name (Type): Description.
    *args: Describe collectively.
    **kwargs: Describe collectively.

Returns:
    Type: What is returned.

Raises:
    ExceptionType: When raised.
"""
```

Rules for every action:
- Summary on the same line as opening `"""`, ≤80 chars, imperative ("Create…", not "Creates…").
- Skip `self`/`cls`.
- Include `Returns:` only if the function returns non-None (or has a non-None return annotation).
- Include `Raises:` only for exceptions actually `raise`d in the body.

**GENERATE** — build the docstring from the template + caller-inferred types. Insert after the signature line with correct indentation. Do not touch the signature or body.

**CONVERT** — preserve content from the old docstring before overwriting:
- Summary → keep, reword to imperative if needed.
- Extended prose → body paragraph above `Args:`.
- Sphinx `:param name: desc` / NumPy `name : type\n    desc` / free-form param mentions → fold `desc` into the matching `Args:` entry.
- `:return:` / `Returns\n-------` → `Returns:` (drop if function returns None).
- `:raises:` / `Raises\n------` → `Raises:` (only for actually-raised types).

Types in the new docstring come from caller inference, not from the old declared types.

**FIX** — surgical edits only. Preserve summary, extended description, and custom sections (`Note:`, `Example:`, etc.). Edit only what's wrong:
- Arg missing/extra/out-of-order in `Args:` → fix to match signature order.
- Arg has no `(Type)` or wrong type → set to caller-inferred type.
- `Returns:` present but body returns None → remove. Non-None return with no `Returns:` → add.
- `Raises:` lists exceptions not raised → drop them. Body raises a type not listed → add it.

Use small `old_string`/`new_string` patches. Never overwrite the summary or description text.

### 5. Report

One block per file. Skip sections with no entries.

```
src/core/dataset_creator.py
Generated:
  - create_dataset  (line 17)
Converted:
  - _process_purposes  (line 25) — was Sphinx
Fixed:
  - _copy_batches_to_s3  (line 62)
      - added type for images_to_copy: List[Tuple[str, str, str]]
      - removed extra arg `verbose`
      - removed stale Returns: section
Left intact:
  - some_helper  (line 110)
```

Don't paste generated docstrings back in chat — the file diff is the source of truth.