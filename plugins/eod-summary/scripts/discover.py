#!/usr/bin/env python3
"""Find everything that happened on one day: git activity + Claude Code sessions.

Emits a single JSON object on stdout:

    {
      "date": "2026-09-02",
      "root": "/Users/me/Documents",
      "repos":    [ {name, path, branch, commits[], dirty[], touched_today} ... ],
      "sessions": [ {id, cwd, project, transcript, messages, first, last,
                     subagents[{path, agent_type, description}]} ... ],
      "stats":    {repos_scanned, repos_active, sessions_found, sessions_capped}
    }

Usage:
    discover.py [--date YYYY-MM-DD] [--path ROOT] [--max-sessions N]
                [--no-git] [--no-sessions]
"""

import datetime
import glob
import json
import os
import subprocess
import sys

MAX_DEPTH = 4             # how deep under ROOT to look for .git
MAX_SESSIONS = 10         # cap; a runaway day should not blow the token budget
MAX_STALE_DIRTY = 40      # WIP not touched on the day is listed only as background
PROJECTS = os.path.expanduser('~/.claude/projects')
PRUNE = {'node_modules', '.venv', 'venv', '.tox', 'site-packages', 'vendor'}


# --------------------------------------------------------------------------- git

def _git(repo, *args):
    """Run a read-only git command in `repo`; return stdout, or '' on failure."""
    try:
        r = subprocess.run(('git', '-C', repo) + args, capture_output=True,
                           text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        return ''


def find_repos(root):
    """Return repo roots under `root`, skipping vendored checkouts."""
    repos = []
    root = os.path.abspath(os.path.expanduser(root))
    base_depth = root.rstrip('/').count('/')
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE and not d.startswith('.git')]
        if dirpath.count('/') - base_depth >= MAX_DEPTH:
            dirnames[:] = []
            continue
        if os.path.isdir(os.path.join(dirpath, '.git')):
            repos.append(dirpath)
            dirnames[:] = []          # don't descend into a repo looking for more
    return sorted(repos)


def repo_activity(repo, day):
    """Collect one repo's commits and working-tree state for `day`."""
    since, until = f'{day} 00:00:00', f'{day} 23:59:59'
    email = _git(repo, 'config', 'user.email')
    log_args = ['log', f'--since={since}', f'--until={until}',
                '--pretty=format:\x01%h\x1f%s\x1f%an', '--numstat']
    if email:
        log_args.append(f'--author={email}')

    commits, cur = [], None
    for line in _git(repo, *log_args).splitlines():
        if line.startswith('\x01'):
            h, subject, author = (line[1:].split('\x1f') + ['', ''])[:3]
            cur = {'sha': h, 'subject': subject, 'author': author,
                   'files': [], 'added': 0, 'deleted': 0}
            commits.append(cur)
        elif line.strip() and cur is not None:
            bits = line.split('\t')
            if len(bits) == 3:
                add, dele, path = bits
                cur['files'].append(path)
                cur['added'] += int(add) if add.isdigit() else 0
                cur['deleted'] += int(dele) if dele.isdigit() else 0

    # Working-tree changes, flagged by whether the file was actually touched on `day`.
    # -uall is required: the default collapses untracked dirs to one entry whose mtime is
    # the directory's, which hides files edited inside it today.
    today_files, other_files = [], []
    for line in _git(repo, 'status', '--porcelain', '-uall').splitlines():
        status, path = line[:2], line[3:]
        path = path.split(' -> ')[-1].strip('"')
        full = os.path.join(repo, path)
        try:
            mtime_day = datetime.date.fromtimestamp(os.path.getmtime(full)).isoformat()
        except OSError:
            mtime_day = None
        entry = {'status': status.strip(), 'path': path,
                 'modified_on_day': mtime_day == day}
        (today_files if entry['modified_on_day'] else other_files).append(entry)

    # Today's files always survive; stale WIP is capped so a repo full of untracked
    # build output can't flood the report.
    dirty = today_files + other_files[:MAX_STALE_DIRTY]
    stale_omitted = max(0, len(other_files) - MAX_STALE_DIRTY)

    return {
        'name': os.path.basename(repo),
        'path': repo,
        'branch': _git(repo, 'rev-parse', '--abbrev-ref', 'HEAD'),
        'email': email,
        'commits': commits,
        'dirty': dirty,
        'stale_dirty_omitted': stale_omitted,
        # "active" means real work on this day, not a week-old pile of WIP
        'touched_today': bool(commits) or bool(today_files),
    }


