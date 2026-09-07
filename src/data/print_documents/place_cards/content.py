"""Conversion between a text item's stored Jinja string and the visual editor's
"content builder" model: an ordered list of parts, each either literal text or a
field.

A field renders its value wrapped in an optional prefix/suffix that only appear
when the value is non-empty, i.e. it serialises to::

    {% if <expr> %}<prefix>{{ <expr> }}<suffix>{% endif %}

Anything the parser does not recognise as a field is kept verbatim as a text
part, so hand-authored Jinja (loops, custom conditions...) round-trips untouched
and still renders.

A part is a plain dict:
    {'k': 't', 'v': <literal text>}
    {'k': 'f', 'e': <expr>, 'p': <prefix>, 's': <suffix>}
"""

import re

# A field with a conditional prefix/suffix (our own output), or a bare
# interpolation. The conditional alternative is listed first so it wins over the
# bare ``{{ }}`` it contains.
_FIELD_RE = re.compile(
    r'{%-?\s*if\s+(?P<ife>.+?)\s*-?%}'
    r'(?P<pre>.*?){{-?\s*(?P<ife2>.+?)\s*-?}}(?P<suf>.*?)'
    r'{%-?\s*endif\s*-?%}'
    r'|{{-?\s*(?P<expr>.+?)\s*-?}}',
    re.DOTALL,
)


def parse_content(text: str | None) -> list[dict[str, str]]:
    """Parse a stored Jinja string into an ordered list of parts."""
    text = text or ''
    parts: list[dict[str, str]] = []

    def add_text(value: str) -> None:
        if value:
            parts.append({'k': 't', 'v': value})

    pos = 0
    for match in _FIELD_RE.finditer(text):
        add_text(text[pos : match.start()])
        pos = match.end()
        if match.group('expr') is not None:
            parts.append({'k': 'f', 'e': match.group('expr').strip(), 'p': '', 's': ''})
            continue
        expr = match.group('ife2').strip()
        if match.group('ife').strip() == expr:
            parts.append(
                {'k': 'f', 'e': expr, 'p': match.group('pre'), 's': match.group('suf')}
            )
        else:
            # A conditional we did not author (the tested expression differs from
            # the printed one): keep it verbatim so it still renders as intended.
            add_text(match.group(0))
    add_text(text[pos:])
    return parts


_HTML_TAG_RE = re.compile(r'<(/?)([a-zA-Z][\w-]*)')


def is_builder_friendly(text: str | None) -> bool:
    """Whether ``text`` can be edited with the visual content builder. Content
    with Jinja control structures (``{% with %}``, ``{% if/elif %}``, loops...)
    or any raw HTML markup (including ``<br>``) can't be cleanly represented as
    parts, so the editor falls back to a raw Jinja box."""
    text = text or ''
    if _HTML_TAG_RE.search(text):
        return False
    return all(
        '{%' not in part['v'] for part in parse_content(text) if part.get('k') == 't'
    )


def serialize_content(parts: list[dict[str, str]]) -> str:
    """Serialise a list of parts back into a Jinja string."""
    out: list[str] = []
    for part in parts or []:
        if part.get('k') == 't':
            out.append(part.get('v', ''))
        elif part.get('k') == 'f':
            expr = (part.get('e') or '').strip()
            if not expr:
                continue
            prefix = part.get('p', '')
            suffix = part.get('s', '')
            if prefix or suffix:
                # Guard the affixes so they only show when the value is present.
                out.append(
                    '{% if '
                    + expr
                    + ' %}'
                    + prefix
                    + '{{ '
                    + expr
                    + ' }}'
                    + suffix
                    + '{% endif %}'
                )
            else:
                out.append('{{ ' + expr + ' }}')
    return ''.join(out)
