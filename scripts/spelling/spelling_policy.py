"""American-spelling policy shared by the one-time codemod and the permanent checker.

The British spellings below are intentional: they are the keys of the replacement map. The scripts/spelling/ directory is a protected mapping path, so neither the codemod nor the checker rewrites or reports it.
"""

from __future__ import annotations

import bisect
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_IZE_STEMS = (
    "agon", "alphabet", "amort", "anonym", "antagon", "apolog", "author", "binar",
    "canonical", "capital", "categor", "central", "character", "colon", "commercial",
    "conceptual", "container", "contextual", "critic", "custom", "decentral", "demon",
    "denormal", "depriorit", "desensit", "deserial", "digit", "discret", "dramat", "econom",
    "empath", "emphas", "energ", "equal", "external", "familiar", "fantas", "final",
    "formal", "general", "global", "harmon", "human", "hypothes", "ideal", "idol",
    "initial", "internal", "italic", "item", "jeopard", "legal", "legitim", "lemmat",
    "liberal", "local", "margin", "material", "maxim", "memo", "memor", "mesmer", "metabol",
    "miniatur", "minim", "mobil", "modern", "monet", "national", "neutral", "normal",
    "operational", "optim", "organ", "ostrac", "parameter", "penal", "personal", "plagiar",
    "polar", "popular", "pressur", "priorit", "privat", "public", "quant", "random",
    "raster", "rational", "real", "recogn", "regular", "reinitial", "renormal", "reorgan",
    "repriorit", "resynchron", "revital", "sanit", "scrutin", "sensit", "serial", "social",
    "special", "stabil", "standard", "stigmat", "subsid", "summar", "symbol", "sympath",
    "synchron", "synthes", "systemat", "theor", "token", "traumat", "trivial", "unauthor",
    "uncategor", "uninitial", "unnormal", "unorgan", "unrecogn", "util", "vapor", "vector",
    "victim", "virtual", "visual", "vocal",
)
_IZE_SUFFIXES = (
    ("ise", "ize"), ("ised", "ized"), ("ises", "izes"), ("ising", "izing"),
    ("isation", "ization"), ("isations", "izations"), ("iser", "izer"), ("isers", "izers"),
    ("isable", "izable"),
)
_YZE_STEMS = ("analy", "cataly", "hydroly", "paraly")
_YZE_SUFFIXES = (("se", "ze"), ("sed", "zed"), ("sing", "zing"), ("ser", "zer"), ("sers", "zers"))
_OUR_WORDS = (
    "armour", "behaviour", "clamour", "colour", "endeavour", "favour", "flavour", "harbour",
    "honour", "humour", "labour", "neighbour", "odour", "parlour", "rigour", "rumour",
    "saviour", "savour", "splendour", "tumour", "valour", "vapour",
)
_OUR_SUFFIXES = ("", "s", "ed", "ing", "al", "ally", "ful", "ite", "ites", "less", "able", "hood", "hoods")
_DOUBLED_L_STEMS = (
    "bevel", "cancel", "channel", "chisel", "counsel", "dial", "duel", "enamel", "equal",
    "fuel", "funnel", "grovel", "jewel", "kennel", "label", "level", "libel", "marshal",
    "marvel", "mislabel", "model", "panel", "parcel", "pedal", "pencil", "quarrel", "refuel",
    "relabel", "remodel", "rival", "shovel", "signal", "spiral", "stencil", "swivel", "total",
    "towel", "travel", "tunnel", "unlabel", "unmarshal", "unravel",
)
_DOUBLED_L_SUFFIXES = (("led", "ed"), ("ling", "ing"), ("ler", "er"), ("lers", "ers"))
_DIRECT_REPLACEMENTS = {
    "acknowledgement": "acknowledgment", "acknowledgements": "acknowledgments",
    "aeroplane": "airplane", "aeroplanes": "airplanes", "ageing": "aging",
    "aluminium": "aluminum", "amongst": "among", "analogue": "analog", "analogues": "analogs",
    "artefact": "artifact", "artefacts": "artifacts", "benefitted": "benefited",
    "benefitting": "benefiting", "catalogue": "catalog", "catalogued": "cataloged",
    "catalogues": "catalogs", "cataloguing": "cataloging", "centre": "center",
    "centred": "centered", "centres": "centers", "centring": "centering", "cheque": "check",
    "cheques": "checks", "cosy": "cozy", "counsellor": "counselor", "counsellors": "counselors",
    "defence": "defense", "defences": "defenses", "disc": "disk", "discs": "disks",
    "enquiries": "inquiries", "enquiry": "inquiry", "enrol": "enroll", "enrolment": "enrollment",
    "enrolments": "enrollments", "enrols": "enrolls", "fibre": "fiber", "fibres": "fibers",
    "focussed": "focused", "focussing": "focusing", "fulfil": "fulfill",
    "fulfilment": "fulfillment", "fulfils": "fulfills", "grey": "gray", "greyed": "grayed",
    "greying": "graying", "greyish": "grayish", "greys": "grays", "greyscale": "grayscale",
    "instalment": "installment", "instalments": "installments", "jewellery": "jewelry",
    "judgement": "judgment", "judgements": "judgments", "learnt": "learned",
    "licence": "license", "licences": "licenses", "litre": "liter", "litres": "liters",
    "manoeuvre": "maneuver", "manoeuvres": "maneuvers", "metre": "meter", "metres": "meters",
    "mould": "mold", "moulds": "molds", "offence": "offense", "offences": "offenses",
    "practise": "practice", "practised": "practiced", "practises": "practices",
    "practising": "practicing", "programme": "program", "programmes": "programs",
    "queueing": "queuing", "sceptic": "skeptic", "sceptical": "skeptical",
    "skilful": "skillful", "speciality": "specialty", "spelt": "spelled", "sulphur": "sulfur",
    "targetted": "targeted", "targetting": "targeting", "theatre": "theater",
    "theatres": "theaters", "towards": "toward", "tyre": "tire", "tyres": "tires",
    "whilst": "while", "wilful": "willful",
}

