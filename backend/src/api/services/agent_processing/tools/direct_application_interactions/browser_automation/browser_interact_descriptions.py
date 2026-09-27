"""Descriptions for the browser_interact tool."""

# Why this slim:
# - KEEPS: the per-action 'requires value' truth-table because the schema's
#   action Literal enumerates the actions but the agent will not otherwise
#   know which actions need 'value' (fill/select), selector/URL, or selectorless
#   page waiting; the navigate-uses-selector-for-URL invariant since
#   it is the most common shape mistake; the SAFETY block (login + CAPTCHA
#   = STOP and request_user_input) because it is a non-negotiable safety
#   invariant not in the system prompt; the don't-guess-selectors rule (the
#   companion to browser_inspect's slim).
# - DROPS: the iterative-workflow numbered list (subsumed by the slim
#   inspect-before-interact rule); per-call usage examples (the action
#   Literal + selector/value Pydantic descriptions cover them); OUTPUT
#   shape (a single result teaches the JSON layout); 'after clicking, call
#   browser_inspect' (already in browser_inspect's slim).
SLIM_DESCRIPTION = (
    "Perform a single action on a web page element in the user's existing "
    "browser session. Actions: click (no value), fill (value=text), select "
    "(value=option), navigate (selector=URL, no value), scroll (no value), "
    "wait (selector optional: omit selector for page readiness, or provide a "
    "selector to wait for a visible element). Use selectors from browser_inspect; "
    "do NOT guess. Use browser_automation_target from browser_tabs.ensure_automation_window "
    "when available. Leave 'browser' empty to auto-detect. SAFETY: login forms "
    "and CAPTCHAs - STOP, do NOT fill credentials or attempt to solve, call "
    "request_user_input to ask the user to complete authentication / CAPTCHA "
    "manually, then resume once they confirm."
)

FULL_DESCRIPTION = """Perform an action on a web page element in the user's browser.

**CAPABILITIES:**
- Click buttons and links.
- Fill form inputs with text.
- Select dropdown options.
- Navigate to URLs.
- Scroll to elements.
- Wait for elements to appear, or wait for page readiness when selector is omitted.
- Works with Safari, Chrome, and Edge.
- Auto-detects the user's default browser if not specified.
- Uses the user's existing browser session (preserves login state and credentials).
- Accepts browser_automation_target from browser_tabs.ensure_automation_window to act on
  Basil's dedicated tab instead of whichever browser tab is active.

**WHEN TO USE:**
- AFTER calling browser_inspect to identify the correct selector.
- To click buttons, fill forms, or navigate pages.
- As part of an iterative workflow with browser_inspect.

**ITERATIVE WORKFLOW (CRITICAL):**
1. First: browser_inspect() to find selectors.
2. Then: browser_interact() with a selector from step 1.
3. Then: browser_inspect() to verify the action worked.
4. If verification fails, adjust approach and retry (max 3 attempts per step).

**SUPPORTED ACTIONS:**
| Action | Description | Requires value |
|--------|-------------|----------------|
| click | Click element | No |
| fill | Type text into input | Yes |
| select | Choose dropdown option | Yes |
| navigate | Go to URL | Yes (URL as selector) |
| scroll | Scroll element into view | No |
| wait | Wait for page readiness if selector is omitted; wait for visible element if selector is provided | No |

**USAGE EXAMPLES:**
- browser_interact(action="click", selector="#add-to-cart") - auto-detect browser
- browser_interact(action="fill", selector="#search-box", value="search term")
- browser_interact(action="navigate", selector="https://example.com")
- browser_interact(action="wait") - wait for page readiness after navigation
- browser_interact(action="wait", selector="#results") - wait for a visible element
- browser_interact(browser="Edge", action="click", selector="#submit") - explicit browser

**OUTPUT:**
Returns JSON with:
- `success`: Whether action completed.
- `action`: Action performed.
- `browser`: Which browser was used (helpful when auto-detected).
- `newUrl`: Current URL after action.
- `newTitle`: Page title after action.
- `error`: Error message if failed.

**SAFETY (non-negotiable):**
- For login forms: STOP immediately. Do NOT fill any credential fields. Call
  request_user_input to notify the user that a login is required and ask them
  to authenticate manually before you continue.
- For CAPTCHAs: STOP immediately. Call request_user_input to ask the user to
  complete the CAPTCHA manually, then resume once they confirm it is done.
  Never attempt to bypass or solve CAPTCHAs programmatically.

**IMPORTANT:**
- Leave browser empty to auto-detect the user's default browser (recommended).
- NEVER guess selectors - always get them from browser_inspect first.
- After clicking, call browser_inspect to see the new page state.
- If element not found, call browser_inspect to find alternatives.
"""

