from abc import ABC
from enum import Enum, auto
from typing import Any


class Column[T](ABC):
    @property
    def grid_column_template(self) -> str:
        """The width definition of the content as used by grid-template-columns"""
        return 'max-content'

    @property
    def header_content(self) -> str:
        """The content of the header as a string.
        A template can be used for more complex headers."""
        name = self.__class__.__name__
        raise NotImplementedError(
            f'{name}: header content needs to be implemented '
            'if a template for the header is not provided.'
        )

    @property
    def is_header_content_safe(self) -> bool:
        """Defines if the header content is safe to be displayed in Jinja.
        User-input strings should not be declared as safe.
        Useful to add light html formatting (ex: <b>last_name</b> first_name)"""
        return False

    @property
    def header_template(self) -> str | None:
        """The template to use for the header of the column.
        If None, the header content is used."""
        return None

    @property
    def header_classes(self) -> str:
        """CSS classes to use for the header."""
        return self.shared_classes

    def get_cell_content(self, object_: T) -> Any:
        """Get the content of a cell as a string from an object of the table.
        A template can be used for more complex cell contents."""
        name = self.__class__.__name__
        raise NotImplementedError(
            f'{name}: cell content needs to be implemented '
            'if a template for the cell is not provided.'
        )

    @property
    def is_cell_content_safe(self) -> bool:
        """Defines if the cell content is safe to be displayed in Jinja.
        User-input strings should not be declared as safe.
        Useful to add light html formatting (ex: <b>last_name</b> first_name)"""
        return False

    @property
    def cell_template(self) -> str | None:
        """The template to use for the cells. If None, the cell content is used."""
        return None

    def is_cell_blank_for(self, object_: T) -> bool:
        """Whether the cell is deliberately left empty for this object,
        whatever its content would be."""
        return False

    def is_cell_struck_for(self, object_: T) -> bool:
        """Whether the cell content is shown crossed out, the content
        itself being unchanged."""
        return False

    def get_cell_classes(self, object_: T) -> str:
        """CSS classes to use for the cells."""
        if self.is_cell_struck_for(object_):
            return f'{self.shared_classes} annulled'
        return self.shared_classes

    def get_footer_content(self, objects_: list[T]) -> str:
        """The content of the footer as a string.
        A template can be used for more complex headers."""
        return ''

    @property
    def is_footer_content_safe(self) -> bool:
        """Defines if the footer content is safe to be displayed in Jinja.
        User-input strings should not be declared as safe.
        Useful to add light html formatting (ex: <b>last_name</b> first_name)"""
        return False

    @property
    def footer_template(self) -> str | None:
        """The template to use for the footer of the column.
        If None, the footer content is used."""
        return None

    def get_footer_classes(self, objects_: list[T]) -> str:
        """CSS classes to use for the footer."""
        return self.shared_classes

    @property
    def shared_classes(self) -> str:
        """Classes shared between the header, the cells and the footer."""
        return ''


class ColumnUsage(Enum):
    SCREEN = auto()
    PRINT = auto()
