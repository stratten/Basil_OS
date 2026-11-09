"""In-page JavaScript that recognizes CAPTCHAs, bot interstitials, and login walls.

The detector is embedded into browser_inspect, the post-click page summary, the not-found diagnostics, and the CAPTCHA tools so they all agree on what a challenge is.
"""

from __future__ import annotations

# Kinds returned by basilDetectChallenge():
#   text_image       a type-the-characters image challenge Basil may attempt with vision (handoff_only is false)
#   recaptcha, hcaptcha, turnstile   third-party widgets (handoff_only is true)
#   login            a visible password field (handoff_only is true)
#   bot_interstitial a block or "checking your browser" page (handoff_only is true)
CHALLENGE_DETECTION_FUNCTION_JS = r'''
function basilDetectChallenge() {
    function challengeVisible(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        var style = window.getComputedStyle(el);
        var rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width > 0 && rect.height > 0;
    }
    function markChallengeElement(el, role) {
        el.setAttribute('data-basil-challenge', role);
        return '[data-basil-challenge="' + role + '"]';
    }
    var stale = document.querySelectorAll('[data-basil-challenge]');
    for (var s = 0; s < stale.length; s++) stale[s].removeAttribute('data-basil-challenge');
    var bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';

    var widgetNodes = document.querySelectorAll('iframe, .g-recaptcha, .h-captcha, .cf-turnstile');
    for (var w = 0; w < widgetNodes.length; w++) {
        var widget = widgetNodes[w];
        if (!challengeVisible(widget)) continue;
        if (widget.closest && widget.closest('.grecaptcha-badge')) continue;
        if (widget.getAttribute('data-size') === 'invisible') continue;
        var widgetHint = (widget.getAttribute('src') || '') + ' ' + (widget.getAttribute('title') || '') + ' ' + String(widget.getAttribute('class') || '');
        var widgetKind = null;
        if (/recaptcha/i.test(widgetHint)) widgetKind = 'recaptcha';
        else if (/hcaptcha|h-captcha/i.test(widgetHint)) widgetKind = 'hcaptcha';
        else if (/challenges\.cloudflare\.com|turnstile/i.test(widgetHint)) widgetKind = 'turnstile';
        if (widgetKind) {
            return {kind: widgetKind, handoff_only: true, prompt: 'This page asks for a ' + widgetKind + ' challenge.'};
        }
    }

    var promptPattern = /(what code is in the image|enter the (characters|code|text|letters) (you see|shown|in the image|below)|type the (characters|code|text|letters)|characters (you see|in the image|shown)|code (shown )?in the image|testing whether you are a human|prove (that )?you are (a )?human|i'?m not a robot)/i;
    if (bodyText.length < 4000 && promptPattern.test(bodyText)) {
        var textInputs = document.querySelectorAll('input[type="text"], input:not([type]), input[type="search"], input[type="tel"], input[type="number"]');
        for (var i = 0; i < textInputs.length; i++) {
            var input = textInputs[i];
            if (!challengeVisible(input) || input.disabled || input.readOnly) continue;
            var scope = input.closest('form') || (input.parentElement && input.parentElement.parentElement) || document.body;
            var inputTop = input.getBoundingClientRect().top;
            var candidates = scope.querySelectorAll('img, canvas');
            var image = null;
            var bestDistance = Infinity;
            for (var k = 0; k < candidates.length; k++) {
                var candidate = candidates[k];
                if (!challengeVisible(candidate)) continue;
                var box = candidate.getBoundingClientRect();
                if (box.width < 40 || box.width > 600 || box.height < 15 || box.height > 250) continue;
                var distance = Math.abs(box.top - inputTop);
                if (distance < bestDistance) { bestDistance = distance; image = candidate; }
            }
            if (!image) continue;
            var button = scope.querySelector('input[type="submit"], button[type="submit"]') || scope.querySelector('button, input[type="button"]');
            var promptMatch = promptPattern.exec(bodyText);
            var imageBox = image.getBoundingClientRect();
            return {
                kind: 'text_image',
                handoff_only: false,
                prompt: promptMatch ? promptMatch[0] : 'Type the characters shown in the image.',
                image_selector: markChallengeElement(image, 'image'),
                input_selector: markChallengeElement(input, 'input'),
                submit_selector: (button && challengeVisible(button)) ? markChallengeElement(button, 'submit') : null,
                image_width: Math.round(imageBox.width),
                image_height: Math.round(imageBox.height)
            };
        }
    }

    var passwordInput = document.querySelector('input[type="password"]');
    if (passwordInput && challengeVisible(passwordInput)) {
        return {kind: 'login', handoff_only: true, prompt: 'This page has a password field. Sign-in must be completed by the user.'};
    }

    if (bodyText.length < 3000 && /(your support id is|just a moment|checking your (browser|connection)|unusual traffic|verify (that )?you are (a )?human|request unsuccessful|access denied)/i.test(bodyText)) {
        return {kind: 'bot_interstitial', handoff_only: true, prompt: bodyText.replace(/\s+/g, ' ').trim().slice(0, 200)};
    }
    return null;
}
'''

CHALLENGE_DETECT_ONLY_JS = (
    "// basil:challenge_detect\n(function() {\n"
    + CHALLENGE_DETECTION_FUNCTION_JS
    + "\n    return JSON.stringify({success: true, url: window.location.href, challenge: basilDetectChallenge()});\n})();\n"
)