_PROTECTED_PATH_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"(^|/)node_modules/",
    r"(^|/)dist/",
    r"(^|/)\.build/",
    r"(^|/)\.venv/",
    r"(^|/)vendor/",
    r"(^|/)__pycache__/",
    r"^client/Sources/Resources/[^/]+Assets/",
    r"\.lock$",
    r"(^|/)package-lock\.json$",
    r"(^|/)(LICENSE|LICENCE|NOTICE|COPYING)[^/]*$",
    r"^backend/src/api/services/whisper_live_core/whisper/normalizers/",
    r"^scripts/spelling/",
    r"^backend/src/tests/tooling_tests/test_american_spelling_policy\.py$",
    r"^backend/src/api/core/knowledge/sqlite/sqlite_knowledge_service_component_services/schema_management/american_spelling_migration\.py$",
    r"^backend/src/tests/core/knowledge_tests/test_american_spelling_migration\.py$",
))
_SCANNABLE_SUFFIXES = frozenset({
    ".py", ".pyi", ".swift", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss",
    ".html", ".md", ".mdc", ".txt", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".sh",
    ".zsh", ".sql", ".plist", ".strings", ".ini", ".cfg",
})
_SCANNABLE_NAMES = frozenset({"Makefile", "Dockerfile"})
_MAX_FILE_BYTES = 5 * 1024 * 1024

_GLOBAL_PROTECTED_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"CancelledError",
    r"[Ll]abelled[Bb]y",
    r"\blist-disc\b",
    r"list-style(?:-type)?\s*:\s*['\"]?disc\b",
    r"listStyle(?:Type)?\s*:\s*['\"]disc['\"]",
    r"stopReason['\"]?\]?\)?\s*(?:==|:)\s*['\"]cancelled['\"]",
    r"stop_reason\s*==\s*['\"]cancelled['\"]",
))
_SUFFIX_PROTECTED_PATTERNS = {
    ".py": tuple(re.compile(pattern) for pattern in (r"\.cancelled\(\)", r"\.cancelling\(\)")),
    ".swift": tuple(re.compile(pattern) for pattern in (
        r"\.isCancelled\b", r"\.cancelled\b", r"NSURLErrorCancelled", r"\.disc\b",
    )),
}
_PROTECTED_LINE_ANCHORS = {
    "backend/src/api/core/models/model_invocation.py": (
        'if normalized in {"cancelled", "canceled"}:',
    ),
    "backend/src/api/core/models/reasoning/streaming_contract.py": (
        'if reason in {"cancelled", "canceled"}:',
    ),
    "backend/src/api/services/agent_processing/lifecycle/submission/agent_task_processing/provider_activity_projector.py": (
        'elif status in ("completed", "failed", "cancelled"):',
    ),
    # "disc" here abbreviates "discussion", not the British spelling of "disk".
    "backend/src/api/services/agent_processing/lifecycle/submission/agent_task_submission_service.py": (
        'f"disc_{root_task_id[:8]}_',
    ),
    "client/Sources/App/LiveTranscription/Capture/LiveTranscriptionViewModel+ErrorHandling.swift": (
        'normalizedError.contains("operation cancelled")',
        'normalizedError.contains("cancelled")',
    ),
    "client/Sources/Services/APIClient/APIClient.swift": (
        'as "cancelled" (its own spelling, not ours)',
    ),
}

_TOKEN_PATTERN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_STRICT_CANCEL_PATTERN = re.compile(r"[Cc]ancell(?:ed|ing)|CANCELL(?:ED|ING)")
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL_BOUNDARY_PATTERN = re.compile(r"[a-z][A-Z]")


def _build_replacements() -> dict[str, str]:
    replacements: dict[str, str] = {}
    for stem in _IZE_STEMS:
        for british_suffix, american_suffix in _IZE_SUFFIXES:
            replacements[stem + british_suffix] = stem + american_suffix
    for stem in _YZE_STEMS:
        for british_suffix, american_suffix in _YZE_SUFFIXES:
            replacements[stem + british_suffix] = stem + american_suffix
    for word in _OUR_WORDS:
        american_word = word[:-3] + "or"
        for suffix in _OUR_SUFFIXES:
            replacements[word + suffix] = american_word + suffix
    for stem in _DOUBLED_L_STEMS:
        for british_suffix, american_suffix in _DOUBLED_L_SUFFIXES:
            replacements[stem + british_suffix] = stem + american_suffix
    replacements.update(_DIRECT_REPLACEMENTS)
    return replacements


