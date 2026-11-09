"""Twenty fixed tool-call cases used identically for both engines.

A case passes when the model output contains exactly one parsable <tool_call> block (a JSON object, or the XML form <function=NAME><parameter=KEY>VALUE</parameter></function> that the Qwen3.5 and Qwen3.6 chat templates use) (or none, for no-tool cases), the tool name is correct, every expected argument matches, and no argument outside the schema is invented.
Matching rules for an expected argument value: a str means the argument, lowercased and stripped, must contain it as a substring; an int or float means numeric equality; a bool means equality.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {"name": "get_weather", "description": "Get the current weather for a city.", "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "send_email", "description": "Send an email on the user's behalf.", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}},
    {"type": "function", "function": {"name": "create_calendar_event", "description": "Create a calendar event.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "start_iso": {"type": "string", "description": "ISO 8601 start time"}, "duration_minutes": {"type": "integer"}, "attendees": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "start_iso", "duration_minutes"]}}},
    {"type": "function", "function": {"name": "search_files", "description": "Search local files by name or content.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "directory": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "set_reminder", "description": "Set a reminder.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "when": {"type": "string", "description": "Natural-language or ISO time"}}, "required": ["text", "when"]}}},
    {"type": "function", "function": {"name": "calculate", "description": "Evaluate an arithmetic expression exactly.", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file from disk.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "recency_days": {"type": "integer"}}, "required": ["query"]}}},
]

SYSTEM = "You are a careful assistant with access to tools. Call a tool only when the request needs one. Today is Tuesday, 2026-11-03."

# (case_id, user message, expected tool name or None, expected args)
CASES: List[Tuple[str, str, Optional[str], Dict[str, Any]]] = [
    ("tc-01", "What's the weather in Lisbon right now?", "get_weather", {"city": "lisbon"}),
    ("tc-02", "Tell me the temperature in Chicago in fahrenheit.", "get_weather", {"city": "chicago", "unit": "fahrenheit"}),
    ("tc-03", "Email priya@example.com with the subject 'Q4 plan' and say the draft is attached for review.", "send_email", {"to": "priya@example.com", "subject": "q4 plan", "body": "draft"}),
    ("tc-04", "Send a note to dan@example.org titled Lunch saying I can do noon on Thursday.", "send_email", {"to": "dan@example.org", "subject": "lunch", "body": "noon"}),
    ("tc-05", "Put a 45 minute 'Design review' on my calendar for 2026-11-05 at 14:00.", "create_calendar_event", {"title": "design review", "start_iso": "2026-11-05t14:00", "duration_minutes": 45}),
    ("tc-06", "Schedule an hour-long call called Vendor sync on 2026-11-09 at 09:30 with sam@example.com.", "create_calendar_event", {"title": "vendor sync", "start_iso": "2026-11-09t09:30", "duration_minutes": 60}),
    ("tc-07", "Find files that mention 'invoice 4471' in my Documents folder.", "search_files", {"query": "invoice 4471", "directory": "documents"}),
    ("tc-08", "Search for the file named budget_2027.xlsx.", "search_files", {"query": "budget_2027"}),
    ("tc-09", "Remind me to call the dentist tomorrow at 8am.", "set_reminder", {"text": "dentist", "when": "tomorrow"}),
    ("tc-10", "Set a reminder to submit the expense report on Friday afternoon.", "set_reminder", {"text": "expense report", "when": "friday"}),
    ("tc-11", "What is 48213 times 377? Use the calculator, I need it exact.", "calculate", {"expression": "48213"}),
    ("tc-12", "Compute (1250 + 375) / 13 exactly.", "calculate", {"expression": "1250"}),
    ("tc-13", "Open /Users/me/notes/standup.txt and show me what's in it.", "read_file", {"path": "/users/me/notes/standup.txt"}),
    ("tc-14", "Read the file ~/todo.md.", "read_file", {"path": "todo.md"}),
    ("tc-15", "Look up the latest news about the Basil open source release from the last 7 days.", "web_search", {"query": "basil", "recency_days": 7}),
    ("tc-16", "Search the web for the boiling point of ethanol.", "web_search", {"query": "ethanol"}),
    ("tc-17", "Say hello and tell me what you can help with.", None, {}),
    ("tc-18", "Explain in one sentence what an API is.", None, {}),
    ("tc-19", "Thanks, that's all for now.", None, {}),
    ("tc-20", "I'm in Osaka. Check the weather there in celsius, and keep it short.", "get_weather", {"city": "osaka", "unit": "celsius"}),
]

CALL_BLOCK = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
XML_FUNCTION = re.compile(r"^<function=([^>\s]+)>\s*(.*?)\s*</function>$", re.DOTALL)
XML_PARAMETER = re.compile(r"<parameter=([^>\s]+)>\s*(.*?)\s*</parameter>", re.DOTALL)


def parse_call(block: str) -> Optional[Dict[str, Any]]:
    """Parse one <tool_call> body in either supported form; None when it is neither."""
    if block.startswith("{"):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    match = XML_FUNCTION.match(block)
    if match is None:
        return None
    return {"name": match.group(1), "arguments": {key: value for key, value in XML_PARAMETER.findall(match.group(2))}}


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    return str(expected).lower() in str(actual).strip().lower()


def score(case_id: str, output: str) -> Dict[str, Any]:
    """Score one model output against its case. Returns parse_ok, name_ok, args_ok, no_extra_args, and passed."""
    _, _, expected_tool, expected_args = next(c for c in CASES if c[0] == case_id)
    calls = CALL_BLOCK.findall(output)
    if expected_tool is None:
        passed = len(calls) == 0
        return {"case": case_id, "parse_ok": passed, "name_ok": passed, "args_ok": passed, "no_extra_args": passed, "passed": passed, "calls": len(calls)}
    if len(calls) != 1:
        return {"case": case_id, "parse_ok": False, "name_ok": False, "args_ok": False, "no_extra_args": False, "passed": False, "calls": len(calls)}
    payload = parse_call(calls[0])
    if payload is None:
        return {"case": case_id, "parse_ok": False, "name_ok": False, "args_ok": False, "no_extra_args": False, "passed": False, "calls": 1}
    name = payload.get("name")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    schema = next(t["function"]["parameters"]["properties"] for t in TOOLS if t["function"]["name"] == expected_tool)
    name_ok = name == expected_tool
    args_ok = name_ok and all(key in arguments and _matches(value, arguments[key]) for key, value in expected_args.items())
    no_extra = name_ok and all(key in schema for key in arguments)
    return {"case": case_id, "parse_ok": True, "name_ok": name_ok, "args_ok": args_ok, "no_extra_args": no_extra, "passed": name_ok and args_ok and no_extra, "calls": 1}
