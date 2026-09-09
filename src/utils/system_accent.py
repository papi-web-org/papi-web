"""The accent colour of the system, which the platform highlights what is
selected with. It is read so that the pages displayed in the window are
highlighted in the colour the controls around them are."""

import sys


def _from_macos() -> str | None:
    from rubicon.objc import ObjCClass

    # Importing from the backend is what loads AppKit, without which the
    # classes can not be looked up.
    import toga_cocoa.libs  # noqa: F401

    NSColor = ObjCClass('NSColor')
    NSColorSpace = ObjCClass('NSColorSpace')
    # The accent is a dynamic colour, which has to be resolved in a colour space
    # before its components can be read.
    color = NSColor.controlAccentColor.colorUsingColorSpace(NSColorSpace.sRGBColorSpace)
    if color is None:
        return None
    return _to_hex(color.redComponent, color.greenComponent, color.blueComponent)


def _from_windows() -> str | None:
    from System.Drawing import SystemColors  # type: ignore[import-not-found]

    color = SystemColors.Highlight
    return _to_hex(color.R / 255, color.G / 255, color.B / 255)


def _to_hex(red: float, green: float, blue: float) -> str:
    return '#{:02x}{:02x}{:02x}'.format(
        *(round(min(max(component, 0), 1) * 255) for component in (red, green, blue))
    )


def system_accent_color() -> str | None:
    """The accent colour of the system as an hexadecimal string, or None on the
    platforms that do not expose one."""
    reader = {'darwin': _from_macos, 'win32': _from_windows}.get(sys.platform)
    if reader is None:
        return None
    try:
        return reader()
    except Exception:
        return None


def readable_text_color(background_color: str) -> str:
    """Black or white, whichever is read on *background_color*. The relative
    luminance of the sRGB colour is what the two are compared on
    (https://www.w3.org/TR/WCAG22/#dfn-relative-luminance)."""
    components = []
    for index in (1, 3, 5):
        component = int(background_color[index : index + 2], 16) / 255
        components.append(
            component / 12.92
            if component <= 0.04045
            else ((component + 0.055) / 1.055) ** 2.4
        )
    luminance = 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2]
    return '#212529' if luminance > 0.4 else '#ffffff'