BRITISH_TO_AMERICAN = _build_replacements()


@dataclass(frozen=True)
class SpellingFinding:
    path: str
    line: int
    column: int
    offset: int
    token: str
    replacement: str | None


def is_protected_path(relpath: str) -> bool:
    return any(pattern.search(relpath) for pattern in _PROTECTED_PATH_PATTERNS)


def is_scannable_path(relpath: str) -> bool:
    if is_protected_path(relpath):
        return False
    posix_path = PurePosixPath(relpath)
    return posix_path.suffix.lower() in _SCANNABLE_SUFFIXES or posix_path.name in _SCANNABLE_NAMES


def iter_repository_files(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    relpaths = sorted({relpath for relpath in completed.stdout.decode("utf-8").split("\0") if relpath})
    return [relpath for relpath in relpaths if is_scannable_path(relpath) and (repo_root / relpath).is_file()]


def read_text_preserving_newlines(path: Path) -> str | None:
    if path.stat().st_size > _MAX_FILE_BYTES:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError:
        return None


def write_text_preserving_newlines(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def americanize_token(token: str) -> str | None:
    american = BRITISH_TO_AMERICAN.get(token.lower())
    if american is None:
        return None
    if token.islower():
        return american
    if len(token) > 1 and token.isupper():
        return american.upper()
    if token[0].isupper() and token[1:].islower():
        return american[0].upper() + american[1:]
    return None


def protected_spans(relpath: str, text: str) -> list[tuple[int, int]]:
    spans = [match.span() for pattern in _GLOBAL_PROTECTED_PATTERNS for match in pattern.finditer(text)]
    suffix = PurePosixPath(relpath).suffix
    for pattern in _SUFFIX_PROTECTED_PATTERNS.get(suffix, ()):
        spans.extend(match.span() for match in pattern.finditer(text))
    anchors = _PROTECTED_LINE_ANCHORS.get(relpath, ())
    if anchors:
        offset = 0
        for line in text.splitlines(keepends=True):
            if any(anchor in line for anchor in anchors):
                spans.append((offset, offset + len(line)))
            offset += len(line)
    return sorted(spans)


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(span_start < end and start < span_end for span_start, span_end in spans)


def _line_starts(text: str) -> list[int]:
    return [0] + [match.end() for match in re.finditer("\n", text)]


def _position(line_starts: list[int], offset: int) -> tuple[int, int]:
    line_index = bisect.bisect_right(line_starts, offset) - 1
    return line_index + 1, offset - line_starts[line_index] + 1


def americanize_text(relpath: str, text: str) -> tuple[str, list[SpellingFinding]]:
    spans = protected_spans(relpath, text)
    line_starts = _line_starts(text)
    pieces: list[str] = []
    findings: list[SpellingFinding] = []
    cursor = 0
    for match in _TOKEN_PATTERN.finditer(text):
        replacement = americanize_token(match.group(0))
        if replacement is None or _overlaps(spans, match.start(), match.end()):
            continue
        line, column = _position(line_starts, match.start())
        findings.append(SpellingFinding(relpath, line, column, match.start(), match.group(0), replacement))
        pieces.append(text[cursor:match.start()])
        pieces.append(replacement)
        cursor = match.end()
    if not findings:
        return text, findings
    pieces.append(text[cursor:])
    return "".join(pieces), findings


def find_violations(relpath: str, text: str) -> list[SpellingFinding]:
    _, findings = americanize_text(relpath, text)
    spans = protected_spans(relpath, text)
    covered = [(finding.offset, finding.offset + len(finding.token)) for finding in findings]
    line_starts = _line_starts(text)
    for match in _STRICT_CANCEL_PATTERN.finditer(text):
        if _overlaps(spans, match.start(), match.end()) or _overlaps(covered, match.start(), match.end()):
            continue
        line, column = _position(line_starts, match.start())
        findings.append(SpellingFinding(relpath, line, column, match.start(), match.group(0), None))
    return sorted(findings, key=lambda finding: finding.offset)


def _americanize_word(word: str) -> str:
    return _TOKEN_PATTERN.sub(lambda match: americanize_token(match.group(0)) or match.group(0), word)


def compound_identifier_collisions(original: str, americanized: str) -> list[tuple[str, str]]:
    original_words = set(_WORD_PATTERN.findall(original))
    americanized_words = set(_WORD_PATTERN.findall(americanized))
    collisions: list[tuple[str, str]] = []
    for word in sorted(original_words - americanized_words):
        if "_" not in word and not _CAMEL_BOUNDARY_PATTERN.search(word):
            continue
        american_word = _americanize_word(word)
        if american_word != word and american_word in original_words:
            collisions.append((word, american_word))
    return collisions
