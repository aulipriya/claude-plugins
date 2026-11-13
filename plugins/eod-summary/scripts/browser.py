#!/usr/bin/env python3
"""Which sites were worked in on one day, from Chrome's on-disk history.

Reads every Chrome profile's History database (copied first — Chrome holds a lock), keeps
the visits that fall inside the local calendar day, and aggregates them by host. Emits one
JSON object on stdout:

    {
      "date": "2026-09-03",
      "profiles": [ {dir, name, account, visits} ... ],   # account = "@domain" only
      "hosts":    [ {host, visits, profile, titles[], paths[]} ... ],   # busiest first
      "issue_keys": ["PROJ-547", ...],          # Jira-style keys seen in URLs or titles
      "jira_projects": ["PROJ"],                # project keys from Jira board/project URLs
      "meetings":   ["Weekly Check-In"],         # Google Meet tab titles
      "open_tabs":  [ {host, title} ... ] | null,   # only with --open-tabs
      "stats":    {visits, hosts, excluded_visits, profiles_read}
    }

Privacy: URL query strings are never emitted (they can carry tokens); e-mail addresses are
redacted from titles; a default list of personal/auth hosts is excluded. The consumer must
still treat this as sensitive context — see SKILL.md: the report names work items, never
browsing history.

Usage:
    browser.py [--date YYYY-MM-DD] [--profile NAME_OR_DIR] [--exclude host,host]
               [--open-tabs] [--history PATH]
"""

import datetime
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

CHROME_DIR = os.path.expanduser('~/Library/Application Support/Google/Chrome')
CHROME_EPOCH_OFFSET = 11644473600          # seconds between 1601-01-01 and 1970-01-01
MAX_TITLES_PER_HOST = 8
MAX_PATHS_PER_HOST = 5
MAX_HOSTS = 40

# Noise and personal traffic that never belongs in a work report. Matched on host suffix.
DEFAULT_EXCLUDE = {
    'youtube.com', 'facebook.com', 'instagram.com', 'x.com', 'twitter.com', 'reddit.com',
    'netflix.com', 'tiktok.com', 'linkedin.com', 'whatsapp.com', 'messenger.com',
    'www.google.com', 'accounts.google.com', 'mail.google.com', 'keep.google.com',
    'signin.aws.amazon.com', 'login.microsoftonline.com', 'newtab', 'chrome',
}

EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
ISSUE_RE = re.compile(r'\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b')
JIRA_PROJECT_RE = re.compile(r'atlassian\.net/jira/[^?#]*?/projects/([A-Z][A-Z0-9]{1,9})\b')
ISSUE_FALSE_POSITIVES = {'UTF-8', 'ISO-8859', 'SHA-256', 'SHA-1', 'MD-5', 'COVID-19', 'GMT-6'}


def _redact(text):
    return EMAIL_RE.sub('<email>', text or '')


def _host(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return ''
    if parts.scheme in ('chrome', 'chrome-extension', 'devtools', 'about', 'file'):
        return parts.scheme
    host = parts.hostname or ''
    if parts.port and parts.port not in (80, 443):
        host = f'{host}:{parts.port}'
    return host


def _excluded(host, exclude):
    bare = host.split(':')[0]
    return any(bare == e or bare.endswith('.' + e) for e in exclude)


def _profiles(chrome_dir, only=None):
    """Yield (dir_name, profile_name, email, history_path) for each Chrome profile."""
    for hist in sorted(glob.glob(os.path.join(chrome_dir, '*', 'History'))):
        d = os.path.dirname(hist)
        dir_name = os.path.basename(d)
        name, email = dir_name, ''
        try:
            with open(os.path.join(d, 'Preferences')) as fh:
                prefs = json.load(fh)
            name = (prefs.get('profile') or {}).get('name') or dir_name
            info = prefs.get('account_info') or []
            email = info[0].get('email', '') if info else ''
        except Exception:
            pass
        if only and only not in (dir_name, name, email):
            continue
        # The account domain is enough to tell a work profile from a personal one, and is
        # all that leaves this script; profile display names are often identical.
        account = '@' + email.split('@', 1)[1] if '@' in email else ''
        label = f'{dir_name} ({account})' if account else dir_name
        yield dir_name, name, account, label, hist


def _day_window_chrome(day):
    start = datetime.datetime.fromisoformat(day).astimezone()      # local midnight
    end = start + datetime.timedelta(days=1)
    to_chrome = lambda dt: int((dt.timestamp() + CHROME_EPOCH_OFFSET) * 1_000_000)
    return to_chrome(start), to_chrome(end)


def read_history(hist_path, day):
    """Return [(url, title)] for every visit on `day`, most-recent first."""
    lo, hi = _day_window_chrome(day)
    tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
    tmp.close()
    try:
        shutil.copyfile(hist_path, tmp.name)          # Chrome keeps the live DB locked
        con = sqlite3.connect(f'file:{tmp.name}?mode=ro', uri=True)
        rows = con.execute(
            'SELECT u.url, u.title FROM visits v JOIN urls u ON u.id = v.url '
            'WHERE v.visit_time >= ? AND v.visit_time < ? ORDER BY v.visit_time DESC',
            (lo, hi)).fetchall()
        con.close()
        return rows
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def open_tabs():
    """Currently open tabs via AppleScript; needs Automation permission for the terminal."""
    script = ('tell application "Google Chrome"\n'
              ' set out to ""\n'
              ' repeat with w in windows\n'
              '  repeat with t in tabs of w\n'
              '   set out to out & (URL of t) & "\t" & (title of t) & "\n"\n'
              '  end repeat\n'
              ' end repeat\n'
              ' return out\n'
              'end tell')
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True,
                           timeout=15)
    except Exception as exc:                       # osascript missing, timeout
        return None, str(exc)
    if r.returncode != 0:
        err = r.stderr.strip()
        if '-1743' in err:
            err += ' — grant your terminal access to Google Chrome under System Settings ' \
                   '> Privacy & Security > Automation'
        return None, err
    tabs = []
    for line in r.stdout.splitlines():
        url, _, title = line.partition('\t')
        if url:
            tabs.append({'host': _host(url), 'title': _redact(title)[:120]})
    return tabs, None


