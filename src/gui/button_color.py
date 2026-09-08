"""Colouring the text of a button.

The colour of a style is not applied to the text of a button on macOS, which
leaves it as macOS draws it: too light to be read on the accent of the
application. The title of the button carries the colour there instead.
"""

import sys

import toga

if sys.platform == 'darwin':
    from rubicon.objc import ObjCClass
    from toga_cocoa.colors import native_color
    from toga_cocoa.libs import (
        NSAttributedString,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
    )
    from travertino.colors import color as parse_color

    # The keys of the attributes are Objective-C strings, which a dictionary of
    # Python can not hold.
    NSMutableDictionary = ObjCClass('NSMutableDictionary')


def set_button_text_color(button: toga.Button, color: str | None):
    """Writes the text of *button* in *color*, or in the colour of the platform
    when it is None. Platforms that apply the colour of the style are left
    alone."""
    if sys.platform != 'darwin':
        return
    native = button._impl.native
    attributes = NSMutableDictionary.alloc().init()
    attributes.setObject(native.font, forKey=NSFontAttributeName)
    if color is not None:
        attributes.setObject(
            native_color(parse_color(color)), forKey=NSForegroundColorAttributeName
        )
    native.attributedTitle = NSAttributedString.alloc().initWithString(
        button.text, attributes=attributes
    )
