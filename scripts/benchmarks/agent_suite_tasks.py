"""The ten fixture tasks for the agent suite. Every task works only inside one temporary directory (or the isolated profile's own database), and every verifier checks the real outcome on disk or in that database, not the model's description of it.

A task is created fresh for each run: `build(workdir, marker)` writes its fixture and returns a context dict, `prompt(ctx)` renders the request, and `verify(ctx, answer, receipts)` returns (passed, detail). `receipts` is the set of (service, method) pairs the work ledger recorded for the run.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Set, Tuple

Receipts = Set[Tuple[str, str]]
Verdict = Tuple[bool, str]


@dataclass(frozen=True)
class SuiteTask:
    task_id: str
    family: str
    title: str
    build: Callable[[Path, str, random.Random], Dict[str, Any]]
    prompt: Callable[[Dict[str, Any]], str]
    verify: Callable[[Dict[str, Any], str, Receipts], Verdict]
    expected_services: Tuple[str, ...] = ()


def _numbers_in(text: str) -> list[str]:
    return [token.replace(",", "") for token in re.findall(r"\d[\d,]*\.?\d*", text)]


def _contains_number(answer: str, expected: str) -> bool:
    cleaned = answer.replace(",", "")
    return re.search(rf"(?<![\d.]){re.escape(expected)}(?![\d])", cleaned) is not None


def _used(receipts: Receipts, service: str) -> bool:
    return any(item[0] == service for item in receipts)


def _build_codename(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    code = f"HELIOTROPE-{rng.randint(1000, 9999)}"
    (workdir / "notes.txt").write_text(f"Meeting notes\nbudget approved\ncodename: {code}\nnext review in March\n", encoding="utf-8")
    return {"dir": workdir, "code": code}


def _verify_codename(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    ok = ctx["code"] in answer
    return ok, "codename reported" if ok else f"codename {ctx['code']} not in the answer"


def _build_search(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    target_index = rng.randrange(6)
    target_invoice = f"{rng.randint(10000, 99999)}-X"
    names = [f"memo_{letter}.txt" for letter in "abcdef"]
    for index, name in enumerate(names):
        invoice = target_invoice if index == target_index else f"{rng.randint(10000, 99999)}-Y"
        (workdir / name).write_text(f"Memo {name}\nReference invoice {invoice} was reviewed.\nNo further action.\n", encoding="utf-8")
    return {"dir": workdir, "invoice": target_invoice, "target": names[target_index], "names": names}


def _verify_search(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    named = [name for name in ctx["names"] if name in answer]
    ok = named == [ctx["target"]]
    return ok, f"answer named {named}, expected {ctx['target']}"


def _build_write(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    items = rng.sample(["milk", "eggs", "flour", "butter", "rice", "salt", "honey", "yeast"], 3)
    return {"dir": workdir, "items": items}


def _verify_write(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    target = ctx["dir"] / "shopping.txt"
    if not target.is_file():
        return False, "shopping.txt was not created"
    lines = [line.strip() for line in target.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
    return lines == ctx["items"], f"file lines {lines}, expected {ctx['items']}"


def _build_move(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    body = f"Quarterly report {marker}\nrevenue {rng.randint(100, 999)}\n"
    (workdir / "report.txt").write_text(body, encoding="utf-8")
    return {"dir": workdir, "body": body}


def _verify_move(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    moved = ctx["dir"] / "archive" / "report-final.txt"
    if not moved.is_file():
        return False, "archive/report-final.txt does not exist"
    if (ctx["dir"] / "report.txt").exists():
        return False, "report.txt is still in the original place (copied, not moved)"
    return moved.read_text(encoding="utf-8") == ctx["body"], "content preserved" if moved.read_text(encoding="utf-8") == ctx["body"] else "content changed"


def _build_count(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    rows = rng.randint(120, 180)
    lines = ["id,name,amount"] + [f"{i},item{i},{rng.randint(1, 9999) / 100:.2f}" for i in range(1, rows + 1)]
    (workdir / "data.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"dir": workdir, "line_count": rows + 1}


def _verify_count(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    ok = _contains_number(answer, str(ctx["line_count"]))
    return ok, f"expected {ctx['line_count']}, answer numbers {_numbers_in(answer)[:6]}"


def _build_sum(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    cents = [rng.randint(100, 99999) for _ in range(rng.randint(40, 70))]
    lines = ["id,name,amount"] + [f"{i},item{i},{c / 100:.2f}" for i, c in enumerate(cents, start=1)]
    (workdir / "data.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"dir": workdir, "total": f"{sum(cents) / 100:.2f}"}


def _verify_sum(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    ok = _contains_number(answer, ctx["total"])
    return ok, f"expected {ctx['total']}, answer numbers {_numbers_in(answer)[:6]}"


def _build_tree(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    return {"dir": workdir}


def _verify_tree(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    target = ctx["dir"] / "out" / "a" / "b" / "ok.txt"
    if not target.is_file():
        return False, "out/a/b/ok.txt does not exist"
    return target.read_text(encoding="utf-8").strip() == "done", f"ok.txt holds {target.read_text(encoding='utf-8').strip()!r}"


def _build_applescript(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    a, b, c = rng.randint(12, 49), rng.randint(12, 49), rng.randint(100, 999)
    return {"dir": workdir, "expr": f"{a} * {b} + {c}", "result": str(a * b + c)}


def _verify_applescript(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    right = _contains_number(answer, ctx["result"])
    used = _used(receipts, "applescript_service")
    return right and used, f"result correct={right}, AppleScript tool used={used}"


def _build_schedule(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    return {"dir": workdir, "marker": marker}


def _verify_schedule_factory(db_path: Path) -> Callable[[Dict[str, Any], str, Receipts], Verdict]:
    def verify(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT title, agent_task_text, schedule_type, schedule_config, next_run_at FROM scheduled_agent_tasks WHERE title LIKE ? OR agent_task_text LIKE ?",
                (f"%{ctx['marker']}%", f"%{ctx['marker']}%"),
            ).fetchall()
        if not rows:
            return False, "no scheduled task with the run marker exists"
        title, text, schedule_type, config, next_run = rows[0]
        one_time = schedule_type == "one_time"
        nine = re.search(r"\b0?9[:\"]?(?:00)?", config or "") is not None or (next_run or "")[11:13] in {"09", "14", "13"}
        return one_time and nine and len(rows) == 1, f"rows={len(rows)} type={schedule_type} config={config} next_run={next_run}"

    return verify


def _build_inventory(workdir: Path, marker: str, rng: random.Random) -> Dict[str, Any]:
    items = [{"name": f"part{i}", "qty": rng.randint(1, 20), "price": rng.randint(100, 5000) / 100, "in_stock": rng.random() > 0.35} for i in range(1, rng.randint(9, 14))]
    (workdir / "inventory.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
    total = sum(round(item["qty"] * item["price"] * 100) for item in items if item["in_stock"]) / 100
    return {"dir": workdir, "total": f"{total:.2f}"}


def _verify_inventory(ctx: Dict[str, Any], answer: str, receipts: Receipts) -> Verdict:
    target = ctx["dir"] / "total.txt"
    in_file = target.is_file() and _contains_number(target.read_text(encoding="utf-8"), ctx["total"])
    in_answer = _contains_number(answer, ctx["total"])
    return in_file and in_answer, f"expected {ctx['total']}; file ok={in_file}; answer ok={in_answer}"


def build_tasks(knowledge_db_path: Path) -> list[SuiteTask]:
    d = lambda ctx: str(ctx["dir"])  # noqa: E731
    return [
        SuiteTask("T01", "file", "Read a file and report one value", _build_codename, lambda c: f"Read the file {d(c)}/notes.txt and tell me the project codename it contains.", _verify_codename, ("file_service",)),
        SuiteTask("T02", "file", "Find which of six files mentions an invoice", _build_search, lambda c: f"Six memo files are in {d(c)}. Which one mentions invoice number {c['invoice']}? Answer with just the file name.", _verify_search, ("file_service",)),
        SuiteTask("T03", "file", "Create a file with exact contents", _build_write, lambda c: f"Create a file named shopping.txt in {d(c)} that contains exactly these three lines, one per line: {c['items'][0]}, {c['items'][1]}, {c['items'][2]}.", _verify_write, ("file_service",)),
        SuiteTask("T04", "file", "Move and rename a file into a new folder", _build_move, lambda c: f"In {d(c)}, move report.txt into a new folder named archive and rename it report-final.txt. Do not leave a copy behind.", _verify_move, ("file_service",)),
        SuiteTask("T05", "shell", "Count the lines of a file with the shell", _build_count, lambda c: f"Use the shell to count how many lines are in {d(c)}/data.csv, header included, and tell me the number.", _verify_count, ("shell_service",)),
        SuiteTask("T06", "shell", "Sum a CSV column with the shell", _build_sum, lambda c: f"Using the shell, add up the amount column of {d(c)}/data.csv (skip the header) and tell me the total to two decimal places.", _verify_sum, ("shell_service",)),
        SuiteTask("T07", "shell", "Create nested folders and a file with the shell", _build_tree, lambda c: f"Using the shell, create the nested folders {d(c)}/out/a/b and write the word done into a file named ok.txt inside the innermost folder.", _verify_tree, ("shell_service",)),
        SuiteTask("T08", "automation", "Compute a value with AppleScript", _build_applescript, lambda c: f"Use AppleScript, not the shell, to calculate {c['expr']} and tell me the result.", _verify_applescript, ("applescript_service",)),
        SuiteTask("T09", "schedule", "Create a one-time scheduled task", _build_schedule, lambda c: f"Schedule a one-time task titled 'Suite {c['marker']} reminder' for tomorrow at 9:00 AM that says: check the {c['marker']} fixture.", _verify_schedule_factory(knowledge_db_path)),
        SuiteTask("T10", "multi_step", "Read JSON, compute, write a file, and report", _build_inventory, lambda c: f"Read {d(c)}/inventory.json. Add up quantity times price for only the items that are in stock, write the total to two decimal places into a new file named total.txt in {d(c)}, and tell me the total.", _verify_inventory, ("file_service",)),
    ]
