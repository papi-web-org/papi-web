"""Data model for a knock-out bracket diagram.

A :class:`BracketLayout` is a pure, render-ready description of a knock-out —
columns of match boxes grouped into sections (upper bracket, lower bracket,
grand final; or a single main bracket plus an optional third-place match).
The engine describes the match graph (:class:`MatchDescriptor`); the
tournament resolves each match's participants, scores and winner and builds
the layout. A print template walks it and draws the boxes and connectors.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchDescriptor:
    """Structural description of one bracket match, from the engine — before
    the participants' names, scores and winner are read from the results.
    ``source_top`` / ``source_bottom`` name the matches that feed each slot,
    for drawing the connector lines."""

    id: str
    section: str  # 'upper' | 'lower' | 'final' | 'main' | 'third'
    column: int  # 0-based position within the section
    round_name: str
    app_round: int  # the bracket stage, the key its boards are found by
    a_id: int | None
    b_id: int | None
    winner_id: int | None
    source_top: str | None
    source_bottom: str | None
    # The app rounds the match is played in — two for a variant that spreads a
    # match over two games. Empty means the stage is the round, one for one.
    played_rounds: tuple[int, ...] = ()


@dataclass(frozen=True)
class BracketSlot:
    """One side of a match box: a participant, their score, and whether they
    advanced. ``name`` is empty for a not-yet-decided or bye slot.
    ``participant_id`` is the player/team id (``None`` for an open slot), used
    to highlight a participant's whole path on hover. ``detail`` is the
    rating/type shown after a player's name; ``group`` is the participant's
    group (a second line, when the bracket is seeded by group); ``seed`` is the
    seed number (shown at the row end when *not* seeded by group)."""

    name: str
    score: str = ''
    winner: bool = False
    participant_id: int | None = None
    detail: str = ''
    group: str = ''
    seed: str = ''


@dataclass(frozen=True)
class BracketMatch:
    id: str
    top: BracketSlot
    bottom: BracketSlot
    source_top: str | None = None
    source_bottom: str | None = None


@dataclass(frozen=True)
class BracketColumn:
    name: str
    app_round: int  # the bracket stage — columns align by this (chronology)
    matches: tuple[BracketMatch, ...]
    app_rounds: tuple[int, ...] = ()  # the app rounds those matches are played in


@dataclass(frozen=True)
class BracketSection:
    key: str  # 'upper' | 'lower' | 'final' | 'main' | 'third'
    columns: tuple[BracketColumn, ...]


@dataclass(frozen=True)
class BracketLayout:
    sections: tuple[BracketSection, ...]
    is_double_elimination: bool
