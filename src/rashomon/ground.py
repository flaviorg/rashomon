"""Ground a ticket in the repo: which routes, tables, components and symbols does it touch?

Pure code. Files come from ``git ls-files`` (or a walk when the folder is not a git repo).
Symbols come from Python's ``ast`` for ``.py`` files and regex heuristics for SQL and
JS/TS. Text hits come from ripgrep when it is on PATH, otherwise from a Python scan with the
same semantics. The output is a context pack where every claim carries ``path:line``.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rashomon.text import split_identifier, stem, tokens

TEXT_EXTS = frozenset(
    ".py .pyi .sql .ts .tsx .js .jsx .mjs .vue .svelte .go .rb .java .kt .rs .md .toml .yaml .yml .json .html .css".split()  # noqa: E501, SIM905
)
SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".rashomon"})
MAX_FILE_BYTES = 200_000

_ROUTE_DECORATOR = re.compile(r"\.(get|post|put|patch|delete|route|api_route)$")
_SQL_TABLE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)", re.IGNORECASE)
_SQL_COLUMN = re.compile(r"^\s+[`\"]?([a-z_][a-z0-9_]*)[`\"]?\s+[A-Z]", re.IGNORECASE)
_JS_COMPONENT = re.compile(r"^\s*export\s+(?:default\s+)?(?:function|const|class)\s+([A-Z]\w*)")
_JS_FUNCTION = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const)\s+([a-z]\w*)")
_JS_ROUTE = re.compile(r"""fetch\(\s*["'`](/[^"'`?]*)""")


@dataclass(frozen=True)
class Entity:
    kind: str  # route | table | column | component | function | class | module
    name: str
    path: str
    line: int

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str


@dataclass
class ContextPack:
    repo: str
    fingerprint: str
    files: list[str]
    terms: list[str]
    entities: list[dict] = field(default_factory=list)
    hits: list[dict] = field(default_factory=list)
    search_backend: str = "python"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- repo facts


def _git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def tracked_files(repo: Path) -> list[str]:
    """``git ls-files`` relative to ``repo``; a filtered walk when it is not a git checkout."""
    listed = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard")
    if listed is not None:
        return sorted({line.strip() for line in listed.splitlines() if line.strip()})
    out: list[str] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            out.append(str((Path(root) / name).relative_to(repo)).replace(os.sep, "/"))
    return out


def fingerprint(repo: Path, files: list[str] | None = None) -> str:
    """HEAD sha when the checkout is clean; otherwise a hash of HEAD + file sizes and mtimes."""
    head = (_git(repo, "rev-parse", "HEAD") or "").strip()
    dirty = _git(repo, "status", "--porcelain", "--", ".")
    if head and dirty is not None and not dirty.strip():
        return head
    digest = hashlib.sha256(head.encode())
    for rel in files if files is not None else tracked_files(repo):
        try:
            st = (repo / rel).stat()
        except OSError:
            continue
        digest.update(f"{rel}:{st.st_size}:{int(st.st_mtime)}".encode())
    return ("dirty-" if head else "nogit-") + digest.hexdigest()[:16]


def _text_files(repo: Path, files: list[str]) -> list[str]:
    keep = []
    for rel in files:
        p = repo / rel
        if p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        keep.append(rel)
    return keep


# --------------------------------------------------------------------------- symbol index


def _python_entities(rel: str, source: str) -> list[Entity]:
    out = [Entity("module", rel.removesuffix(".py").replace("/", "."), rel, 1)]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(Entity("function", node.name, rel, node.lineno))
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and _ROUTE_DECORATOR.search("." + dec.func.attr)
                    and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)
                ):
                    method = dec.func.attr.upper() if dec.func.attr not in ("route", "api_route") else "ANY"
                    out.append(Entity("route", f"{method} {dec.args[0].value}", rel, dec.lineno))
        elif isinstance(node, ast.ClassDef):
            out.append(Entity("class", node.name, rel, node.lineno))
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)
                ):
                    out.append(Entity("table", str(stmt.value.value), rel, stmt.lineno))
    return out


def _sql_entities(rel: str, source: str) -> list[Entity]:
    out: list[Entity] = []
    table: str | None = None
    for i, line in enumerate(source.splitlines(), 1):
        if m := _SQL_TABLE.match(line):
            table = m.group(1)
            out.append(Entity("table", table, rel, i))
            continue
        if table and line.strip().startswith(")"):
            table = None
            continue
        if table and (m := _SQL_COLUMN.match(line)) and m.group(1).upper() not in {"PRIMARY", "FOREIGN", "UNIQUE"}:
            out.append(Entity("column", f"{table}.{m.group(1)}", rel, i))
    return out


def _js_entities(rel: str, source: str) -> list[Entity]:
    out: list[Entity] = []
    for i, line in enumerate(source.splitlines(), 1):
        if m := _JS_COMPONENT.match(line):
            out.append(Entity("component", m.group(1), rel, i))
        elif m := _JS_FUNCTION.match(line):
            out.append(Entity("function", m.group(1), rel, i))
        for m in _JS_ROUTE.finditer(line):
            out.append(Entity("route", f"CALL {m.group(1)}", rel, i))
    return out


