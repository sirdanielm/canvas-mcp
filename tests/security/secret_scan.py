"""Static credential checks with value-free findings for source-review tests."""

import ast
import re
from dataclasses import dataclass

_CANVAS = re.compile(r"[0-9]+~[A-Za-z0-9._-]{20,}")
_PROVIDER = re.compile(r"(?:sk-(?:proj-|live-)?|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{20,}")
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{40,}")
_SYMBOL = re.compile(r"(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[a-z][a-z0-9]*(?:_[a-z0-9]+)+)")
_HEX = re.compile(r"[a-fA-F0-9]{64}")
_UUID = re.compile(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")
_SENSITIVE = re.compile(r"(?:^|_)(?:token|secret|password|api_key)(?:$|_)", re.I)
_HASH_CONTEXT = re.compile(r"sha(?:256|512)?|hash|digest|fingerprint", re.I)
_PLACEHOLDER = re.compile(r"(?:your_|example_|synthetic_|fictional_|test_|placeholder)", re.I)


@dataclass(frozen=True)
class SecretFinding:
    line: int
    kind: str


def _context(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names = []
    child = node
    for _ in range(5):
        parent = parents.get(child)
        if parent is None:
            break
        if isinstance(parent, ast.Dict):
            for key, value in zip(parent.keys, parent.values, strict=True):
                if value is child and isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.append(key.value)
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.Compare)):
            names.extend(item.id for item in ast.walk(parent) if isinstance(item, ast.Name))
            names.extend(item.attr for item in ast.walk(parent) if isinstance(item, ast.Attribute))
            names.extend(item.args[0].value for item in ast.walk(parent)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                and item.func.attr == "get" and item.args
                and isinstance(item.args[0], ast.Constant) and isinstance(item.args[0].value, str))
            break
        if isinstance(parent, ast.keyword):
            names.append(parent.arg or "")
        child = parent
    return " ".join(names)


def find_secret_literals(source: str) -> list[SecretFinding]:
    """Recognize token forms and unexplained opaque literals without echoing them.

    Fixed policy/schema symbols are not credentials. SHA-256 literals are
    admitted only in a hash-named context; an unrelated opaque hex value is
    still flagged. Token-shaped strings are checked even inside docstrings or
    fixtures, so adding 'test' to a real token cannot suppress the finding.
    """
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value
        if _CANVAS.search(value) or _PROVIDER.search(value):
            findings.append(SecretFinding(node.lineno, "credential format"))
            continue
        context = _context(node, parents)
        sensitive = _SENSITIVE.search(context) is not None
        if sensitive and len(value) >= 12 and not _PLACEHOLDER.match(value):
            if not (_HEX.fullmatch(value) and _HASH_CONTEXT.search(context)):
                # Config labels/URLs are not values of credentials.
                if _OPAQUE.fullmatch(value):
                    findings.append(SecretFinding(node.lineno, "credential value"))
                    continue
        if not _OPAQUE.fullmatch(value):
            continue
        parent = parents.get(node)
        lookup_key = (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
            and parent.func.attr == "get" and parent.args and parent.args[0] is node)
        declared_symbol = ((lookup_key or re.search(r"schema|profile|status|rule|contract", context, re.I))
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+", value))
        if (_SYMBOL.fullmatch(value) or declared_symbol or _UUID.fullmatch(value)
                or _HEX.fullmatch(value) and _HASH_CONTEXT.search(context)
                or _PLACEHOLDER.match(value)):
            continue
        findings.append(SecretFinding(node.lineno, "unexplained opaque literal"))
    return findings
