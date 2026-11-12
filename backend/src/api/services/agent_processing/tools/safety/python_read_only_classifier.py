"""Conservative proof that a Python script only reads data and changes nothing.

A script is read-only only when every node of its syntax tree is on a short allowlist, every name it reads is a vetted builtin or one it defined itself,
and every attribute it touches is a vetted method name or a vetted attribute of one of a few pure standard-library modules. Anything the module does not
positively recognize makes the whole script "not read-only", which keeps the normal approval prompt. A false "not read-only" costs one approval click;
a false "read-only" would let a change run unasked, so every ambiguity resolves toward the prompt.

The proof rests on one invariant: the script can only ever hold values that come from literals, vetted builtins, vetted module attributes, and files opened
for reading. None of those can write a file, start a process, open a socket, or change the environment, and there is no way to reach a module, function,
or attribute outside the lists (no dunder names, no ``getattr``, no ``eval``, no ``lambda``, no function or class definitions).

"Read-only" means no side effects: it cannot change files, settings, or system state and cannot send anything. It does not mean "harmless to read": the
script can read any file the user can read, exactly as ``cat`` can.
"""

from __future__ import annotations

import ast
import warnings
from typing import Dict, FrozenSet, Optional, Set

from .applescript_read_only_classifier import ReadOnlyVerdict

MAX_SCRIPT_CHARACTERS = 8000
MAX_INTEGER_LITERAL = 1_000_000

# Builtins whose behavior is limited to computing on values or printing. `open` is deliberately absent: it is handled in _check_open_call, because it is safe only with a read mode.
ALLOWED_BUILTINS: FrozenSet[str] = frozenset(
    {
        "print", "len", "sorted", "reversed", "enumerate", "zip", "range", "min", "max", "sum", "abs", "round", "divmod",
        "str", "int", "float", "bool", "list", "dict", "set", "tuple", "frozenset", "bytes",
        "any", "all", "isinstance", "repr", "chr", "ord", "map", "filter", "iter", "next",
    }
)

# The only modules a script may import, and the only attributes of each it may use. All of them compute on values or read a stream.
MODULE_ATTRIBUTES: Dict[str, FrozenSet[str]] = {
    "json": frozenset({"load", "loads", "dumps", "JSONDecodeError"}),
    "re": frozenset(
        {
            "compile", "match", "search", "findall", "finditer", "sub", "split", "fullmatch", "escape", "error",
            "I", "IGNORECASE", "M", "MULTILINE", "S", "DOTALL", "X", "VERBOSE",
        }
    ),
    "sys": frozenset({"argv", "stdin", "stdout", "stderr", "exit", "maxsize", "version_info"}),
    "collections": frozenset({"Counter", "defaultdict", "OrderedDict", "deque"}),
    "math": frozenset({"floor", "ceil", "sqrt", "log", "log10", "exp", "pi", "e", "inf", "isnan", "fabs"}),
}

# Method and attribute names allowed on any other value. Every value the script can hold is a string, number, list, dict, set, tuple, regular-expression object, match, read-only file, or standard stream, so none of these names can change anything outside the script. `write` and `flush` are here for `sys.stdout.write`; on a file opened for reading they only raise.
ALLOWED_METHOD_NAMES: FrozenSet[str] = frozenset(
    {
        "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "join", "lower", "upper", "startswith", "endswith", "replace", "find", "rfind",
        "count", "index", "title", "capitalize", "isdigit", "isalpha", "isalnum", "zfill", "ljust", "rjust", "center", "partition", "rpartition",
        "removeprefix", "removesuffix", "encode", "decode",
        "get", "items", "keys", "values", "copy", "setdefault", "update", "pop", "append", "extend", "insert", "sort", "reverse", "add", "discard",
        "most_common", "elements", "appendleft", "popleft",
        "group", "groups", "groupdict", "start", "end", "span", "match", "search", "findall", "finditer", "sub", "fullmatch",
        "read", "readline", "readlines", "close", "seek", "tell", "write", "flush",
    }
)

READ_MODES: FrozenSet[str] = frozenset({"r", "rt", "tr", "rb", "br"})
OPEN_KEYWORDS: FrozenSet[str] = frozenset({"mode", "encoding", "errors", "newline"})

# Statements and expressions the checker understands. Anything else (function and class definitions, lambda, try, raise, while, global, delete, await, yield, walrus, match, shifts, power) is refused.
_ALLOWED_NODE_TYPES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If, ast.With, ast.withitem, ast.Pass, ast.Break, ast.Continue,
    ast.Import, ast.ImportFrom, ast.alias,
    ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Compare, ast.Call, ast.keyword, ast.Attribute, ast.Subscript, ast.Slice, ast.Starred,
    ast.Name, ast.Constant, ast.JoinedStr, ast.FormattedValue,
    ast.Dict, ast.Set, ast.List, ast.Tuple,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.Load, ast.Store,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.BitAnd, ast.BitOr,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
)


def _no(reason: str) -> ReadOnlyVerdict:
    return ReadOnlyVerdict(False, reason)


class _Refusal(Exception):
    """Raised with the reason a script is not provably read-only."""


