"""Helpers for turning browser tabs into checkpoint selection options."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .browser_safety import normalize_domain_from_url


def build_browser_session_options(tabs_result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Build checkpoint-compatible options from a browser_tabs list result."""
    browser = str(tabs_result.get("browser") or "Browser")
    tabs = tabs_result.get("tabs")
    if not isinstance(tabs, list):
        return []

    options: List[Dict[str, Any]] = []
    for index, tab in enumerate(tabs):
        if not isinstance(tab, Mapping):
            continue
        title = str(tab.get("title") or "Untitled")
        url = str(tab.get("url") or "")
        domain = normalize_domain_from_url(url)
        window_index = tab.get("window_index", 1)
        tab_index = tab.get("tab_index", index + 1)
        label = " - ".join(part for part in [browser, title, domain] if part)
        value = {
            "browser": browser,
            "window_index": window_index,
            "tab_index": tab_index,
            "url": url,
            "title": title,
        }
        options.append({
            "id": f"{browser.lower()}-{window_index}-{tab_index}",
            "label": label,
            "value": value,
            "description": url,
        })

    return options