def index_symbols(repo: Path, files: list[str]) -> list[Entity]:
    out: list[Entity] = []
    for rel in files:
        suffix = Path(rel).suffix.lower()
        if suffix not in {".py", ".sql", ".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            continue
        try:
            source = (repo / rel).read_text(errors="replace")
        except OSError:
            continue
        if suffix == ".py":
            out.extend(_python_entities(rel, source))
        elif suffix == ".sql":
            out.extend(_sql_entities(rel, source))
        else:
            out.extend(_js_entities(rel, source))
    return out


# --------------------------------------------------------------------------- matching


def ticket_terms(text: str, limit: int = 16) -> list[str]:
    """Stemmed content words of the ticket, most frequent first (ties by first appearance)."""
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for i, raw in enumerate(re.findall(r"[A-Za-z][A-Za-z0-9_]+", text or "")):
        for tok in tokens(raw, keep_meaningful=False):
            if len(tok) < 3:
                continue
            counts[tok] = counts.get(tok, 0) + 1
            order.setdefault(tok, i)
    ranked = sorted(counts, key=lambda t: (-counts[t], order[t]))
    return ranked[:limit]


def _entity_tokens(entity: Entity) -> frozenset[str]:
    name = entity.name.split(" ", 1)[-1]
    if entity.kind == "column":
        name = name.split(".", 1)[-1]
    return frozenset(stem(p.lower()) for p in split_identifier(name) if len(p) >= 2)


KIND_WEIGHT = {
    "route": 1.3,
    "table": 1.3,
    "component": 1.2,
    "column": 1.0,
    "class": 1.0,
    "function": 0.9,
    "module": 0.8,
}


def match_entities(entities: list[Entity], terms: list[str], limit: int = 24) -> list[tuple[Entity, float, list[str]]]:
    term_set = set(terms)
    scored: list[tuple[Entity, float, list[str]]] = []
    for ent in entities:
        toks = _entity_tokens(ent)
        if not toks:
            continue
        matched = sorted(toks & term_set)
        if not matched:
            continue
        score = round(len(matched) / len(toks) * KIND_WEIGHT.get(ent.kind, 1.0), 3)
        scored.append((ent, score, matched))
    scored.sort(key=lambda x: (-x[1], x[0].path, x[0].line))
    return scored[:limit]


def search_text(repo: Path, files: list[str], terms: list[str], limit: int = 20) -> tuple[list[Hit], str]:
    """Lines mentioning any term (word-prefix, case-insensitive). ripgrep if available."""
    if not terms:
        return [], "none"
    pattern = r"\b(" + "|".join(re.escape(t) for t in terms) + r")"
    rg = shutil.which("rg")
    if rg:
        try:
            proc = subprocess.run(
                [
                    rg,
                    "--line-number",
                    "--no-heading",
                    "--color",
                    "never",
                    "-i",
                    "--max-count",
                    "3",
                    "-e",
                    pattern,
                    "--",
                    *files,
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode in (0, 1):
                hits = []
                for line in proc.stdout.splitlines():
                    path, _, rest = line.partition(":")
                    num, _, text = rest.partition(":")
                    if num.isdigit():
                        hits.append(Hit(path, int(num), text.strip()[:160]))
                hits.sort(key=lambda h: (h.path, h.line))
                return hits[:limit], "ripgrep"
        except (OSError, subprocess.TimeoutExpired):
            pass
    rx = re.compile(pattern, re.IGNORECASE)
    hits = []
    for rel in files:
        try:
            lines = (repo / rel).read_text(errors="replace").splitlines()
        except OSError:
            continue
        found = 0
        for i, text in enumerate(lines, 1):
            if rx.search(text):
                hits.append(Hit(rel, i, text.strip()[:160]))
                found += 1
                if found >= 3:
                    break
    return hits[:limit], "python"


def build_context(repo: Path, ticket_text: str, files: list[str] | None = None) -> ContextPack:
    repo = repo.resolve()
    all_files = files if files is not None else tracked_files(repo)
    text_files = _text_files(repo, all_files)
    terms = ticket_terms(ticket_text)
    entities = match_entities(index_symbols(repo, text_files), terms)
    code_files = [f for f in text_files if not f.lower().endswith(".md")]
    hits, backend = search_text(repo, code_files, terms)
    return ContextPack(
        repo=repo.name,
        fingerprint=fingerprint(repo, all_files),
        files=all_files,
        terms=terms,
        entities=[{**asdict(e), "score": s, "matched": m} for e, s, m in entities],
        hits=[asdict(h) for h in hits],
        search_backend=backend,
    )


def render_context(pack: dict, max_files: int = 80) -> str:
    """The context pack as prompt text. Every line that claims something carries path:line."""
    lines = [f"Repository: {pack['repo']}", f"Ticket terms: {', '.join(pack['terms']) or '(none)'}", ""]
    lines.append("Entities matching the ticket (kind, name, path:line):")
    for e in pack["entities"] or []:
        lines.append(f"- {e['kind']} `{e['name']}` at {e['path']}:{e['line']}")
    if not pack["entities"]:
        lines.append("- (none found)")
    lines.append("")
    lines.append("Text hits (path:line: text):")
    for h in pack["hits"] or []:
        lines.append(f"- {h['path']}:{h['line']}: {h['text']}")
    lines.append("")
    files = pack["files"]
    lines.append(f"Tracked files ({len(files)}{', first ' + str(max_files) if len(files) > max_files else ''}):")
    lines.extend(f"- {f}" for f in files[:max_files])
    return "\n".join(lines)
