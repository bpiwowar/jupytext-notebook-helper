"""Turn the practicals manifest into the page that hands them out.

The notebooks reach the students through a directory on a web server, and a
directory listing is not a hand-out: it shows `07-2-ppo_clip.ipynb` next to a
zip and a `colab/` folder, in whatever order the server feels like, with no
word on which file to open or what it contains.

So this writes an `index.html` to put at the root of that directory: the
archives to download first, then one row per practical — its number, its name,
a one-line description when the source has one, and a link per variant
(notebook, Colab, corrigé). It reads the JSON of :mod:`.manifest`, which is
already the answer to "which practicals exist and where does each file end
up", so the page and whatever else announces the course cannot drift apart.

The result is one self-contained file: the CSS is inline, there is no script,
no font and no image to fetch, and nothing dated in it — so an unchanged
course rewrites an identical page, which `write_if_changed` then leaves alone
and rsync does not re-upload.

``--intro`` inserts an HTML fragment under the title (the practical's own
words: what the course is, which Python, where to ask for help). It is
inserted verbatim: it is the course's own file, not user input.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from .manifest import write_text_if_changed

# What each archive of `bundles` is called when the course says nothing. The
# ids come from tp.mk (`student`, and `solution` once released).
DEFAULT_BUNDLE_LABELS = {
    "student": "Notebooks and environment",
    "solution": "Solutions",
}

STYLE = """\
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #1a1c21;
  --muted: #5c6270;
  --line: #e2e5ea;
  --card: #f6f7f9;
  --accent: #2d5bb9;
  --accent-fg: #ffffff;
  --solution: #7a5199;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14161a;
    --fg: #e8eaed;
    --muted: #9aa1ad;
    --line: #2b2f36;
    --card: #1d2026;
    --accent: #7ba3ea;
    --accent-fg: #14161a;
    --solution: #c0a0da;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2.5rem 1rem 4rem;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
}
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.9rem; margin: 0 0 .5rem; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 .75rem; font-weight: 600; }
a { color: var(--accent); }
.intro { color: var(--muted); }
.intro p:first-child { margin-top: 0; }
.bundles { display: flex; flex-wrap: wrap; gap: .75rem; padding: 0; margin: 0;
           list-style: none; }
.bundle {
  flex: 1 1 15rem;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  padding: .85rem 1rem;
  border: 1px solid var(--line);
  border-radius: .5rem;
  background: var(--card);
}
.bundle .name { font-weight: 600; }
.bundle .size { color: var(--muted); font-size: .85rem; }
table { width: 100%; border-collapse: collapse; }
caption { text-align: left; color: var(--muted); padding-bottom: .5rem; }
th, td { text-align: left; padding: .6rem .5rem; border-bottom: 1px solid var(--line); vertical-align: baseline; }
th { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em;
     color: var(--muted); font-weight: 600; }
