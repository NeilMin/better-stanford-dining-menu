#!/usr/bin/env python3
"""Keep a GitHub issue in step with the dishes that still have no picture.

The one step of the pipeline that cannot run in CI is the one that needs a GPU,
so the nightly job's only move is to tell somebody. It files a single standing
issue: the body is the whole backlog, rewritten every night, and a comment is
added -- mentioning you, so the mail arrives under "Participating and @mentions"
whatever the repo is being watched at -- only on a night that turned up dishes
nobody has drawn yet. An edit sends no mail, which is the point: twenty new
dishes a night is normal, and a nightly ping would be read exactly as often as
a warning in a green log.

Runs after the menus are committed, like scripts/check_source.py and for the
same reason: nothing here is worth a night of data. It goes non-zero only if
GitHub itself could not be reached, because a backlog nobody was told about is
the failure this exists to prevent.

    scripts/notify_images.py --dry-run     # print the body, touch nothing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdm import pending as pendinglib  # noqa: E402


class GhError(RuntimeError):
    pass


def gh(*args: str, stdin: str | None = None) -> str:
    """One `gh` call. Raises rather than returning an error to be ignored."""
    try:
        done = subprocess.run(("gh",) + args, input=stdin, capture_output=True,
                              text=True, check=False)
    except FileNotFoundError:
        raise GhError("no `gh` on PATH -- install the GitHub CLI, or run with --dry-run")
    if done.returncode != 0:
        raise GhError(f"gh {' '.join(args)}\n{done.stderr.strip()}")
    return done.stdout


def owner() -> str | None:
    """Who to address. The repo's owner, which is who has the GPU."""
    try:
        return json.loads(gh("repo", "view", "--json", "owner"))["owner"]["login"]
    except (GhError, KeyError, ValueError):
        return None


def standing_issue() -> dict | None:
    """The backlog issue, open or closed. Newest wins; an open one wins outright."""
    found = json.loads(gh("issue", "list", "--label", pendinglib.LABEL, "--state", "all",
                          "--limit", "10", "--json", "number,state,body"))
    if not found:
        return None
    return next((i for i in found if i["state"].lower() == "open"), found[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be filed and exit without calling gh")
    ap.add_argument("--mention", help="who to cc (default: the repo owner)")
    ap.add_argument("--quiet", action="store_true",
                    help="update the body but never comment, however much is new")
    args = ap.parse_args()

    items = pendinglib.wanted(ROOT)

    if args.dry_run:
        print(pendinglib.body(items, args.mention or "you"))
        print(f"-- {len(items)} waiting" + (f": {pendinglib.tally(items)}" if items else ""))
        return 0

    try:
        mention = args.mention or owner()
        issue = standing_issue()

        if not items:
            if issue and issue["state"].lower() == "open":
                gh("issue", "close", str(issue["number"]),
                   "--comment", "Every dish on the board has a picture. 🎉")
                print(f"Closed #{issue['number']}: nothing is waiting for a picture.")
            else:
                print("Nothing is waiting for a picture.")
            return 0

        text = pendinglib.body(items, mention)

        if issue is None:
            # Created with the label, so the next run finds it by the same query
            # it would have used anyway. --force on the label, because a label
            # that already exists must not be the thing that stops the report.
            gh("label", "create", pendinglib.LABEL, "--force", "--color", "fbca04",
               "--description", "Dishes on the board with no picture yet")
            url = gh("issue", "create", "--title", pendinglib.TITLE,
                     "--label", pendinglib.LABEL, "--body-file", "-", stdin=text).strip()
            if mention:
                # Best effort: the @mention in the body is what actually sends the
                # mail, so a repo where assignment is not allowed still reports.
                try:
                    gh("issue", "edit", url, "--add-assignee", mention)
                except GhError as exc:
                    print(f"(could not assign to {mention}: {exc})")
            print(f"Filed {url}: {len(items)} waiting ({pendinglib.tally(items)}).")
            return 0

        number = str(issue["number"])
        new = [(did, e) for did, e in items if did not in pendinglib.listed(issue["body"])]
        gh("issue", "edit", number, "--body-file", "-", stdin=text)
        if issue["state"].lower() != "open":
            gh("issue", "reopen", number)
            print(f"Reopened #{number}.")

        if new and not args.quiet:
            gh("issue", "comment", number, "--body-file", "-",
               stdin=pendinglib.comment(new, items, mention))
            print(f"#{number}: {len(new)} new tonight, {len(items)} waiting in total.")
        else:
            # Nothing arrived, so nothing is sent: the body is current and the
            # list is shorter than it was. Silence here is the feature.
            print(f"#{number}: {len(items)} waiting, nothing new tonight.")
        return 0

    except GhError as exc:
        print(f"!! Could not file the picture backlog: {exc}", file=sys.stderr)
        print("   The menus are committed; this is only the report.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
