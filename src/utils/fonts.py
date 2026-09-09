import functools
import os
import sys
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError

from common.logger import get_logger

logger = get_logger()

_FONT_PATTERNS: tuple[str, ...] = ('*.ttf', '*.otf', '*.ttc')


def _system_font_dirs() -> list[Path]:
    """The standard font directories for the current operating system."""
    home = Path.home()
    if sys.platform == 'darwin':
        return [
            Path('/System/Library/Fonts'),
            Path('/Library/Fonts'),
            home / 'Library/Fonts',
        ]
    if sys.platform.startswith('win'):
        dirs = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts']
        local = os.environ.get('LOCALAPPDATA')
        if local:
            dirs.append(Path(local) / 'Microsoft/Windows/Fonts')
        return dirs
    return [
        Path('/usr/share/fonts'),
        Path('/usr/local/share/fonts'),
        home / '.fonts',
        home / '.local/share/fonts',
    ]


def _family_name(file: Path) -> str | None:
    """The human-readable family name of a font file, or None if unreadable."""
    try:
        font = TTFont(file, fontNumber=0, lazy=True)
    except (TTLibError, OSError, ValueError):
        return None
    try:
        name_table = font['name']
        # Typographic family (16) is the most user-friendly; fall back to the
        # legacy family name (1).
        return name_table.getDebugName(16) or name_table.getDebugName(1)
    except (KeyError, AttributeError):
        return None
    finally:
        font.close()


@functools.lru_cache(maxsize=1)
def system_font_families() -> tuple[str, ...]:
    """Every font family installed on this machine, sorted, de-duplicated.

    Reading every font file is not free, so the result is cached for the life
    of the process. Families whose name starts with a dot (hidden system fonts)
    are skipped as they are not usable by name."""
    families: set[str] = set()
    for directory in _system_font_dirs():
        if not directory.is_dir():
            continue
        for pattern in _FONT_PATTERNS:
            for file in directory.rglob(pattern):
                name = _family_name(file)
                if name and not name.startswith('.'):
                    families.add(name)
    logger.debug('Found %s system font families.', len(families))
    return tuple(sorted(families, key=str.casefold))
