"""Run a function out of web/app.js, in node, without a browser.

app.js is one IIFE that reads its data out of the DOM on the first line, so
nothing in it is importable and nothing in it is exported. Stubbing a DOM to
get at a pure string function would be a bigger fake than the thing under test,
so instead the declaration is sliced out of the file by name and evaluated on
its own, with whatever it closes over supplied as a prelude.

That makes renaming a function a test failure with a clear message rather than
a silent skip, which is the trade: these are cross-language invariants, and the
only thing worse than a brittle check on them is no check at all.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "web" / "app.js"

NODE = shutil.which("node")

# Characters after which a "/" opens a regex literal rather than dividing.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {""}


class NotFound(LookupError):
    pass


def _skip_string(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == quote:
            return i + 1
        i += 1
    raise NotFound(f"unterminated {quote} string in {APP_JS.name}")


def _skip_regex(src: str, i: int) -> int:
    i += 1
    in_class = False
    while i < len(src):
        ch = src[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return i + 1
        i += 1
    raise NotFound(f"unterminated regex in {APP_JS.name}")


def _declaration(src: str, name: str) -> str:
    """The source text of one top-level `function name` or `const name =`."""
    match = re.search(
        rf"^[ \t]*(?:function\s+{re.escape(name)}\s*\(|"
        rf"(?:const|let|var)\s+{re.escape(name)}\s*=)",
        src, re.M)
    if not match:
        raise NotFound(
            f"{name} is not declared in web/app.js any more. The test that "
            f"wanted it is checking a real invariant -- point it at the new name.")

    is_function = "function" in match.group(0)
    start, i, depth, body_seen, prev = match.start(), match.end() - 1, 0, False, ""
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            i = _skip_string(src, i)
            prev = ch
            continue
        if ch == "/" and src[i + 1:i + 2] == "/":
            i = src.find("\n", i)
            i = len(src) if i < 0 else i
            continue
        if ch == "/" and src[i + 1:i + 2] == "*":
            i = src.index("*/", i) + 2
            continue
        if ch == "/" and prev in _REGEX_AFTER:
            i = _skip_regex(src, i)
            prev = "/"
            continue
        if ch in "([{":
            depth += 1
            body_seen = body_seen or ch == "{"
        elif ch in ")]}":
            depth -= 1
            if depth == 0 and body_seen and is_function:
                return src[start:i + 1]
        elif ch == ";" and depth == 0 and not is_function:
            return src[start:i + 1]
        if not ch.isspace():
            prev = ch
        i += 1
    raise NotFound(f"could not find the end of {name} in web/app.js")


def declarations(*names: str) -> str:
    src = APP_JS.read_text()
    return "\n\n".join(_declaration(src, name) for name in names)


def call(names, body: str, payload=None, prelude: str = "", tmp_path: Path | None = None):
    """Evaluate `body` with those declarations in scope; INPUT is `payload`.

    `body` is a function body: it returns the value the test asserts on, which
    comes back through JSON.
    """
    script = "\n".join([
        "'use strict';",
        prelude,
        declarations(*names),
        "const INPUT = JSON.parse(process.argv[2]);",
        f"const OUT = (() => {{ {body} }})();",
        "process.stdout.write(JSON.stringify(OUT === undefined ? null : OUT));",
    ])
    directory = tmp_path or Path(tempfile.mkdtemp())
    path = directory / "bridge.mjs"
    path.write_text(script)
    done = subprocess.run([NODE, str(path), json.dumps(payload)],
                          capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise AssertionError(f"node failed:\n{done.stderr.strip()}\n\n{script}")
    return json.loads(done.stdout)
