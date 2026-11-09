"""Descriptions for the browser_interact tool."""

# Why this slim:
# - KEEPS: the per-action 'requires value' truth-table because the schema's
#   action Literal enumerates the actions but the agent will not otherwise
#   know which actions need 'value' (fill/select), selector/URL, or selectorless
#   page waiting; the navigate-uses-selector-for-URL invariant since
#   it is the most common shape mistake; the SAFETY block (login = hand the
#   page to the user; CAPTCHA = text-image only, everything else to the user) because it is a non-negotiable safety
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
    "when available. Leave 'browser' empty to auto-detect. More actions: fill_form "
    "(fields={selector: value}; fills several fields, then reads them back), capture_captcha and "
    "submit_captcha (value=the characters; only for type-the-characters image CAPTCHAs). A click waits "
    "for the page to settle and returns a `page` summary (url, title, headings, error messages, "
    "challenge); outcome_unknown means the action may have happened, so never repeat it blindly. SAFETY: login forms - STOP, do NOT fill credentials; call browser_tabs with action "
    "request_human_help so the user can sign in. CAPTCHAs: when browser_inspect reports challenge.kind "
    "text_image, call capture_captcha, read the saved image with analyze_with_vision, then "
    "submit_captcha, at most twice. For any other challenge (recaptcha, hcaptcha, turnstile, picture "
    "grids, sliders, bot interstitials) never attempt it; call browser_tabs with action request_human_help."
)

FULL_DESCRIPTION = """Perform an action on a web page element in the user's browser.

**CAPABILITIES:**
- Click buttons and links.
- Fill form inputs with text.
- Select dropdown options.
- Navigate to URLs.
- Scroll to elements.
- Wait for elements to appear, or wait for page readiness when selector is omitted.
- Fill several fields in one call with fill_form, and read the values back.
- Solve a simple type-the-characters image CAPTCHA with capture_captcha, analyze_with_vision and submit_captcha.
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
| fill_form | Fill several fields: pass `fields` as an object of selector to value (max 25). Stops at the first failure and reads the values back | No (use `fields`) |
| capture_captcha | Save the CAPTCHA image to a file and return its path. Only when browser_inspect shows challenge.kind text_image | No |
| submit_captcha | Type the characters into the CAPTCHA box and submit. At most 2 attempts per site, then ask the user | Yes (the characters) |

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
- `settled`, `navigated`, `page`: for click, whether the page stopped changing, whether the URL or title changed, and a summary of where the browser ended up (`url`, `title`, `headings`, `messages` with visible error text, and `challenge`). Read this instead of calling browser_inspect when you only need to know what happened.
- `outcome_unknown`: the page was navigating while the action ran; the action may have taken effect and was not repeated.
- `page_state`, `hint`: on a not-found error, what the page shows now (title, text excerpt, similar selectors, any challenge) and what to do next.
- `readback`: for fill_form, each filled field's value after filling (secrets show as `[hidden]`).
- `error`: Error message if failed.

**SAFETY (non-negotiable):**
- For login forms: STOP immediately. Do NOT fill any credential fields. Call
  browser_tabs with action request_human_help so the user can sign in in the
  browser window, then confirm with browser_inspect that the login is gone.
- For a type-the-characters image CAPTCHA (browser_inspect shows challenge.kind
  text_image): call capture_captcha, read the saved image with analyze_with_vision
  (reply with only the characters, or UNREADABLE), then call submit_captcha with
  exactly those characters. You get at most 2 attempts per site. If the image is
  unreadable or the attempts are used up, call browser_tabs with action
  request_human_help.
- For every other challenge (reCAPTCHA, hCaptcha, Turnstile, picture grids,
  sliders, bot-block pages): never attempt it. Call browser_tabs with action
  request_human_help.

**IMPORTANT:**
- Leave browser empty to auto-detect the user's default browser (recommended).
- NEVER guess selectors - always get them from browser_inspect first.
- A click already returns a `page` summary. Call browser_inspect after it only when you need selectors for the next step.
- If element not found, call browser_inspect to find alternatives.
"""

