"""Thirty fixed prompts with programmatic checks, used identically for both engines.

Each check is deterministic code, so no judge model is involved. The set measures whether a speed win hides a basic capability loss. It is not a broad quality benchmark.
"""
from __future__ import annotations

import json
import re
from typing import Callable, List, Tuple


def _has(*needles: str) -> Callable[[str], bool]:
    return lambda out: all(n.lower() in out.lower() for n in needles)


def _number(expected: str) -> Callable[[str], bool]:
    return lambda out: expected in out.replace(",", "")


def _json_keys(*keys: str) -> Callable[[str], bool]:
    def check(out: str) -> bool:
        match = re.search(r"\{.*\}", out, re.DOTALL)
        if not match:
            return False
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False
        return isinstance(data, dict) and all(k in data for k in keys)

    return check


def _bullets(count: int) -> Callable[[str], bool]:
    return lambda out: len([line for line in out.splitlines() if re.match(r"^\s*[-*\u2022]\s+\S", line)]) == count


def _words_at_most(limit: int) -> Callable[[str], bool]:
    return lambda out: 0 < len(out.split()) <= limit


def _starts_with(prefix: str) -> Callable[[str], bool]:
    return lambda out: out.strip().lower().startswith(prefix.lower())


def _no_letter(letter: str) -> Callable[[str], bool]:
    return lambda out: letter.lower() not in out.lower() and len(out.strip()) > 0


# (prompt_id, category, prompt, check)
CASES: List[Tuple[str, str, str, Callable[[str], bool]]] = [
    ("q-01", "arithmetic", "What is 17 * 23? Answer with just the number.", _number("391")),
    ("q-02", "arithmetic", "What is 1000 - 387? Answer with just the number.", _number("613")),
    ("q-03", "arithmetic", "A train travels 60 miles per hour for 2.5 hours. How many miles? Answer with just the number.", _number("150")),
    ("q-04", "arithmetic", "What is 15% of 240? Answer with just the number.", _number("36")),
    ("q-05", "arithmetic", "What is the sum of the integers from 1 to 20? Answer with just the number.", _number("210")),
    ("q-06", "arithmetic", "What is 144 divided by 12, plus 7? Answer with just the number.", _number("19")),
    ("q-07", "factual", "What is the capital of Australia? One word.", _has("canberra")),
    ("q-08", "factual", "Which planet is known as the Red Planet? One word.", _has("mars")),
    ("q-09", "factual", "What is the chemical symbol for gold? One word.", _has("au")),
    ("q-10", "factual", "Who wrote the play Hamlet? Short answer.", _has("shakespeare")),
    ("q-11", "factual", "How many sides does a hexagon have? Answer with just the number.", _number("6")),
    ("q-12", "factual", "What is the largest ocean on Earth? One or two words.", _has("pacific")),
    ("q-13", "format", "List exactly three fruits as a bulleted list with a dash at the start of each line and nothing else.", _bullets(3)),
    ("q-14", "format", "List exactly five colors as a bulleted list using dashes and nothing else.", _bullets(5)),
    ("q-15", "format", "Return a JSON object with the keys name and age for a fictional person. Output only the JSON.", _json_keys("name", "age")),
    ("q-16", "format", "Return a JSON object with the keys city, country, and population for any city. Output only the JSON.", _json_keys("city", "country", "population")),
    ("q-17", "format", "Describe the ocean in at most 12 words.", _words_at_most(12)),
    ("q-18", "format", "Answer with a sentence that starts with the word 'Indeed': is water wet?", _starts_with("indeed")),
    ("q-19", "format", "Write one sentence about cats that does not use the letter 'z'.", _no_letter("z")),
    ("q-20", "format", "Reply with exactly the single word: ready", lambda out: out.strip().strip(".!").lower() == "ready"),
    ("q-21", "reasoning", "Tom is taller than Sam. Sam is taller than Lee. Who is the shortest? One word.", _has("lee")),
    ("q-22", "reasoning", "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies? Answer yes or no.", _has("yes")),
    ("q-23", "reasoning", "I have 3 apples, eat one, then buy 5 more. How many apples do I have? Answer with just the number.", _number("7")),
    ("q-24", "reasoning", "What comes next in the sequence 2, 4, 8, 16? Answer with just the number.", _number("32")),
    ("q-25", "reasoning", "Today is Tuesday. What day of the week is it in 10 days? One word.", _has("friday")),
    ("q-26", "extraction", "From the text 'Invoice 8841 is due on 2026-12-15 for $1,250.00', give the invoice number only.", _number("8841")),
    ("q-27", "extraction", "From the text 'Invoice 8841 is due on 2026-12-15 for $1,250.00', give the due date only.", _has("2026-12-15")),
    ("q-28", "extraction", "From the text 'Meet Alice Chen at the Boston office at 3pm', give the person's full name only.", _has("alice chen")),
    ("q-29", "extraction", "From the text 'Contact: support@example.com or call 555-0134', give the email address only.", _has("support@example.com")),
    ("q-30", "extraction", "Translate to French: 'Good morning'. Give just the translation.", lambda out: "bonjour" in out.lower()),
]
