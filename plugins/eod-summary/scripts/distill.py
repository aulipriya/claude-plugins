#!/usr/bin/env python3
"""Distill one Claude Code transcript into a compact, readable digest for a single day.

Raw transcripts run 8-30 MB because tool *results* dominate the bytes while carrying
almost none of the meaning. This keeps user/assistant prose and reduces each tool call to
a one-line label, which measures ~400:1 compression on real sessions.

Usage:
    distill.py <transcript.jsonl> [YYYY-MM-DD] [--max-chars N]

Writes the digest to stdout and a one-line size report to stderr.
"""

import json
import os
import sys

MAX_CHARS = 4000          # per message; long tool-dump pastes are not worth the tokens
MAX_LABEL = 200           # per tool-call label
SKIP_PREFIXES = ('<system-reminder', '<local-command', '<command-name',
                 '<command-message', '<user-memory-input')


def _label(name, inp):
    """Reduce a tool call to one short line: what it was, on what."""
    if not isinstance(inp, dict):
        return f"[tool {name}]"
    for key in ('description', 'file_path', 'pattern', 'command', 'prompt', 'query', 'url'):
        val = inp.get(key)
        if val:
            return f"[tool {name}] {str(val)[:MAX_LABEL]}"
    return f"[tool {name}]"


def distill(path, day=None, max_chars=MAX_CHARS):
    """Return the digest text for one transcript, restricted to `day` if given."""
    out = []
    with open(path, errors='replace') as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get('timestamp') or ''
            if day and not ts.startswith(day):
                continue
            if d.get('isMeta'):
                continue
            # Note: do NOT filter on isSidechain. Subagent transcripts are entirely
            # sidechain lines, and main transcripts contain none, so filtering here
            # empties every subagent digest without removing anything from a main one.
            msg = d.get('message') or {}
            role = msg.get('role')
            if role not in ('user', 'assistant'):
                continue
            content = msg.get('content')
            parts = []
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get('type')
                    if btype == 'text':
                        parts.append(b.get('text') or '')
                    elif btype == 'tool_use':
                        parts.append(_label(b.get('name'), b.get('input')))
                    # tool_result and thinking are dropped on purpose
            txt = '\n'.join(p for p in parts if p).strip()
            if not txt or txt.startswith(SKIP_PREFIXES):
                continue
            out.append(f"### {role} {ts[11:19]}\n{txt[:max_chars]}")
    return '\n\n'.join(out)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    flags = [a for a in argv[1:] if a.startswith('--')]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    path = args[0]
    day = args[1] if len(args) > 1 else None
    max_chars = MAX_CHARS
    for f in flags:
        if f.startswith('--max-chars='):
            max_chars = int(f.split('=', 1)[1])

    text = distill(path, day, max_chars)
    src_mb = os.path.getsize(path) / 1e6
    print(f"{os.path.basename(path)}: {src_mb:.1f}MB -> {len(text)/1e3:.1f}KB "
          f"(~{len(text)//4} tok)", file=sys.stderr)
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
