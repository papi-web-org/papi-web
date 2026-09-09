"""Restricting the height of the list a selection displays.

The list of a selection is as tall as what it holds, which fills the screen when
it holds the federations. A menu that does not fit the rectangle its delegate
confines it to becomes scrollable, which is how its height is restricted here.

This is the approach of the ``max_visible_items`` option added to Toga
(https://github.com/beeware/toga/pull/4691): once the option is released, this
module goes away and the option is passed to the selections instead.
"""

import sys

import toga

if sys.platform == 'darwin':
    from rubicon.objc import objc_method, objc_property

    # From the backend, which is what loads AppKit.
    from toga_cocoa.libs import NSMenu, NSObject, NSPoint, NSRect, NSScreen, NSSize

    #: The height of what a menu displays on top of its items, measured once.
    _menu_chrome_height: float | None = None

    def menu_chrome_height() -> float:
        """The height of the parts of a menu that are not its items. macOS
        exposes neither it nor the height of an item, and both depend on the
        version and on the settings of the user, so they are measured from
        menus holding one and two items."""
        global _menu_chrome_height
        if _menu_chrome_height is None:
            heights = []
            for item_count in (1, 2):
                menu = NSMenu.alloc().init()
                for index in range(item_count):
                    menu.addItemWithTitle(
                        f'item {index}', action=None, keyEquivalent=''
                    )
                heights.append(menu.size.height)
            item_height = heights[1] - heights[0]
            _menu_chrome_height = heights[0] - item_height
        return _menu_chrome_height

    class SelectionMenuDelegate(NSObject):  # type: ignore[misc, valid-type]
        button = objc_property(object, weak=True)
        max_visible_items = objc_property(object)

        @objc_method
        def confinementRectForMenu_onScreen_(self, menu, screen) -> NSRect:
            """The region the list is displayed in. A zero rectangle leaves it
            to macOS, which uses the whole screen."""
            no_confinement = NSRect(NSPoint(0, 0), NSSize(0, 0))
            max_visible_items = self.max_visible_items
            button = self.button
            if (
                max_visible_items is None
                or button is None
                or button.window is None
                or menu.numberOfItems <= max_visible_items
            ):
                return no_confinement
            if screen is None:
                screen = NSScreen.mainScreen
            if screen is None:
                return no_confinement

            # The height of an item comes from the menu itself, so that whatever
            # the items carry is taken into account.
            chrome = menu_chrome_height()
            item_height = (menu.size.height - chrome) / menu.numberOfItems
            height = chrome + item_height * max_visible_items

            # A list that would not fit the screen anyway is left to macOS,
            # which makes it scrollable and handles the edges of the screen.
            visible_frame = screen.visibleFrame
            if height >= visible_frame.size.height:
                return no_confinement

            # The list drops down from the top of the selection and can not be
            # displayed outside the rectangle, which is therefore a band of the
            # screen starting *height* below the top of the selection, and
            # covering it (a band that does not would display no list at all).
            button_frame = button.window.convertRectToScreen(
                button.convertRect(button.bounds, toView=None)
            )
            button_top = button_frame.origin.y + button_frame.size.height
            origin_y = max(visible_frame.origin.y, button_top - height)
            return NSRect(
                NSPoint(visible_frame.origin.x, origin_y),
                NSSize(
                    visible_frame.size.width,
                    button_top + button_frame.size.height - origin_y,
                ),
            )


def limit_popup_height(selection: toga.Selection, max_visible_items: int):
    """Displays at most *max_visible_items* items in the list of *selection*,
    which is scrolled to reach the others. Platforms whose list is bounded
    already are left alone."""
    if sys.platform != 'darwin':
        return
    button = selection._impl.native
    delegate = SelectionMenuDelegate.alloc().init()
    delegate.button = button
    delegate.max_visible_items = max_visible_items
    # The menu holds its delegate weakly, and the selection is what keeps this
    # one alive.
    selection._menu_delegate = delegate
    button.menu.delegate = delegate
