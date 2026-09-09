"""Markdown rendering, used for the descriptions provided by the plugins."""

from functools import cache

from markdown_it import MarkdownIt


@cache
def _parser() -> MarkdownIt:
    # Raw HTML stays disabled: the rendered markdown is inserted as is in the pages.
    return MarkdownIt('default', {'html': False})


def markdown_to_html(markdown: str) -> str:
    return _parser().render(markdown)
