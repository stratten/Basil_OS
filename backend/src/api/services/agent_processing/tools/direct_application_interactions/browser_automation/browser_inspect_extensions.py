"""Extra in-page JavaScript for browser_inspect: page regions, form state, frames, and challenge detection."""

from __future__ import annotations

import json

from .browser_challenge_js import CHALLENGE_DETECTION_FUNCTION_JS

OPTIONS_PLACEHOLDER = "/*__BASIL_OPTIONS__*/"
EXTENSIONS_PLACEHOLDER = "/*__BASIL_EXTENSIONS__*/"


def apply_inspect_options(
    js_code: str,
    *,
    content_selector: str | None,
    content_offset: int,
    include_form_state: bool,
) -> str:
    """Return the inspect script with this call's options declared as `BASIL_OPTIONS`."""

    options = {
        "contentSelector": (content_selector or "").strip() or None,
        "contentOffset": max(0, int(content_offset or 0)),
        "includeFormState": bool(include_form_state),
    }
    return js_code.replace(OPTIONS_PLACEHOLDER, "const BASIL_OPTIONS = " + json.dumps(options) + ";", 1)


INSPECT_EXTENSIONS_JS = CHALLENGE_DETECTION_FUNCTION_JS + r'''
    function basilRegionOf(el) {
        if (!el || !el.closest) return 'main';
        if (el.closest('nav, [role="navigation"]')) return 'nav';
        if (el.closest('footer, [role="contentinfo"]')) return 'footer';
        if (el.closest('aside, [role="complementary"]')) return 'aside';
        if (el.closest('header, [role="banner"]')) return 'header';
        try {
            if (el.closest('[id*="header" i], [class*="header" i], [id*="topbar" i], [class*="topbar" i]')) return 'header';
        } catch (selectorError) {
            /* engines without the case-insensitive attribute flag fall through to main */
        }
        return 'main';
    }

    function basilIsSearchField(el, region) {
        if (!el || !el.tagName) return false;
        if ((el.type || '').toLowerCase() === 'search') return true;
        if (el.closest && el.closest('[role="search"]')) return true;
        var hint = [el.name, el.id, el.getAttribute('placeholder'), el.getAttribute('aria-label')].filter(Boolean).join(' ');
        return region !== 'main' && /search|query|keyword|(^|\W)q($|\W)/i.test(hint);
    }

    function basilTagGroup(group) {
        var items = info[group];
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (!item.selector || item.selector.indexOf(' >>> ') !== -1) continue;
            var el = null;
            try { el = document.querySelector(item.selector); } catch (selectorError) { el = null; }
            if (!el) continue;
            var region = basilRegionOf(el);
            if (region !== 'main') item.region = region;
            if (group === 'inputs') {
                var form = el.form || (el.closest ? el.closest('form') : null);
                if (form) {
                    item.form = form.id ? '#' + cssEscape(form.id) : (form.getAttribute('name') ? 'form[name="' + form.getAttribute('name') + '"]' : 'form');
                }
                if (basilIsSearchField(el, region)) item.global_search = true;
            }
        }
    }
    basilTagGroup('buttons');
    basilTagGroup('inputs');
    basilTagGroup('links');

    function basilCollectFrames() {
        var frames = document.querySelectorAll('iframe, frame');
        var list = [];
        for (var i = 0; i < frames.length && list.length < 10; i++) {
            var frame = frames[i];
            if (!isVisible(frame)) continue;
            var accessible = false;
            try { accessible = Boolean(frame.contentDocument); } catch (frameError) { accessible = false; }
            var host = '';
            try { host = new URL(frame.getAttribute('src') || '', window.location.href).host; } catch (urlError) { host = ''; }
            list.push({selector: localSelector(frame), host: host, accessible: accessible});
        }
        return list;
    }
    var basilFrames = basilCollectFrames();
    if (basilFrames.length) info.frames = basilFrames;
    var basilBlockedFrames = basilFrames.filter(function (f) { return !f.accessible; });
    if (basilBlockedFrames.length) {
        var basilHosts = [];
        basilBlockedFrames.forEach(function (f) { if (f.host && basilHosts.indexOf(f.host) === -1) basilHosts.push(f.host); });
        info.frame_notice = basilBlockedFrames.length + ' frame(s) from another site' + (basilHosts.length ? ' (' + basilHosts.join(', ') + ')' : '') + ' cannot be read or filled by browser_inspect or browser_interact. If one holds a choice you must make, such as a saved-card dropdown, use browser_native_input. Do not try to read card numbers.';
    }

    function basilLabelFor(el) {
        var label = '';
        if (el.id) {
            try {
                var byFor = document.querySelector('label[for="' + String(el.id).replace(/"/g, '\\"') + '"]');
                if (byFor) label = textOf(byFor);
            } catch (labelError) {
                label = '';
            }
        }
        if (!label && el.closest) {
            var wrapper = el.closest('label');
            if (wrapper) label = textOf(wrapper);
        }
        if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '';
        return String(label).replace(/\s+/g, ' ').trim().slice(0, 80);
    }

    function basilCollectFormState() {
        var out = [];
        var fields = document.querySelectorAll('input, select, textarea');
        for (var i = 0; i < fields.length && out.length < 80; i++) {
            var el = fields[i];
            var tag = el.tagName.toLowerCase();
            var type = (el.type || tag).toLowerCase();
            if (['hidden', 'submit', 'button', 'image', 'reset'].indexOf(type) !== -1) continue;
            if (!isVisible(el)) continue;
            var hint = [el.type, el.name, el.id, el.getAttribute('autocomplete')].filter(Boolean).join(' ');
            var masked = type === 'password' || isSensitiveInput(el) || /cvv|cvc|card|ssn|routing|account/i.test(hint) || /^cc-/i.test(el.getAttribute('autocomplete') || '');
            var entry = {
                selector: localSelector(el),
                label: basilLabelFor(el),
                type: type,
                name: el.name || '',
                required: Boolean(el.required),
                disabled: Boolean(el.disabled)
            };
            if (type === 'checkbox' || type === 'radio') {
                entry.checked = Boolean(el.checked);
            } else if (tag === 'select') {
                entry.selected_text = el.selectedIndex >= 0 ? String(el.options[el.selectedIndex].text).slice(0, 120) : '';
            } else {
                entry.value = masked ? '[hidden]' : String(el.value === undefined ? '' : el.value).slice(0, 200);
            }
            if (el.validity && !el.validity.valid) {
                entry.invalid = true;
                entry.validation_message = String(el.validationMessage || '').slice(0, 160);
            }
            out.push(entry);
        }
        return out;
    }

    function basilCollectValidationMessages() {
        var messages = [];
        var nodes = document.querySelectorAll('[role="alert"], .validation-summary-errors, .field-validation-error, .error, .errors, .text-danger, .alert-danger, .alert-error, .error-message');
        for (var i = 0; i < nodes.length && messages.length < 5; i++) {
            if (!isVisible(nodes[i])) continue;
            var text = String(nodes[i].innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160);
            if (text && messages.indexOf(text) === -1) messages.push(text);
        }
        return messages;
    }

    var basilMessages = basilCollectValidationMessages();
    if (basilMessages.length) info.validationMessages = basilMessages;
    if (typeof BASIL_OPTIONS !== 'undefined' && BASIL_OPTIONS && BASIL_OPTIONS.includeFormState) {
        info.formState = basilCollectFormState();
    }

    info.challenge = basilDetectChallenge();
    if (info.challenge) {
        if (info.challenge.kind === 'text_image') {
            info.safety_warnings = info.safety_warnings.filter(function (warning) { return warning.indexOf('CAPTCHA-like') === -1; });
            info.requires_user_input = info.safety_warnings.length > 0;
            info.challenge.next_step = 'Call browser_interact with action capture_captcha, read the saved image with analyze_with_vision, then call browser_interact with action submit_captcha.';
        } else {
            info.requires_user_input = true;
            info.challenge.next_step = 'Call browser_tabs with action request_human_help so the user can complete this step, then confirm with browser_inspect that it is gone.';
        }
    }
'''