def main(argv):
    day = datetime.date.today().isoformat()
    only, want_tabs, hist_override = None, False, None
    exclude = set(DEFAULT_EXCLUDE)

    it = iter(argv[1:])
    for a in it:
        if a == '--date':
            day = next(it)
        elif a == '--profile':
            only = next(it)
        elif a == '--exclude':
            exclude |= {h.strip() for h in next(it).split(',') if h.strip()}
        elif a == '--open-tabs':
            want_tabs = True
        elif a == '--history':
            hist_override = next(it)
        else:
            print(f'unknown argument: {a}\n{__doc__}', file=sys.stderr)
            return 2

    if hist_override:
        d = os.path.basename(os.path.dirname(hist_override))
        profiles = [('custom', d, '', d, hist_override)]
    else:
        profiles = list(_profiles(CHROME_DIR, only))

    hosts = {}
    prof_out = []
    excluded_visits = 0
    issue_keys, jira_projects, meetings = set(), set(), set()

    for dir_name, name, account, label, hist in profiles:
        try:
            rows = read_history(hist, day)
        except Exception as exc:
            print(f'{dir_name}: could not read history: {exc}', file=sys.stderr)
            continue
        prof_out.append({'dir': dir_name, 'name': name, 'account': account,
                         'visits': len(rows)})
        for url, title in rows:
            host = _host(url)
            if not host or _excluded(host, exclude):
                excluded_visits += 1
                continue
            title = _redact(title).strip()
            path = urlsplit(url).path[:80] if '://' in url else ''
            h = hosts.setdefault(host, {'host': host, 'visits': 0, 'profile': label,
                                        '_titles': {}, '_paths': {}})
            h['visits'] += 1
            if title:
                h['_titles'][title] = h['_titles'].get(title, 0) + 1
            if path and path != '/':
                h['_paths'][path] = h['_paths'].get(path, 0) + 1
            for m in ISSUE_RE.findall(f'{url} {title}'):
                if m not in ISSUE_FALSE_POSITIVES:
                    issue_keys.add(m)
            jira_projects.update(JIRA_PROJECT_RE.findall(url))
            if host.endswith('meet.google.com') and title.startswith('Meet - '):
                meetings.add(title[len('Meet - '):])

    out_hosts = []
    for h in sorted(hosts.values(), key=lambda x: -x['visits'])[:MAX_HOSTS]:
        top = lambda d, n: [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:n]]
        out_hosts.append({'host': h['host'], 'visits': h['visits'], 'profile': h['profile'],
                          'titles': top(h['_titles'], MAX_TITLES_PER_HOST),
                          'paths': top(h['_paths'], MAX_PATHS_PER_HOST)})

    tabs, tabs_err = (open_tabs() if want_tabs else (None, None))

    json.dump({
        'date': day,
        'profiles': prof_out,
        'hosts': out_hosts,
        'issue_keys': sorted(issue_keys),
        'jira_projects': sorted(jira_projects),
        'meetings': sorted(meetings),
        'open_tabs': tabs,
        'open_tabs_error': tabs_err,
        'stats': {
            'visits': sum(p['visits'] for p in prof_out),
            'hosts': len(hosts),
            'excluded_visits': excluded_visits,
            'profiles_read': len(prof_out),
        },
    }, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))