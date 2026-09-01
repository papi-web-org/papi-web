"""Turn a :class:`~data.pairings.knockout_helpers.layout.BracketLayout` into absolute
SVG geometry — positioned match boxes, column headers and connector paths —
so the print template only has to emit shapes, not compute a layout.

Every match is placed left-to-right by its column and vertically by the
average height of the matches feeding it (falling back to even spacing for a
column with no in-diagram sources, e.g. a losers'-bracket entry round).
Because every match ends up with an absolute position, a connector can be
drawn for every source link — within a bracket or across brackets (the
winners' losers dropping down, the two champions meeting in the grand
final) — with no special cases.
"""

from dataclasses import dataclass

from data.pairings.knockout_helpers.layout import BracketLayout, BracketMatch

BOX_WIDTH = 210
# Tall enough for two lines per slot (the name, and the group/seed line).
BOX_HEIGHT = 58
COLUMN_GAP = 46
SECTION_GAP = 70
HEADER_HEIGHT = 44
MARGIN = 16
_UNIT = BOX_HEIGHT + 18  # vertical pitch between adjacent matches


@dataclass(frozen=True)
class PositionedMatch:
    match: BracketMatch
    x: float
    y: float  # box top


@dataclass(frozen=True)
class PositionedColumn:
    name: str
    x: float
    header_y: float
    app_round: int
    matches: tuple[PositionedMatch, ...]


@dataclass(frozen=True)
class ColumnBand:
    """A full-height background stripe for one app round (one column of the
    diagram), so the eye can follow a round top to bottom across brackets."""

    x: float
    width: float
    app_round: int


@dataclass(frozen=True)
class Connector:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class BracketSvg:
    columns: tuple[PositionedColumn, ...]
    connectors: tuple[Connector, ...]
    bands: tuple[ColumnBand, ...]
    width: float
    height: float
    box_width: int = BOX_WIDTH
    box_height: int = BOX_HEIGHT
    header_height: int = HEADER_HEIGHT


def build_svg(layout: BracketLayout) -> BracketSvg:
    centres: dict[str, tuple[float, float]] = {}  # match id -> (centre x, centre y)
    columns: list[PositionedColumn] = []

    main_sections = [s for s in layout.sections if s.key != 'final']
    final_sections = [s for s in layout.sections if s.key == 'final']

    section_of: dict[str, str] = {}
    first_section_top = HEADER_HEIGHT + MARGIN
    section_top: float = first_section_top
    section_bottom: float = section_top
    for section in main_sections:
        section_bottom = _place_section(
            section.columns,
            section_top=section_top,
            centres=centres,
            columns=columns,
            section_key=section.key,
            section_of=section_of,
        )
        section_top = section_bottom + SECTION_GAP

    # The grand final sits (by its later app round) to the right of the two
    # brackets, vertically centred over the whole diagram.
    if final_sections:
        centre_y = (first_section_top + section_bottom) / 2
        _place_section(
            final_sections[0].columns,
            section_top=centre_y,
            centres=centres,
            columns=columns,
            section_key='final',
            section_of=section_of,
        )

    connectors = _connectors(columns, centres, section_of)
    connectors += _final_connectors(
        final_sections[0] if final_sections else None, centres
    )
    width = max((column.x + BOX_WIDTH for column in columns), default=0) + MARGIN
    height = (
        max(
            (m.y + BOX_HEIGHT for column in columns for m in column.matches),
            default=0,
        )
        + MARGIN
    )
    # One full-height background stripe per app round (deduped by x). Nudged
    # right by a quarter-gap so a stripe edge lands mid-way along a box's
    # entry line rather than on the connector's vertical bar (which sits at
    # box_x - gap/2), keeping the bars cleanly inside a stripe.
    bands_by_round: dict[int, ColumnBand] = {}
    for column in columns:
        bands_by_round.setdefault(
            column.app_round,
            ColumnBand(
                x=column.x - COLUMN_GAP / 4,
                width=BOX_WIDTH + COLUMN_GAP,
                app_round=column.app_round,
            ),
        )
    return BracketSvg(
        columns=tuple(columns),
        connectors=tuple(connectors),
        bands=tuple(bands_by_round.values()),
        width=width,
        height=height,
    )


