#!/usr/bin/env python3
"""Build and verify verbatim reading pages (v3.2.1). Standard library only.

build   Write a reading page for a UTF-8 text raw file into a working directory.
        The body is the raw bytes, concatenated without decoding or normalization.
        Enforced: --out must be inside --workdir; neither may be inside an Obsidian
        vault (a directory with .obsidian/ at or above it); existing files are
        never overwritten; raw must be strict UTF-8; names and fields are validated.
verify  Rebuild the page from the raw file and the page's own header fields and
        compare the fixed envelope/source bytes. Candidate title/type/date/style
        are untrusted unless --expected-page-sha256 binds the trusted build.
        Production acceptance requires that flag; unbound mode is diagnostic.

Exit codes: 0 PASS/BUILT, 1 FAIL, 2 invalid input. Stable-ancestry, private
workdir required: path checks/exclusive create do not defend concurrent hostile
ancestor junction replacement. All vault mutations still require the native guard.
"""
import argparse
import datetime
import hashlib
import re
import sys
from pathlib import Path

END = b"<!-- verbatim-end -->"
FORBIDDEN_NAME_CHARS = set('/\\:*?"<>|[]#^')
TYPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
HEADER_RE = re.compile(
    rb"\A---\n"
    rb"type: (?P<type>[A-Za-z][A-Za-z0-9_-]{0,63})\n"
    rb'title: "(?P<title>(?:[^"\\\n]|\\.)*)"\n'
    rb"status: active\n"
    rb"created: (?P<date>\d{4}-\d{2}-\d{2})\n"
    rb"updated: (?P=date)\n"
    rb"---\n"
)
MARKER_RE = re.compile(rb"<!-- verbatim-begin bytes=\d+ sha256=[0-9a-f]{64}(?: fence=(?P<fence>\d+))? -->\n")


class InputError(Exception):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_name(name: str, max_length: int = 200) -> str:
    if not name or len(name) > max_length:
        raise InputError("archive name empty or exceeds the allowed input length")
    if name in (".", "..") or name.startswith(".") or name.endswith((" ", ".")):
        raise InputError("archive name must not start with a dot or end with a space/dot")
    if any(c in FORBIDDEN_NAME_CHARS for c in name) or any(ord(c) < 32 for c in name):
        raise InputError("archive name must be a plain file name (no path separators, traversal or link syntax)")
    stem = name.split(".", 1)[0].rstrip(" ").upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        raise InputError("archive name is a reserved Windows device name")
    return name