class _Checker:
    def __init__(self, tree: ast.AST) -> None:
        self.module_aliases: Dict[str, str] = {}
        self.defined_names: Set[str] = set()
        self._collect_definitions(tree)

    def _collect_definitions(self, tree: ast.AST) -> None:
        """Gather every name the script binds, so a read of a name can be matched to a vetted source."""
        stored_names: Set[str] = set()
        from_imported_names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                stored_names.add(node.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if self.module_aliases.get(bound, alias.name) != alias.name:
                        raise _Refusal(f"it binds the name '{bound}' to two different modules")
                    if alias.name in MODULE_ATTRIBUTES:
                        self.module_aliases[bound] = alias.name
            elif isinstance(node, ast.ImportFrom):
                from_imported_names.update(alias.asname or alias.name for alias in node.names)
        # The attribute checks trust that a module alias still means that module, so no assignment or second import may reuse the name.
        if (stored_names | from_imported_names) & set(self.module_aliases):
            raise _Refusal("it reuses the name of an imported module")
        self.defined_names = stored_names | from_imported_names | set(self.module_aliases)

    def check(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise _Refusal(f"it uses {type(node).__name__}, which is not on the read-only list")
        if isinstance(node, ast.Import):
            self._check_import(node)
        elif isinstance(node, ast.ImportFrom):
            self._check_import_from(node)
            return
        elif isinstance(node, ast.Call):
            self._check_call(node)
            return
        elif isinstance(node, ast.Attribute):
            self._check_attribute(node)
            return
        elif isinstance(node, ast.Name):
            self._check_name(node)
        elif isinstance(node, ast.Constant):
            self._check_constant(node)
        elif isinstance(node, ast.keyword):
            if node.arg is None or node.arg.startswith("__"):
                raise _Refusal("it passes keyword arguments in a form that is not allowed")
        for child in ast.iter_child_nodes(node):
            self.check(child)

    def _check_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in MODULE_ATTRIBUTES:
                raise _Refusal(f"it imports '{alias.name}', which is not a read-only module")

    def _check_import_from(self, node: ast.ImportFrom) -> None:
        if node.level != 0 or node.module not in MODULE_ATTRIBUTES:
            raise _Refusal(f"it imports from '{node.module}', which is not a read-only module")
        allowed = MODULE_ATTRIBUTES[node.module]
        for alias in node.names:
            if alias.name not in allowed:
                raise _Refusal(f"it imports '{alias.name}' from '{node.module}', which is not on the read-only list")

    def _check_name(self, node: ast.Name) -> None:
        name = node.id
        if name.startswith("__"):
            raise _Refusal("it uses a double-underscore name")
        if isinstance(node.ctx, ast.Store):
            if name == "open":
                raise _Refusal("it rebinds 'open'")
            return
        if name == "open":
            raise _Refusal("it uses open() in a way other than calling it directly")
        if name in ALLOWED_BUILTINS or name in self.defined_names:
            return
        raise _Refusal(f"it uses the name '{name}', which is not a vetted builtin or one the script defined")

    def _check_constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_INTEGER_LITERAL:
            raise _Refusal("it uses a very large number")

    def _check_attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.ctx, ast.Load):
            raise _Refusal("it assigns to an attribute")
        if node.attr.startswith("__"):
            raise _Refusal("it uses a double-underscore attribute")
        owner = node.value
        if isinstance(owner, ast.Name) and owner.id in self.module_aliases:
            module = self.module_aliases[owner.id]
            if node.attr not in MODULE_ATTRIBUTES[module]:
                raise _Refusal(f"it uses '{module}.{node.attr}', which is not on the read-only list")
            return
        if node.attr not in ALLOWED_METHOD_NAMES:
            raise _Refusal(f"it uses the attribute or method '{node.attr}', which is not on the read-only list")
        self.check(owner)

    def _check_call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Name) and function.id == "open":
            self._check_open_call(node)
            return
        if not isinstance(function, (ast.Name, ast.Attribute)):
            raise _Refusal("it calls the result of another expression")
        self.check(function)
        for argument in node.args:
            self.check(argument)
        for keyword in node.keywords:
            self.check(keyword)

    def _check_open_call(self, node: ast.Call) -> None:
        """Allow `open(path)` and `open(path, 'r')` forms only: a literal read mode, no file descriptor tricks, no opener."""
        if not node.args and not any(keyword.arg == "file" for keyword in node.keywords):
            raise _Refusal("it calls open() without a path")
        if len(node.args) > 2 or any(isinstance(argument, ast.Starred) for argument in node.args):
            raise _Refusal("it calls open() with arguments in a form that is not allowed")
        mode: Optional[ast.expr] = node.args[1] if len(node.args) == 2 else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                if mode is not None:
                    raise _Refusal("it gives open() two modes")
                mode = keyword.value
            elif keyword.arg not in OPEN_KEYWORDS and keyword.arg != "file":
                raise _Refusal("it calls open() with a keyword that is not allowed")
        if mode is not None and not (isinstance(mode, ast.Constant) and isinstance(mode.value, str) and mode.value in READ_MODES):
            raise _Refusal("it opens a file in a mode other than reading")
        for argument in node.args:
            self.check(argument)
        for keyword in node.keywords:
            self.check(keyword)


def classify_python_read_only(script: str) -> ReadOnlyVerdict:
    """Return whether ``script`` provably only reads data."""
    if not isinstance(script, str) or not script.strip():
        return _no("the script is empty")
    if len(script) > MAX_SCRIPT_CHARACTERS:
        return _no("the script is too long to check")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(script, mode="exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        return _no(f"the script cannot be parsed ({type(error).__name__})")
    try:
        _Checker(tree).check(tree)
    except _Refusal as refusal:
        return _no(str(refusal))
    except RecursionError:
        return _no("the script is nested too deeply to check")
    return ReadOnlyVerdict(True, "every statement is a recognized read-only form")


__all__ = [
    "ALLOWED_BUILTINS",
    "ALLOWED_METHOD_NAMES",
    "MODULE_ATTRIBUTES",
    "classify_python_read_only",
]
