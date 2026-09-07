from data.print_documents.place_cards.content import (
    is_builder_friendly,
    parse_content,
    serialize_content,
)


def test_builder_friendly_detection():
    assert is_builder_friendly('Board {{ board.number }}')
    assert is_builder_friendly('{% if player.club %}({{ player.club }}){% endif %}')
    # Control structures the builder can't model -> advanced.
    assert not is_builder_friendly(
        '{% with p = pairing.white_player %}{{ p.rating }}{% endwith %}'
    )
    assert not is_builder_friendly('{% if a %}x{% elif b %}y{% endif %}')
    # Any raw HTML markup (including <br>) -> advanced.
    assert not is_builder_friendly(
        '<span style="color: {{ p.color }}">{{ p.color }}</span>'
    )
    assert not is_builder_friendly('{{ a }}<br/>{{ b }}')  # <br> is advanced-only
    assert is_builder_friendly('score 5 < 6')  # a bare "<" is not a tag


def test_empty():
    assert parse_content('') == []
    assert parse_content(None) == []
    assert serialize_content([]) == ''


def test_plain_text():
    assert parse_content('Board') == [{'k': 't', 'v': 'Board'}]
    assert serialize_content([{'k': 't', 'v': 'Board'}]) == 'Board'


def test_bare_field():
    parts = parse_content('{{ player.club }}')
    assert parts == [{'k': 'f', 'e': 'player.club', 'p': '', 's': ''}]


def test_field_with_affixes_roundtrips():
    text = '{% if player.club %}Club: {{ player.club }} —{% endif %}'
    parts = parse_content(text)
    assert parts == [{'k': 'f', 'e': 'player.club', 'p': 'Club: ', 's': ' —'}]
    assert serialize_content(parts) == text


def test_mixed_text_and_fields():
    text = 'Board {{ board.number }} {% if player.rating %}({{ player.rating }}){% endif %}'
    parts = parse_content(text)
    assert parts == [
        {'k': 't', 'v': 'Board '},
        {'k': 'f', 'e': 'board.number', 'p': '', 's': ''},
        {'k': 't', 'v': ' '},
        {'k': 'f', 'e': 'player.rating', 'p': '(', 's': ')'},
    ]
    assert serialize_content(parts) == text


def test_serialize_skips_empty_expr():
    assert serialize_content([{'k': 'f', 'e': '  ', 'p': 'x', 's': 'y'}]) == ''


def test_bare_field_serializes_bare():
    # A field with no affixes stays a plain interpolation (no conditional).
    out = serialize_content([{'k': 'f', 'e': 'player.club', 'p': '', 's': ''}])
    assert out == '{{ player.club }}'
    assert parse_content(out) == [{'k': 'f', 'e': 'player.club', 'p': '', 's': ''}]


def test_prefix_only_is_guarded():
    out = serialize_content([{'k': 'f', 'e': 'player.rating', 'p': '(', 's': ''}])
    assert out == '{% if player.rating %}({{ player.rating }}{% endif %}'
    assert parse_content(out) == [{'k': 'f', 'e': 'player.rating', 'p': '(', 's': ''}]


def test_safe_filter_preserved():
    text = '{{ player.federation_flag | safe }}'
    parts = parse_content(text)
    assert parts == [{'k': 'f', 'e': 'player.federation_flag | safe', 'p': '', 's': ''}]
    assert serialize_content(parts) == text


def test_line_break_kept_as_literal_text():
    # <br> is no longer a part type; it stays verbatim text (advanced-only) and
    # round-trips untouched.
    text = '{{ player.last_name }}<br/>{{ player.first_name }}'
    parts = parse_content(text)
    assert parts == [
        {'k': 'f', 'e': 'player.last_name', 'p': '', 's': ''},
        {'k': 't', 'v': '<br/>'},
        {'k': 'f', 'e': 'player.first_name', 'p': '', 's': ''},
    ]
    assert serialize_content(parts) == text


def test_unrecognised_jinja_kept_verbatim():
    text = 'A {% for x in y %}{{ x }}{% endfor %} B'
    parts = parse_content(text)
    # The loop body's bare {{ x }} is a field; the surrounding for/endfor stay
    # as text and round-trip.
    assert serialize_content(parts) == text


def test_mismatched_conditional_kept_verbatim():
    text = '{% if a %}x{{ b }}y{% endif %}'
    parts = parse_content(text)
    assert parts == [{'k': 't', 'v': text}]
    assert serialize_content(parts) == text


def _embedded_texts() -> list[tuple[str, str, str]]:
    """Every (file, section, text) of the built-in templates."""
    import toml

    from common import EMBEDDED_PLACE_CARDS_DIR

    texts: list[tuple[str, str, str]] = []
    for file in sorted(EMBEDDED_PLACE_CARDS_DIR.glob('*.template')):
        for section, data in toml.load(file).items():
            if isinstance(data, dict) and 'text' in data:
                texts.append((file.name, section, data['text']))
    return texts


def test_embedded_templates_roundtrip():
    """The built-in templates stay editable with the visual content builder:
    what the builder would write back must be byte-identical to what ships."""
    for name, section, text in _embedded_texts():
        if not is_builder_friendly(text):
            continue
        assert serialize_content(parse_content(text)) == text, f'{name} [{section}]'


def test_embedded_optional_fields_are_guarded():
    """An optional field followed by a separator carries the separator in its
    own guard, so nothing is left dangling when the value is empty. Advanced
    items are raw HTML, where a trailing space is markup, not a separator."""
    for name, section, text in _embedded_texts():
        if not is_builder_friendly(text):
            continue
        for part in parse_content(text):
            if part.get('k') != 't':
                continue
            assert not part['v'].startswith(' '), f'{name} [{section}]: {text}'
            assert not part['v'].endswith(' '), f'{name} [{section}]: {text}'