def versioned_archive_name(name: str, digest: str, path_prefixes: list[str], max_path_units: int = 240) -> str:
    """Pure Windows path budget planner; no filesystem reads or writes.

    Prefixes must include the raw and every checkpoint/staging ancestor that
    will be prepended to the basename. This does not discover those ancestors.
    Truncate stem by codepoint, never hash/extension or a UTF-16 surrogate half.
    """
    check_name(name, max_length=1024)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise InputError("raw digest must contain all 64 hex characters")
    if type(max_path_units) is not int or not 80 <= max_path_units <= 32760 or not path_prefixes or len(path_prefixes) > 32:
        raise InputError("invalid explicit path budget or path-prefix list")
    normalized=[]
    reserved={"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    for prefix in path_prefixes:
        if not isinstance(prefix, str):
            raise InputError("planned prefixes must be fully qualified Windows paths")
        portable=prefix.replace(chr(92),'/')
        if re.match(r'^[A-Za-z]:/',portable):
            components=portable[3:].split('/')
        elif portable.startswith('//'):
            components=portable[2:].split('/')
            if len(components)<2 or not all(components[:2]):
                raise InputError("UNC prefix requires server and share")
        else:
            raise InputError("prefix must be fully qualified drive or UNC path")
        for component in filter(None,components):
            stem=component.split('.',1)[0].rstrip(' ').upper()
            if (component in ('.','..') or component.endswith((' ','.'))
                or any(ord(c)<32 or c in '<>:"|?*' for c in component)
                or stem in reserved or re.fullmatch(r'(?:COM|LPT)[1-9¹²³]',stem)):
                raise InputError("invalid, device or alias-bearing Windows path component")
        normalized.append(prefix.rstrip('/'+chr(92))+chr(92))
    stem, dot, extension=name.rpartition('.')
    if not dot:stem=name;extension=''
    else:extension='.'+extension
    suffix='--sha256-'+digest.lower()+extension
    def units(s):
        try:return len(s.encode('utf-16-le',errors='strict'))//2
        except UnicodeEncodeError:raise InputError("invalid Unicode in name or path prefix")
    while stem:
        candidate=stem+suffix
        if units(candidate)<=200 and all(units(p+candidate)<=max_path_units for p in normalized):
            return check_name(candidate)
        stem=stem[:-1]
    raise InputError("full hash and extension cannot fit with a nonempty title; hold without shortening hash")


def check_title(title: str) -> str:
    if not title.strip() or len(title) > 300 or any(
        ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF
        or ord(c) in (0xFFFE, 0xFFFF) or c in '\u2028\u2029' for c in title
    ):
        raise InputError("title must be 1-300 printable characters on one line")
    return title


def check_type(t: str) -> str:
    if not TYPE_RE.fullmatch(t):
        raise InputError("type must be a simple identifier supported by the vault schema")
    return t


def check_date(d: str) -> str:
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        raise InputError("date must be a real YYYY-MM-DD date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise InputError("date must be YYYY-MM-DD")
    return d


def check_utf8(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise InputError(f"raw is not strict UTF-8 text (byte offset {e.start}); held: format not supported")
    if any((ord(c) < 32 and c not in '\t\n\r') or 127 <= ord(c) <= 159 for c in text):
        raise InputError("raw contains NUL or unsupported control characters; held as non-text input")


def inside_vault(path: Path) -> bool:
    return any((p / ".obsidian").exists() or (p / ".claude-obsidian.json").exists()
               or ((p / "wiki").is_dir() and (p / ".raw").is_dir())
               for p in [path, *path.parents])


def yaml_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def render(raw: bytes, name: str, title: str, typ: str, date: str, style: str) -> bytes:
    fence_len = 0
    if style == "fenced":
        runs = re.findall(rb"`+", raw)
        fence_len = max(3, max((len(r) for r in runs), default=0) + 1)
    header = (
        "---\n"
        f"type: {typ}\n"
        f"title: {yaml_quote(title)}\n"
        "status: active\n"
        f"created: {date}\n"
        f"updated: {date}\n"
        "---\n"
        "> [!info] Salinan baca verbatim\n"
        "> Isi di antara penanda di bawah identik byte dengan arsip (SHA-256 tercantum). "
        "Tidak ada ringkasan, terjemahan, atau suntingan.\n"
        "\n"
        f"Sumber arsip: [[.raw/{name}]]\n"
        "\n"
    ).encode("utf-8")
    fence_attr = f" fence={fence_len}" if fence_len else ""
    page = header + f"<!-- verbatim-begin bytes={len(raw)} sha256={sha256(raw)}{fence_attr} -->\n".encode("ascii")
    if fence_len:
        page += b"`" * fence_len + b"text\n"
    page += raw + b"\n"
    if fence_len:
        page += b"`" * fence_len + b"\n"
    return page + END + b"\n"


def cmd_build(a) -> int:
    raw_path = Path(a.raw).resolve()
    raw = raw_path.read_bytes()
    check_utf8(raw)
    name = check_name(a.archive_name or raw_path.name)
    workdir = Path(a.workdir).resolve()
    if not workdir.is_dir():
        raise InputError("--workdir must be an existing directory")
    if inside_vault(workdir):
        raise InputError("--workdir is inside an Obsidian vault; build only in a working directory outside the vault")
    out = Path(a.out).resolve()
    if inside_vault(out.parent):
        raise InputError("--out is inside an Obsidian vault; refuse direct vault writes")
    if workdir not in out.parents:
        raise InputError("--out must be inside --workdir")
    if not out.parent.is_dir():
        raise InputError("parent directory of --out does not exist")
    if out.exists():
        raise InputError("--out already exists; refusing to overwrite")
    page = render(raw, name, check_title(a.title), check_type(a.type), check_date(a.date), a.style)
    with open(out, "xb") as fh:  # exclusive create: never overwrite, even in a race
        fh.write(page)
    print(f"BUILT {out} body_bytes={len(raw)} body_sha256={sha256(raw)} page_sha256={sha256(page)} style={a.style}")
    return 0


def cmd_verify(a) -> int:
    page = Path(a.page).read_bytes()
    raw = Path(a.raw).read_bytes()
    if a.expected_page_sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", a.expected_page_sha256):
            raise InputError("expected page SHA-256 must be 64 hex characters (either case)")
        if sha256(page) != a.expected_page_sha256.lower():
            print("FAIL\n - whole-page SHA-256 differs from trusted pre-apply baseline")
            return 1
    check_utf8(raw)
    name = check_name(a.archive_name or Path(a.raw).name)
    m = HEADER_RE.match(page)
    if not m:
        print("FAIL\n - frontmatter is not in the generated form (changed, extended or missing)")
        return 1
    marker = MARKER_RE.search(page, m.end())
    style = "fenced" if marker and marker.group("fence") else "rendered"
    try:
        title = check_title(yaml_unquote(m.group("title").decode("utf-8")))
        expected = render(raw, name, title, m.group("type").decode(), check_date(m.group("date").decode()), style)
    except (InputError, UnicodeDecodeError) as e:
        print(f"FAIL\n - header fields invalid: {e}")
        return 1
    if page == expected:
        level = "BOUND" if a.expected_page_sha256 else "DIAGNOSTIC_UNBOUND"
        print(f"PASS {level} source/envelope matches rebuild; body_bytes={len(raw)} sha256={sha256(raw)} style={style}")
        return 0
    i = next((k for k in range(min(len(page), len(expected))) if page[k] != expected[k]),
             min(len(page), len(expected)))
    body_start = expected.index(b"\n", expected.index(b"<!-- verbatim-begin")) + 1
    if style == "fenced":
        body_start = expected.index(b"\n", body_start) + 1
    region = "header" if i < body_start else ("body" if i < body_start + len(raw) else "footer/trailing content")
    print("FAIL")
    print(f" - page differs from rebuild at byte {i} ({region}); page={len(page)} bytes, expected={len(expected)} bytes")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", required=True)
    b.add_argument("--workdir", required=True, help="existing working directory outside the vault")
    b.add_argument("--out", required=True, help="output path inside --workdir")
    b.add_argument("--title", required=True)
    b.add_argument("--type", required=True, help="frontmatter type supported by the vault schema")
    b.add_argument("--date", required=True, help="YYYY-MM-DD")
    b.add_argument("--style", choices=["rendered", "fenced"], required=True)
    b.add_argument("--archive-name", help="file name under .raw/ (default: raw basename)")
    v = sub.add_parser("verify")
    v.add_argument("page")
    v.add_argument("raw")
    v.add_argument("--archive-name")
    v.add_argument("--expected-page-sha256", help="trusted pre-apply full-page digest; mandatory for production acceptance")
    a = ap.parse_args()
    try:
        return cmd_build(a) if a.cmd == "build" else cmd_verify(a)
    except InputError as e:
        print(f"INVALID INPUT: {e}")
        return 2
    except OSError as e:
        print(f"INVALID INPUT: {e.strerror}: {e.filename}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
