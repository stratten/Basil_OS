"""Run the in-page browser_inspect JavaScript against real DOM fixtures with jsdom."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_captcha,
    browser_challenge_js,
    browser_inspect_extensions,
    browser_inspect_tool,
    browser_interact_batch,
    browser_interact_diagnostics,
    browser_interact_tool,
    browser_page_settle,
    browser_safety,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
NODE = shutil.which("node")
JSDOM_CANDIDATES = sorted(REPO_ROOT.glob("web-components/*/node_modules/jsdom"))

pytestmark = pytest.mark.skipif(
    NODE is None or not JSDOM_CANDIDATES,
    reason="Node.js with jsdom (web-components/*/node_modules/jsdom) is required",
)

_NODE_RUNNER = r'''
const fs = require('fs');
const { JSDOM } = require(process.env.JSDOM_PATH);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const dom = new JSDOM(input.html, { runScripts: 'outside-only', pretendToBeVisual: true, url: input.url });
const window = dom.window;
window.Element.prototype.getBoundingClientRect = function () {
  const size = this.getAttribute && this.getAttribute('data-test-size');
  if (size) {
    const parts = size.split('x').map(Number);
    return { width: parts[0], height: parts[1], top: 0, left: 0, right: parts[0], bottom: parts[1] };
  }
  return { width: 100, height: 20, top: 0, left: 0, right: 100, bottom: 20 };
};
Object.defineProperty(window.HTMLElement.prototype, 'innerText', { get() { return this.textContent; }, configurable: true });
(async () => {
  if (window.document.readyState !== 'complete') {
    await new Promise((resolve) => window.addEventListener('load', resolve));
  }
  if (input.init) { window.eval(input.init); }
  const result = window.eval(input.js);
  process.stdout.write(String(result));
})().catch((error) => { process.stderr.write(String(error && error.stack ? error.stack : error)); process.exit(1); });
'''

CROSS_ORIGIN_FRAME_INIT = (
    "Object.defineProperty(window.HTMLIFrameElement.prototype, 'contentDocument', "
    "{ get() { return null; }, configurable: true });"
)


@pytest.fixture(scope="module")
def jsdom(tmp_path_factory):
    script = tmp_path_factory.mktemp("jsdom") / "runner.js"
    script.write_text(_NODE_RUNNER, encoding="utf-8")

    def run(html: str, js: str, *, init: str = "", url: str = "https://example.test/page") -> Dict[str, Any]:
        completed = subprocess.run(
            [NODE, str(script)],
            input=json.dumps({"html": html, "js": js, "init": init, "url": url}),
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "JSDOM_PATH": str(JSDOM_CANDIDATES[0])},
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    return run


def inspect_js(*, content_selector=None, content_offset=0, include_form_state=False, with_marks=False) -> str:
    base = browser_inspect_extensions.apply_inspect_options(
        browser_inspect_tool._INSPECT_JS_CODE,
        content_selector=content_selector,
        content_offset=content_offset,
        include_form_state=include_form_state,
    )
    if not with_marks:
        return base
    expression = base.strip().rstrip(";")
    return (
        "(function(){var out = JSON.parse(" + expression + ");"
        " out.__marked = document.querySelectorAll('[data-basil-challenge]').length;"
        " return JSON.stringify(out);})()"
    )


WYOMING_STYLE_PAGE = """
<body>
<div id="MainContent">
<p>Testing whether you are a human visitor. What code is in the image?</p>
<form id="challenge">
<img id="cap" src="data:image/png;base64,AAAA" data-test-size="150x50">
<input type="text" id="answer" name="answer">
<button type="submit" id="go">Submit</button>
</form>
<p>Your support ID is: 1234</p>
</div>
</body>
"""

CONTENT_PAGE = """
<body>
<nav id="topnav"><a href="/">Home</a> <a href="/f">Filings</a> <a href="/c">Contact</a> <a href="/s">Search</a></nav>
<div id="content"><h1>Annual Report</h1><p>The filing fee is sixty dollars and is due each year before the first day of the anniversary month, with no extensions.</p></div>
<footer>Copyright 2026 Example Secretary of State. All rights reserved worldwide.</footer>
</body>
"""


def test_text_image_challenge_is_recognized_and_its_elements_are_marked(jsdom):
    info = jsdom(WYOMING_STYLE_PAGE, inspect_js(with_marks=True))

    challenge = info["challenge"]
    assert challenge["kind"] == "text_image"
    assert challenge["handoff_only"] is False
    assert challenge["input_selector"] == '[data-basil-challenge="input"]'
    assert challenge["submit_selector"] == '[data-basil-challenge="submit"]'
    assert challenge["image_selector"] == '[data-basil-challenge="image"]'
    assert (challenge["image_width"], challenge["image_height"]) == (150, 50)
    assert "capture_captcha" in challenge["next_step"]
    assert info["__marked"] == 3
    assert info["requires_user_input"] is False


def test_text_image_challenge_clears_the_generic_captcha_warning(jsdom):
    html = "<body><p>Captcha: type the characters you see in the image</p><form><img src='x' data-test-size='120x40'><input type='text' id='c'><button type='submit'>Go</button></form></body>"

    info = jsdom(html, inspect_js())

    assert info["challenge"]["kind"] == "text_image"
    assert info["safety_warnings"] == []
    assert info["requires_user_input"] is False


def test_recaptcha_widget_is_a_handoff_only_challenge(jsdom):
    html = '<body><form><iframe src="https://www.google.com/recaptcha/api2/anchor?k=1" title="reCAPTCHA"></iframe></form></body>'

    info = jsdom(html, inspect_js())

    assert info["challenge"]["kind"] == "recaptcha"
    assert info["challenge"]["handoff_only"] is True
    assert "request_human_help" in info["challenge"]["next_step"]
    assert info["requires_user_input"] is True
    assert info["frames"][0]["host"] == "www.google.com"


def test_invisible_recaptcha_badge_is_not_a_challenge(jsdom):
    html = '<body><p>Contact us</p><div class="grecaptcha-badge"><iframe src="https://www.google.com/recaptcha/api2/anchor" title="reCAPTCHA"></iframe></div></body>'

    info = jsdom(html, inspect_js())

    assert info["challenge"] is None


def test_password_field_is_a_login_handoff(jsdom):
    info = jsdom('<body><form><input type="text" id="u"><input type="password" id="pw"></form></body>', inspect_js())

    assert info["challenge"]["kind"] == "login"
    assert info["challenge"]["handoff_only"] is True


def test_card_fields_are_masked_in_the_inputs_list_and_ordinary_fields_are_not(jsdom):
    html = (
        '<body><form>'
        '<input type="text" id="num" name="cardnumber" autocomplete="cc-number" value="4242424242424242">'
        '<input type="text" id="sec" placeholder="Security code" value="123">'
        '<input type="text" id="cv" name="cvv" value="456">'
        '<input type="text" id="holder" name="cardholder" value="Ada Lovelace">'
        '<input type="text" id="city" name="discard_pile" value="Boston">'
        '</form></body>'
    )
    info = jsdom(html, inspect_js())
    fields = {item["selector"]: item for item in info["inputs"]}

    for selector in ("#num", "#sec", "#cv"):
        assert fields[selector]["value"] == "[hidden]"
        assert fields[selector]["sensitive"] is True
    assert fields["#holder"]["value"] == "Ada Lovelace"
    assert fields["#city"]["value"] == "Boston"
    assert "4242424242424242" not in json.dumps(info)


CARD_FILL_PAGE = (
    '<body><form>'
    '<input type="text" id="num" name="cardnumber" autocomplete="cc-number">'
    '<input type="text" id="sec" placeholder="Security code">'
    '<input type="text" id="cv" name="cvv">'
    '<input type="text" id="holder" name="cardholder">'
    '<input type="text" id="city" name="discard_pile">'
    '</form></body>'
)


@pytest.mark.parametrize("selector", ["#num", "#sec", "#cv"])
def test_fill_refuses_card_fields_without_sensitive_approval(jsdom, selector):
    fill_js = browser_interact_tool._build_action_js("fill", selector, "4242424242424242")

    result = jsdom(CARD_FILL_PAGE, fill_js)

    assert result["success"] is False
    assert result["requires_user_input"] is True
    assert "valueFilled" not in result


@pytest.mark.parametrize("selector", ["#holder", "#city"])
def test_fill_still_allows_ordinary_fields_near_card_forms(jsdom, selector):
    fill_js = browser_interact_tool._build_action_js("fill", selector, "Ada")

    result = jsdom(CARD_FILL_PAGE, fill_js)

    assert result["success"] is True
    assert result["valueFilled"] == "Ada"


def test_fill_card_field_proceeds_when_sensitive_fill_was_approved(jsdom):
    fill_js = browser_interact_tool._build_action_js(
        "fill", "#num", "4242424242424242", allow_sensitive_fill=True, redact_value=True
    )

    result = jsdom(CARD_FILL_PAGE, fill_js)

    assert result["success"] is True
    assert result["valueFilled"] == "[redacted]"
    assert "4242424242424242" not in json.dumps(result)


def test_card_metadata_is_classified_sensitive_by_the_python_gate():
    for metadata in (
        {"autocomplete": "cc-number"},
        {"name": "cardnumber"},
        {"placeholder": "Security code"},
        {"name": "cvv"},
        {"label": "Credit card"},
    ):
        assert browser_safety.is_sensitive_field_metadata(metadata) is True, metadata
    for metadata in ({"name": "cardholder"}, {"name": "discard_pile"}, {"name": "search"}):
        assert browser_safety.is_sensitive_field_metadata(metadata) is False, metadata


def test_block_page_is_a_bot_interstitial(jsdom):
    info = jsdom("<body><h1>Request unsuccessful.</h1><p>Your support ID is: 12345</p></body>", inspect_js())

    assert info["challenge"]["kind"] == "bot_interstitial"
    assert info["challenge"]["handoff_only"] is True


def test_ordinary_page_has_no_challenge(jsdom):
    info = jsdom("<body><h1>Welcome</h1><p>Plain page about gardening and soil.</p></body>", inspect_js())

    assert info["challenge"] is None
    assert "frame_notice" not in info


def test_unreadable_frame_produces_a_native_input_notice(jsdom):
    html = '<body><h1>Pay</h1><iframe id="card" src="https://secure.pay.example/card"></iframe></body>'

    info = jsdom(html, inspect_js(), init=CROSS_ORIGIN_FRAME_INIT)

    assert info["frames"] == [{"selector": "#card", "host": "secure.pay.example", "accessible": False}]
    assert "secure.pay.example" in info["frame_notice"]
    assert "browser_native_input" in info["frame_notice"]
    assert info["skippedFrames"]


def test_page_without_a_main_region_loses_nav_and_footer_text(jsdom):
    info = jsdom(CONTENT_PAGE, inspect_js())

    assert "filing fee is sixty dollars" in info["mainText"]
    assert "Copyright 2026" not in info["mainText"]
    assert "Home Filings" not in info["mainText"]
    assert info["mainTextMeta"]["stripped_chrome_blocks"] == 2


def test_page_with_a_main_region_is_read_as_before(jsdom):
    html = "<body><nav>Home Filings Contact Search Help</nav><main><p>Only the main text should be read from this page, nothing else at all.</p></main><footer>Copyright notice that is long enough to count</footer></body>"

    info = jsdom(html, inspect_js())

    assert info["mainText"].startswith("Only the main text")
    assert info["mainTextMeta"]["stripped_chrome_blocks"] == 0


def test_stripping_never_blanks_a_page_that_is_all_navigation(jsdom):
    html = "<body><nav>Home Filings Contact Search Help Sitemap</nav></body>"

    info = jsdom(html, inspect_js())

    assert "Home Filings" in info["mainText"]


def test_content_selector_reads_one_section(jsdom):
    info = jsdom(CONTENT_PAGE, inspect_js(content_selector="#content"))

    assert info["mainText"].startswith("Annual Report")
    assert "Copyright" not in info["mainText"]
    assert "Home" not in info["mainText"]


@pytest.mark.parametrize("selector", ["#nope", "###"])
def test_content_selector_that_matches_nothing_reports_an_error(jsdom, selector):
    info = jsdom(CONTENT_PAGE, inspect_js(content_selector=selector))

    assert info["mainText"] == ""
    assert info["mainTextMeta"]["error"].startswith("content_selector matched no element")


def test_long_text_can_be_continued_with_an_offset(jsdom):
    html = "<body><div id='content'>" + ("x" * 13000) + "</div></body>"

    first = jsdom(html, inspect_js(content_selector="#content"))
    second = jsdom(html, inspect_js(content_selector="#content", content_offset=12000))

    assert len(first["mainText"]) == 12000
    assert first["mainTextMeta"]["truncated"] is True
    assert first["mainTextMeta"]["next_offset"] == 12000
    assert "content_offset" in first["mainTextMeta"]["continuation_hint"]
    assert len(second["mainText"]) == 1000
    assert second["mainTextMeta"]["truncated"] is False
    assert second["mainTextMeta"]["next_offset"] is None


def test_unmodified_script_still_runs_without_options(jsdom):
    info = jsdom(CONTENT_PAGE, browser_inspect_tool._INSPECT_JS_CODE)

    assert "filing fee" in info["mainText"]
    assert info["challenge"] is None


FORM_PAGE = """
<body><form id="f">
<label for="first">First name</label><input id="first" name="first" type="text" value="Ada" required>
<input id="pw" name="pw" type="password" value="hunter2">
<input id="agree" type="checkbox" checked>
<select id="state" name="state"><option value="WY">Wyoming</option><option value="CO" selected>Colorado</option></select>
<input id="card" name="cardnumber" type="text" autocomplete="cc-number" value="4111111111111111">
<input id="em" type="email" value="nope">
<input id="req" type="text" required>
<input type="hidden" id="hid" value="x">
<input type="submit" id="submit" value="Go">
</form></body>
"""


def test_form_state_reads_values_masks_secrets_and_flags_invalid_fields(jsdom):
    info = jsdom(FORM_PAGE, inspect_js(include_form_state=True))

    fields = {entry["selector"]: entry for entry in info["formState"]}
    assert "#hid" not in fields and "#submit" not in fields
    assert fields["#first"]["label"] == "First name"
    assert fields["#first"]["value"] == "Ada"
    assert fields["#first"]["required"] is True
    assert "invalid" not in fields["#first"]
    assert fields["#pw"]["value"] == "[hidden]"
    assert fields["#card"]["value"] == "[hidden]"
    assert fields["#agree"]["checked"] is True
    assert fields["#state"]["selected_text"] == "Colorado"
    assert fields["#em"]["invalid"] is True
    assert fields["#req"]["invalid"] is True
    form_state_json = json.dumps(info["formState"])
    assert "hunter2" not in form_state_json and "4111111111111111" not in form_state_json


def test_form_state_is_absent_unless_requested(jsdom):
    info = jsdom(FORM_PAGE, inspect_js())

    assert "formState" not in info


HEADER_SEARCH_PAGE = """
<body>
<header id="site-header"><form role="search"><input type="text" id="q" name="q" placeholder="Search"><button id="searchgo" type="button">Go</button></form></header>
<main><form id="filing"><input type="text" id="MainContent_txtFilingName" name="MainContent_txtFilingName"><button type="submit" id="MainContent_btnSearch">Search</button></form></main>
</body>
"""


def test_header_search_box_is_tagged_and_the_page_form_is_not(jsdom):
    info = jsdom(HEADER_SEARCH_PAGE, inspect_js())

    inputs = {item["selector"]: item for item in info["inputs"]}
    buttons = {item["selector"]: item for item in info["buttons"]}
    assert inputs["#q"]["global_search"] is True
    assert inputs["#q"]["region"] == "header"
    assert inputs["#q"]["form"] == "form"
    assert "global_search" not in inputs["#MainContent_txtFilingName"]
    assert "region" not in inputs["#MainContent_txtFilingName"]
    assert inputs["#MainContent_txtFilingName"]["form"] == "#filing"
    assert buttons["#searchgo"]["region"] == "header"
    assert "region" not in buttons["#MainContent_btnSearch"]


def test_validation_messages_are_collected(jsdom):
    html = '<body><div class="field-validation-error">Name is required</div><div class="error" style="display:none">Hidden</div></body>'

    info = jsdom(html, inspect_js())

    assert info["validationMessages"] == ["Name is required"]


def test_page_summary_script_reports_headings_messages_and_challenge(jsdom):
    html = (
        "<!DOCTYPE html><html><head><title>Results page</title></head><body>"
        "<h1>Search results</h1><h2 style='display:none'>Hidden heading</h2><h3>Section</h3>"
        "<div class='field-validation-error'>Name is required</div>"
        "</body></html>"
    )

    summary = jsdom(html, browser_page_settle.PAGE_SUMMARY_JS)

    assert summary["success"] is True
    assert summary["title"] == "Results page"
    assert summary["url"] == "https://example.test/page"
    assert summary["headings"] == ["Search results", "Section"]
    assert summary["messages"] == ["Name is required"]
    assert summary["challenge"] is None


def test_challenge_detect_script_reports_url_and_challenge(jsdom):
    result = jsdom(WYOMING_STYLE_PAGE, browser_challenge_js.CHALLENGE_DETECT_ONLY_JS)

    assert result["success"] is True
    assert result["url"] == "https://example.test/page"
    assert result["challenge"]["kind"] == "text_image"


def test_settle_probe_script_reports_readiness(jsdom):
    probe = jsdom("<body><p>Hello there</p></body>", browser_page_settle.SETTLE_PROBE_JS)

    assert probe["ready"] == "complete"
    assert probe["text_length"] >= len("Hello there")


def test_not_found_diagnostics_script_lists_similar_visible_elements(jsdom):
    html = "<body><p>" + ("filler " * 80) + "</p><input id='MainContent_txtFilingName' name='MainContent_txtFilingName'><input id='other'></body>"

    diagnostics = jsdom(html, browser_interact_diagnostics.build_not_found_diagnostics_js("#txtFilingName"))

    assert diagnostics["similar"] == [{"selector": "#MainContent_txtFilingName", "tag": "input", "visible": True}]
    assert len(diagnostics["text_head"]) == 240
    assert diagnostics["challenge"] is None


def test_form_readback_script_masks_secrets_and_reports_missing_fields(jsdom):
    html = (
        "<body><input id='a' type='text' value='Ada'><input id='pw' type='password' value='hunter2'>"
        "<input id='c' type='checkbox' checked><select id='s'><option>Wyoming</option><option selected>Colorado</option></select></body>"
    )

    readback = jsdom(html, browser_interact_batch.build_form_readback_js(["#a", "#pw", "#c", "#s", "#missing"]))

    fields = readback["fields"]
    assert fields["#a"]["value"] == "Ada"
    assert fields["#pw"]["value"] == "[hidden]"
    assert fields["#c"]["checked"] is True
    assert fields["#s"]["selected_text"] == "Colorado"
    assert fields["#missing"] == {"found": False}


def test_captcha_capture_script_reports_a_missing_or_unloaded_image(jsdom):
    unmarked = jsdom("<body><p>Nothing here</p></body>", browser_captcha.CAPTCHA_CAPTURE_JS)
    unloaded = jsdom('<body><img data-basil-challenge="image" src="x.png"></body>', browser_captcha.CAPTCHA_CAPTURE_JS)

    assert unmarked["success"] is False
    assert "No CAPTCHA image is marked" in unmarked["error"]
    assert unloaded["success"] is False
    assert "not finished loading" in unloaded["error"]