td.num { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
td.name { font-weight: 600; }
td.desc { color: var(--muted); }
td.links { white-space: nowrap; }
.link {
  display: inline-block;
  margin: .1rem .25rem .1rem 0;
  padding: .2rem .55rem;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  font-size: .85rem;
  text-decoration: none;
}
.link:hover { background: var(--accent); color: var(--accent-fg); }
.link.solution { border-color: var(--solution); color: var(--solution); }
.link.solution:hover { background: var(--solution); color: var(--accent-fg); }
footer { margin-top: 3rem; color: var(--muted); font-size: .85rem; }
@media (max-width: 40rem) {
  td.links { white-space: normal; }
  .desc-col { display: none; }
}
"""


def escape(text: str) -> str:
    return html.escape(text, quote=True)


def human_size(size: int) -> str:
    """A file size a student can read, in the units a browser would show."""
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            precision = 0 if unit == "B" or value >= 100 else 1
            return f"{value:.{precision}f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def file_size(root: Path | None, path: str) -> str | None:
    """The size of a listed file, when it is here to be measured."""
    if root is None:
        return None
    candidate = root / path
    try:
        return human_size(candidate.stat().st_size) if candidate.is_file() else None
    except OSError:
        return None


# The numbering a course puts at the front of its file names: `01`, `03-2`,
# `A01`. What follows it is the subject, which the name column already says.
_NUMBER = re.compile(r"^([A-Za-z]{0,2}\d+(?:-\d+)*)(?:[-_.]|$)")


def practical_number(identifier: str) -> str:
    """The number a file name starts with, or nothing when it starts with a word."""
    match = _NUMBER.match(identifier)
    return match.group(1) if match else ""


def href(base_url: str, entry: dict[str, Any]) -> str:
    """Where a file entry points: its absolute ``url``, or ``baseUrl + path``."""
    url = entry.get("url")
    if isinstance(url, str) and url:
        return url
    return base_url + str(entry.get("path", ""))


def parse_label(value: str) -> tuple[str, str]:
    """``id=Label`` (as given on the command line)."""
    bundle_id, sep, label = value.partition("=")
    if not sep or not bundle_id.strip() or not label.strip():
        raise SystemExit(f"index: --bundle-label expects id=label, got {value!r}")
    return bundle_id.strip(), label.strip()


def bundle_label(bundle_id: str, overrides: dict[str, str]) -> str:
    if bundle_id in overrides:
        return overrides[bundle_id]
    if bundle_id in DEFAULT_BUNDLE_LABELS:
        return DEFAULT_BUNDLE_LABELS[bundle_id]
    return bundle_id.replace("-", " ").replace("_", " ").capitalize()


def render_bundles(
    bundles: list[dict[str, Any]],
    base_url: str,
    overrides: dict[str, str],
    root: Path | None,
) -> str:
    if not bundles:
        return ""
    items = []
    for bundle in bundles:
        path = str(bundle.get("path", ""))
        label = bundle_label(str(bundle.get("id", "")), overrides)
        size = file_size(root, path)
        items.append(
            '    <li class="bundle">'
            f'<a class="name" href="{escape(href(base_url, bundle))}">'
            f"{escape(label)}</a>"
            f'<span class="size">{escape(Path(path).name)}'
            f"{f' · {escape(size)}' if size else ''}</span></li>"
        )
    return (
        "  <h2>Download</h2>\n"
        '  <ul class="bundles">\n' + "\n".join(items) + "\n  </ul>\n"
    )


def render_practicals(
    practicals: list[dict[str, Any]], base_url: str, numbered: bool
) -> str:
    has_description = any(p.get("description") for p in practicals)
    numbers = {
        str(p.get("id", "")): practical_number(str(p.get("id", ""))) for p in practicals
    }
    # Only when the course numbers its sources at all — otherwise the column
    # would be a row of blanks.
    numbered = numbered and any(numbers.values())
    head = ["    <tr>"]
    if numbered:
        head.append('<th scope="col">#</th>')
    head.append('<th scope="col">Practical</th>')
    if has_description:
        head.append('<th scope="col" class="desc-col">Description</th>')
    head.append('<th scope="col">Files</th></tr>')

    rows = []
    for practical in practicals:
        cells = []
        if numbered:
            number = numbers[str(practical.get("id", ""))]
            cells.append(f'<td class="num">{escape(number)}</td>')
        cells.append(f'<td class="name">{escape(str(practical.get("name", "")))}</td>')
        if has_description:
            description = str(practical.get("description") or "")
            cells.append(f'<td class="desc desc-col">{escape(description)}</td>')
        links = [
            '<a class="link{solution}" href="{url}">{label}</a>'.format(
                solution=" solution" if entry.get("solution") else "",
                url=escape(href(base_url, entry)),
                label=escape(str(entry.get("label", "Notebook"))),
            )
            for entry in practical.get("files", [])
        ]
        cells.append(f'<td class="links">{" ".join(links)}</td>')
        rows.append("    <tr>" + "".join(cells) + "</tr>")

    return (
        "  <h2>Practicals</h2>\n"
        "  <table>\n"
        "    <thead>\n" + "".join(head) + "\n    </thead>\n"
        "    <tbody>\n" + "\n".join(rows) + "\n    </tbody>\n"
        "  </table>\n"
    )


def render(
    manifest: dict[str, Any],
    *,
    title: str,
    intro: str = "",
    footer: str = "",
    lang: str = "en",
    bundle_labels: dict[str, str] | None = None,
    root: Path | None = None,
    numbered: bool = True,
) -> str:
    base_url = str(manifest.get("baseUrl") or "")
    overrides = bundle_labels or {}
    body = [f"  <h1>{escape(title)}</h1>"]
    if intro:
        body.append(f'  <div class="intro">\n{intro.rstrip()}\n  </div>')
    body.append(
        render_bundles(
            list(manifest.get("bundles") or []), base_url, overrides, root
        ).rstrip()
    )
    body.append(
        render_practicals(
            list(manifest.get("practicals") or []), base_url, numbered
        ).rstrip()
    )
    if footer:
        body.append(f"  <footer>{escape(footer)}</footer>")
    return (
        f'<!DOCTYPE html>\n<html lang="{escape(lang)}">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>\n{STYLE}</style>\n"
        "</head>\n<body>\n<main>\n"
        + "\n".join(part for part in body if part)
        + "\n</main>\n</body>\n</html>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jupytext_notebook_helper.index",
        description="Write the HTML index of the practicals from their manifest",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="the JSON written by jupytext_notebook_helper.manifest ('-' for stdin)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Practicals")
    parser.add_argument(
        "--intro",
        type=Path,
        help="an HTML fragment inserted under the title, verbatim",
    )
    parser.add_argument("--footer", default="")
    parser.add_argument("--lang", default="en", help="the page's language tag")
    parser.add_argument(
        "--bundle-label",
        action="append",
        default=[],
        metavar="ID=LABEL",
        help="how an archive of the manifest is named on the page (repeatable)",
    )
    parser.add_argument(
        "--no-numbers",
        action="store_true",
        help="leave out the column holding the number each file name starts with",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="the directory the listed paths are relative to; file sizes are "
        "shown for the archives found there (default: the output's directory)",
    )
    args = parser.parse_args(argv)

    if str(args.manifest) == "-":
        manifest = json.load(sys.stdin)
    else:
        if not args.manifest.is_file():
            raise SystemExit(f"index: no manifest at {args.manifest}")
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    intro = ""
    if args.intro:
        if not args.intro.is_file():
            raise SystemExit(f"index: no introduction file at {args.intro}")
        intro = args.intro.read_text(encoding="utf-8")

    page = render(
        manifest,
        title=args.title,
        intro=intro,
        footer=args.footer,
        lang=args.lang,
        bundle_labels=dict(parse_label(value) for value in args.bundle_label),
        root=args.root if args.root is not None else args.output.parent,
        numbered=not args.no_numbers,
    )
    changed = write_text_if_changed(args.output, page)
    count = len(manifest.get("practicals") or [])
    print(f"{args.output}: {count} practicals, {'written' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