# ----------------------------------------------------------------------- sessions

def _day_start_ts(day):
    y, m, d = (int(x) for x in day.split('-'))
    return datetime.datetime(y, m, d).timestamp()


def find_sessions(day, root=None, cap=MAX_SESSIONS):
    """Return the day's session transcripts, newest first, grouped data included."""
    marker = f'"timestamp":"{day}'.encode()
    day_floor = _day_start_ts(day)
    root = os.path.abspath(os.path.expanduser(root)) if root else None
    found = []

    for path in glob.glob(os.path.join(PROJECTS, '*', '*.jsonl')):
        try:
            if os.path.getmtime(path) < day_floor:
                continue          # append-only: can't hold that day's lines
        except OSError:
            continue
        try:
            with open(path, 'rb') as fh:
                if marker not in fh.read():
                    continue
        except OSError:
            continue

        cwd, first, last, count = None, None, None, 0
        with open(path, errors='replace') as fh:
            for line in fh:
                if cwd is None and '"cwd"' in line:
                    try:
                        cwd = json.loads(line).get('cwd')
                    except Exception:
                        pass
                if f'"timestamp":"{day}' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if (d.get('message') or {}).get('role') not in ('user', 'assistant'):
                    continue
                ts = d.get('timestamp') or ''
                if not ts.startswith(day):
                    continue      # the marker hit was a nested timestamp, not this line's
                first = first or ts
                last = ts
                count += 1
        if not count:
            continue              # marker hit was a snapshot, not real conversation
        if root and cwd and not os.path.abspath(cwd).startswith(root):
            continue

        sid = os.path.basename(path)[:-6]
        subagents = []
        for sub in sorted(glob.glob(os.path.join(os.path.dirname(path), sid,
                                                 'subagents', '*.jsonl'))):
            meta = {}
            try:
                with open(sub[:-6] + '.meta.json') as fh:
                    meta = json.load(fh)
            except Exception:
                pass
            subagents.append({'path': sub,
                              'agent_type': meta.get('agentType', ''),
                              'description': meta.get('description', '')})

        found.append({
            'id': sid,
            'cwd': cwd or '?',
            'project': os.path.basename(cwd) if cwd else '?',
            'transcript': path,
            'messages': count,
            'first': first,
            'last': last,
            'subagents': subagents,
        })

    found.sort(key=lambda s: s['messages'], reverse=True)
    return found[:cap], len(found)


# --------------------------------------------------------------------------- main

def main(argv):
    day = datetime.date.today().isoformat()
    root, cap = '~/Documents', MAX_SESSIONS
    do_git = do_sessions = True

    it = iter(argv[1:])
    for a in it:
        if a == '--date':
            day = next(it)
        elif a == '--path':
            root = next(it)
        elif a == '--max-sessions':
            cap = int(next(it))
        elif a == '--no-git':
            do_git = False
        elif a == '--no-sessions':
            do_sessions = False
        else:
            print(f'unknown argument: {a}\n{__doc__}', file=sys.stderr)
            return 2

    repos, scanned = [], []
    if do_git:
        scanned = find_repos(root)
        repos = [r for r in (repo_activity(p, day) for p in scanned) if r['touched_today']]

    sessions, total = ([], 0)
    if do_sessions:
        sessions, total = find_sessions(day, root, cap)

    json.dump({
        'date': day,
        'root': os.path.abspath(os.path.expanduser(root)),
        'repos': repos,
        'sessions': sessions,
        'stats': {
            'repos_scanned': len(scanned),
            'repos_active': len(repos),
            'sessions_found': total,
            'sessions_capped': max(0, total - len(sessions)),
        },
    }, sys.stdout, indent=2)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
