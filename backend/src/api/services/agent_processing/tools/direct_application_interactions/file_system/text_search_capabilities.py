"""Capability entries for the read-only text search tools, kept apart so the file service's own capability list stays readable."""

from __future__ import annotations

from typing import Any, Dict, List

READ_ONLY_TEXT_METHOD_CAPABILITIES: List[Dict[str, Any]] = [
    {
        "name": "search_text_in_files",
        "description": "Find which files under a folder mention any of some words or phrases, with the matching lines and line numbers. Read-only, needs no approval prompt, and skips node_modules and .git by default, so use it instead of a grep or find pipeline in the shell.",
        "slim_doc": (
            "Search the text of the files under a known absolute folder for any of several words or phrases (plain text, not a regular expression; case-insensitive unless case_sensitive is true). "
            "Returns each matching line with its file path and line number, plus the list of files that matched. "
            "Narrow the files with file_globs such as [\"*.md\", \"*.ts\"] (matched against file names). "
            "Generated folders such as node_modules, .git, .venv, dist, and build are skipped unless include_generated_directories is true, and the result names every folder it skipped. "
            "It reads only: it never changes a file, follows symbolic links, or reads binary files or files over 2 MiB, and the result says when a limit cut it short. "
            "Use this instead of grep -r or find | grep in the shell, which can need an approval prompt. To read one whole file or a range of it, use read_text_file."
        ),
        "parameters": [
            {"name": "directory", "type": "str", "required": True, "description": "Absolute path of the folder to search, or a path starting with ~/."},
            {"name": "terms", "type": "List[str]", "required": True, "description": "Words or phrases to look for; a line matches if it contains any one of them. At most 20."},
            {"name": "file_globs", "type": "List[str]", "required": False, "description": "Optional file-name patterns such as *.md or *.tsx; only matching files are searched."},
            {"name": "case_sensitive", "type": "bool", "required": False, "description": "True to match capitalization exactly. Defaults to false."},
            {"name": "max_matches", "type": "int", "required": False, "description": "Most matching lines to return, from 1 to 500. Defaults to 100."},
            {"name": "include_generated_directories", "type": "bool", "required": False, "description": "True to also search node_modules, .git, .venv, dist, build, and similar folders. Defaults to false."},
        ],
        "returns": "Dict with success, matches (path, line_number, line), files_with_matches, files_visited, truncated and truncation_reason, and skipped counts including generated_directories_skipped.",
    },
    {
        "name": "list_files_in_folder",
        "description": "List the files under a folder, optionally only those whose names match patterns such as *.md. Read-only, needs no approval prompt, and skips node_modules and .git by default, so use it instead of a find command in the shell.",
        "slim_doc": (
            "List the files under a known absolute folder, with each file's size and modified time. "
            "Pass name_globs such as [\"*.md\", \"*.html\"] to keep only files whose names match (case-insensitive). "
            "Generated folders such as node_modules, .git, .venv, dist, and build are skipped unless include_generated_directories is true, and the result names every folder it skipped. "
            "It reads only, and the result says when a limit cut it short. "
            "Use this instead of find in the shell. To search inside the files use search_text_in_files, and to read one use read_text_file."
        ),
        "parameters": [
            {"name": "directory", "type": "str", "required": True, "description": "Absolute path of the folder to list, or a path starting with ~/."},
            {"name": "name_globs", "type": "List[str]", "required": False, "description": "Optional file-name patterns such as *.md; only matching files are listed."},
            {"name": "max_results", "type": "int", "required": False, "description": "Most files to list, from 1 to 1000. Defaults to 200."},
            {"name": "include_generated_directories", "type": "bool", "required": False, "description": "True to also list files inside node_modules, .git, .venv, dist, build, and similar folders. Defaults to false."},
        ],
        "returns": "Dict with success, files (path, size_bytes, modified), total_listed, files_visited, truncated and truncation_reason, and skipped counts including generated_directories_skipped.",
    },
    {
        "name": "read_text_file",
        "description": "Read a range of lines from one UTF-8 text file. Read-only and needs no approval prompt, so use it instead of cat, head, tail, or sed in the shell.",
        "slim_doc": (
            "Read the text of one existing UTF-8 file at a known absolute path, from start_line for up to max_lines lines (default 400, at most 1000). "
            "Returns the raw text without line numbers, the line range returned, the file's total line count, and next_start_line when the file continues. "
            "It also returns the file's SHA-256, which you can pass as expected_sha256 to edit_text_file or write_text_file so a later change is refused if the file changed in between. "
            "Binary files and files over 2 MiB are refused. "
            "Use this instead of cat, head, tail, or sed in the shell. To find which file or line to read, use search_text_in_files or list_files_in_folder first."
        ),
        "parameters": [
            {"name": "path", "type": "str", "required": True, "description": "Absolute path of the text file, or a path starting with ~/."},
            {"name": "start_line", "type": "int", "required": False, "description": "First line to return, counting from 1. Defaults to 1."},
            {"name": "max_lines", "type": "int", "required": False, "description": "Most lines to return, from 1 to 1000. Defaults to 400."},
        ],
        "returns": "Dict with success, path, text, start_line, end_line, total_lines, truncated, next_start_line, and sha256; on failure error_type and error say why.",
    },
]
