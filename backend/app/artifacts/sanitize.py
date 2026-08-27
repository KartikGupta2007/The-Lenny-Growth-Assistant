"""Sanitise generated HTML.

Generated HTML is untrusted (PRD section 14). Three layers, in order:

1. Script-like elements are removed with their contents, so nothing executable
   is even stored.
2. bleach allows only a layout/text tag set and drops every event handler,
   javascript: URL and unknown tag.
3. The frontend renders the result in a sandboxed iframe with no
   allow-scripts, so even a miss here cannot execute.
"""

from __future__ import annotations

import re

import bleach
from bleach.css_sanitizer import CSSSanitizer

# Elements whose *contents* must go too -- stripping only the tag would leave
# the script body behind as visible text.
_EXECUTABLE = re.compile(
    r"<\s*(script|noscript|template|object|embed|applet)\b.*?<\s*/\s*\1\s*>"
    r"|<\s*(script|noscript|object|embed|applet)\b[^>]*/?>",
    re.IGNORECASE | re.DOTALL,
)

ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "div", "em", "figcaption", "figure",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "ol", "p", "pre", "section", "small", "span", "strong", "style", "sub",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}

ALLOWED_ATTRIBUTES = {
    "*": ["class", "id", "style", "title"],
    "a": ["href", "target", "rel"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
}

# http/https/mailto only. No javascript:, no data: -- data: URLs can carry
# markup that some renderers will execute.
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]

ALLOWED_CSS_PROPERTIES = [
    "align-items", "background", "background-color", "border", "border-bottom",
    "border-color", "border-radius", "border-top", "box-shadow", "color",
    "display", "flex", "flex-direction", "flex-wrap", "font-family",
    "font-size", "font-style", "font-weight", "gap", "grid-template-columns",
    "height", "justify-content", "letter-spacing", "line-height", "margin",
    "margin-bottom", "margin-top", "max-width", "min-height", "opacity",
    "padding", "text-align", "text-decoration", "text-transform", "width",
]

_css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_CSS_PROPERTIES)


def sanitize_html(html: str) -> str:
    """Return `html` with everything executable removed."""
    without_scripts = _EXECUTABLE.sub("", html)
    return bleach.clean(
        without_scripts,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_css_sanitizer,
        strip=True,
        strip_comments=True,
    )