def _place_section(
    section_columns, *, section_top, centres, columns, section_key, section_of
) -> float:
    """Position one bracket's columns; return the section's bottom y.

    Columns are placed by their app round, so matches played at the same time
    line up in one column across brackets (chronological order). A match is
    centred on the matches feeding it *within this section*, so a later round
    pyramids over its own bracket. Cross-bracket feeds (the winners' losers
    dropping in, the two champions meeting in the final) are ignored for
    placement — they only draw a connector — otherwise a losers'-bracket row
    would be pulled up onto the winners' bracket."""
    header_y = section_top - 18  # padding between the round title and its boxes
    section_ids: set[str] = set()
    bottom = section_top
    for column in section_columns:
        x = MARGIN + (column.app_round - 1) * (BOX_WIDTH + COLUMN_GAP)
        placed: list[PositionedMatch] = []
        even_counter = 0
        for match in column.matches:
            source_centres = [
                centres[source][1]
                for source in (match.source_top, match.source_bottom)
                if source in section_ids
            ]
            if source_centres:
                centre_y = sum(source_centres) / len(source_centres)
            else:
                centre_y = section_top + even_counter * _UNIT + BOX_HEIGHT / 2
                even_counter += 1
            top = centre_y - BOX_HEIGHT / 2
            centres[match.id] = (x, centre_y)
            section_ids.add(match.id)
            section_of[match.id] = section_key
            placed.append(PositionedMatch(match=match, x=x, y=top))
            bottom = max(bottom, top + BOX_HEIGHT)
        columns.append(
            PositionedColumn(
                name=column.name,
                x=x,
                header_y=header_y,
                app_round=column.app_round,
                matches=tuple(placed),
            )
        )
    return bottom


def _connectors(columns, centres, section_of) -> list[Connector]:
    """The classic bracket connector, one per match: the matches feeding it
    run to a shared vertical bar in the gap, then a single line enters the
    box at its centre. Only same-bracket feeds are drawn — a cross-bracket
    drop (winners' loser into the losers' bracket, champions into the grand
    final) would be a long line across the diagram, so it is left implied."""
    connectors: list[Connector] = []
    for column in columns:
        for positioned in column.matches:
            match = positioned.match
            sources = [
                source
                for source in (match.source_top, match.source_bottom)
                if source in centres
                and section_of.get(source) == section_of.get(match.id)
            ]
            if not sources:
                continue
            bar_x = positioned.x - COLUMN_GAP / 2
            box_centre_y = positioned.y + BOX_HEIGHT / 2
            source_ys = [centres[source][1] for source in sources]
            for source in sources:
                sx, sy = centres[source]
                connectors.append(Connector(sx + BOX_WIDTH, sy, bar_x, sy))
            connectors.append(Connector(bar_x, min(source_ys), bar_x, max(source_ys)))
            connectors.append(
                Connector(bar_x, box_centre_y, positioned.x, box_centre_y)
            )
    return connectors


def _final_connectors(final_section, centres) -> list[Connector]:
    """The grand final's feeders — the winners' and losers' champions
    converging on it — plus a link from the grand final to its reset game.
    These are the one cross-bracket link worth drawing: both brackets meet
    here, so a bracket with no line into the final reads as unfinished."""
    connectors: list[Connector] = []
    if final_section is None or not final_section.columns:
        return connectors
    grand_final = final_section.columns[0].matches[0]
    if grand_final.id not in centres:
        return connectors
    gf_x, gf_centre_y = centres[grand_final.id]
    feeders = [
        source
        for source in (grand_final.source_top, grand_final.source_bottom)
        if source in centres
    ]
    if feeders:
        bar_x = gf_x - COLUMN_GAP / 2
        feeder_ys = [centres[source][1] for source in feeders]
        for source in feeders:
            sx, sy = centres[source]
            connectors.append(Connector(sx + BOX_WIDTH, sy, bar_x, sy))
        connectors.append(Connector(bar_x, min(feeder_ys), bar_x, max(feeder_ys)))
        connectors.append(Connector(bar_x, gf_centre_y, gf_x, gf_centre_y))
    # A reset game sits just to the right of the grand final, fed by it.
    if len(final_section.columns) > 1 and final_section.columns[1].matches:
        reset = final_section.columns[1].matches[0]
        if reset.id in centres:
            reset_x, reset_centre_y = centres[reset.id]
            connectors.append(
                Connector(gf_x + BOX_WIDTH, gf_centre_y, reset_x, reset_centre_y)
            )
    return connectors
