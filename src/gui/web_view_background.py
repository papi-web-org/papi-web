"""Letting the window show through a web view.

A web view paints a background of its own, white whatever the page it displays
carries, which hides the window behind it. macOS is asked not to paint it, so
that a page with no background of its own shows the window through.
"""

import sys

import toga


def show_window_through(web_view: toga.WebView):
    """Stops *web_view* from painting a background of its own. Platforms whose
    web view is left as it is are not touched."""
    if sys.platform != 'darwin':
        return
    from rubicon.objc import ObjCClass

    NSNumber = ObjCClass('NSNumber')
    native = web_view._impl.native
    # The property is not part of the documented interface of a web view: a
    # version of macOS that does not know it leaves the background as it is.
    try:
        native.setValue(NSNumber.numberWithBool(False), forKey='drawsBackground')
    except Exception:
        pass
