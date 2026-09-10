"""Team tie-break tests reproducing the TEC-2023 published exercises
(Exercises 34-41), running against pure ``TeamRecord`` inputs so the
math is verified independently of the storage layer.

Source crosstable: TEC-2023 ``Exercises in Tie-Breaking``, §2.3 (14
teams, 4 players each, 7 Swiss rounds). Unplayed-match scoring per
the tournament regulations on PDF page 9:

  PAB / HPB → 1 match point, 2 game points (a draw against a dummy)
  ZPB / -F  → 0 / 0
  +F        → 2 match points, 4 game points

Those exercises predate the March 2026 edition, which added the Art.
16.4 caps on the dummy opponent's score. The tie-breaks reproducing
their published values therefore carry the legacy option; the tests
written against the current rules build their own fixtures.
"""

from typing import ClassVar
from unittest import TestCase

import pytest

from data.tie_breaks.team_records import (
    TeamMatchRecord,
    TeamMatchType,
    TeamRecord,
    dummy_opponent_score,
)
from data.tie_breaks.team_tie_breaks import (
    BoardCountTieBreak,
    EDEKnockoutTieBreakOption,
    EDEKnockoutVariant,
    BottomBoardEliminationTieBreak,
    ESBVariant,
    ESBVariantTieBreakOption,
    ExtendedDirectEncounterTieBreak,
    ExtendedSonnebornBergerTeamTieBreak,
    MatchPointsVsGamePointsTieBreak,
    ScoresAndScheduleStrengthCombinationTieBreak,
    TeamTieBreakContext,
    TopBoardResultsTieBreak,
)
from data.tie_breaks.tie_breaks import StandardBuchholzTieBreak
from data.tie_breaks.options import (
    CutterTieBreakOption,
    CutterWithMedianTieBreakOption,
    LegacyMarch2026TieBreakOption,
    PlayedModifierTieBreakOption,
    TeamScoreTieBreakOption,
)
from data.tie_breaks.cutters import Cut1TieBreakCutter
from utils.enum import ScoreType


# ---------------------------------------------------------------------------
# Raw crosstable data (TEC-2023 §2.3, p. 6). Each tuple is one round's
# match for that team: (opponent_team_id, own_gp, match_type). own_mp
# is derived from own_gp vs opponent_gp (computed once below).
# ---------------------------------------------------------------------------

PLAYED = TeamMatchType.PLAYED
PAB = TeamMatchType.PAB
HPB = TeamMatchType.HPB
ZPB = TeamMatchType.ZPB
F_WIN = TeamMatchType.FORFEIT_WIN
F_LOSS = TeamMatchType.FORFEIT_LOSS

# Raw rounds: team_id -> list of (opponent_or_None, own_gp, match_type)
_RAW: dict[int, list[tuple[int | None, float, TeamMatchType]]] = {
    1: [  # Antelopes
        (8, 2.5, PLAYED),
        (4, 1.5, PLAYED),
        (7, 3.0, PLAYED),
        (2, 2.5, PLAYED),
        (5, 1.5, PLAYED),
        (None, 4.0, F_WIN),
        (3, 2.5, PLAYED),
    ],
    2: [  # Bonobos
        (9, 3.0, PLAYED),
        (3, 4.0, PLAYED),
        (5, 0.0, PLAYED),
        (1, 1.5, PLAYED),
        (13, 3.0, PLAYED),
        (4, 2.5, PLAYED),
        (10, 3.0, PLAYED),
    ],
    3: [  # Cougars
        (10, 2.5, PLAYED),
        (2, 0.0, PLAYED),
        (9, 3.0, PLAYED),
        (6, 2.5, PLAYED),
        (4, 3.0, PLAYED),
        (5, 3.5, PLAYED),
        (1, 1.5, PLAYED),
    ],
    4: [  # Deer
        (11, 3.0, PLAYED),
        (1, 2.5, PLAYED),
        (13, 3.0, PLAYED),
        (5, 3.5, PLAYED),
        (3, 1.0, PLAYED),
        (2, 1.5, PLAYED),
        (9, 2.5, PLAYED),
    ],
    5: [  # Elephants
        (12, 4.0, PLAYED),
        (6, 3.0, PLAYED),
        (2, 4.0, PLAYED),
        (4, 0.5, PLAYED),
        (1, 2.5, PLAYED),
        (3, 0.5, PLAYED),
        (13, 3.5, PLAYED),
    ],
    6: [  # Falcons
        (13, 2.0, PLAYED),
        (5, 1.0, PLAYED),
        (8, 3.0, PLAYED),
        (3, 1.5, PLAYED),
        (11, 2.5, PLAYED),
        (None, 0.0, F_LOSS),
        (12, 2.5, PLAYED),
    ],
    7: [  # Giraffes
        (14, 2.0, PLAYED),
        (8, 2.0, PLAYED),
        (1, 1.0, PLAYED),
        (10, 2.5, PLAYED),
        (9, 2.0, PLAYED),
        (13, 2.0, PLAYED),
        (None, 0.0, ZPB),
    ],
    8: [  # Hippopotami
        (1, 1.5, PLAYED),
        (7, 2.0, PLAYED),
        (6, 1.0, PLAYED),
        (12, 3.5, PLAYED),
        (10, 2.0, PLAYED),
        (9, 2.0, PLAYED),
        (11, 3.0, PLAYED),
    ],
    9: [  # Iguanas
        (2, 1.0, PLAYED),
        (12, 4.0, PLAYED),
        (3, 1.0, PLAYED),
        (14, 3.0, PLAYED),
        (7, 2.0, PLAYED),
        (8, 2.0, PLAYED),
        (4, 1.5, PLAYED),
    ],
    10: [  # Jackals
        (3, 1.5, PLAYED),
        (11, 1.5, PLAYED),
        (12, 2.5, PLAYED),
        (7, 1.5, PLAYED),
        (8, 2.0, PLAYED),
        (14, 3.0, PLAYED),
        (2, 1.0, PLAYED),
    ],
    11: [  # Koalas
        (4, 1.0, PLAYED),
        (10, 2.5, PLAYED),
        (14, 2.0, PLAYED),
        (13, 1.5, PLAYED),
        (6, 1.5, PLAYED),
        (12, 2.0, PLAYED),
        (8, 1.0, PLAYED),
    ],
    12: [  # Lynxes
        (5, 0.0, PLAYED),
        (9, 0.0, PLAYED),
        (10, 1.5, PLAYED),
        (8, 0.5, PLAYED),
        (None, 2.0, PAB),
        (11, 2.0, PLAYED),
        (6, 1.5, PLAYED),
    ],
    13: [  # Moose
        (6, 2.0, PLAYED),
        (14, 2.5, PLAYED),
        (4, 1.0, PLAYED),
        (11, 2.5, PLAYED),
        (2, 1.0, PLAYED),
        (7, 2.0, PLAYED),
        (5, 0.5, PLAYED),
    ],
    14: [  # Narwhals
        (7, 2.0, PLAYED),
        (13, 1.5, PLAYED),
        (11, 2.0, PLAYED),
        (9, 1.0, PLAYED),
        (None, 2.0, HPB),
        (10, 1.0, PLAYED),
        (None, 2.0, PAB),
    ],
}

_NAMES = {
    1: 'Antelopes',
    2: 'Bonobos',
    3: 'Cougars',
    4: 'Deer',
    5: 'Elephants',
    6: 'Falcons',
    7: 'Giraffes',
    8: 'Hippopotami',
    9: 'Iguanas',
    10: 'Jackals',
    11: 'Koalas',
    12: 'Lynxes',
    13: 'Moose',
    14: 'Narwhals',
}


def _build_records() -> dict[int, TeamRecord]:
    """Convert ``_RAW`` into ``TeamRecord`` instances, deriving each
    match's own_mp from the played-match GP comparison and the
    tournament's unplayed-match rules (PAB / HPB → 1 MP, +F → 2 MP,
    everything else → 0 MP). own_gp comes straight from the raw data.
    """
    # First pass: collect own_gp per (team, round) so we can look up the
    # opponent's own_gp for played-match MP derivation.
    own_gp_lookup: dict[tuple[int, int], float] = {}
    for team_id, rounds in _RAW.items():
        for round_index, (_opp, own_gp, _kind) in enumerate(rounds, start=1):
            own_gp_lookup[(team_id, round_index)] = own_gp

    records: dict[int, TeamRecord] = {}
    for team_id, rounds in _RAW.items():
        matches: list[TeamMatchRecord] = []
        total_mp = 0.0
        total_gp = 0.0
        for round_index, (opp_id, own_gp, kind) in enumerate(rounds, start=1):
            if kind == PLAYED:
                assert opp_id is not None
                opp_gp = own_gp_lookup[(opp_id, round_index)]
                if own_gp > opp_gp:
                    own_mp = 2.0
                elif own_gp < opp_gp:
                    own_mp = 0.0
                else:
                    own_mp = 1.0
            elif kind in (PAB, HPB):
                own_mp = 1.0
            elif kind == F_WIN:
                own_mp = 2.0
            else:  # ZPB, F_LOSS
                own_mp = 0.0
            matches.append(
                TeamMatchRecord(
                    round_=round_index,
                    opponent_id=opp_id,
                    own_mp=own_mp,
                    own_gp=own_gp,
                    match_type=kind,
                )
            )
            total_mp += own_mp
            total_gp += own_gp
        records[team_id] = TeamRecord(
            team_id=team_id,
            name=_NAMES[team_id],
            total_mp=total_mp,
            total_gp=total_gp,
            matches=matches,
        )
    return records


_CONTEXT = TeamTieBreakContext(
    primary_score=ScoreType.MATCH_POINTS,
    secondary_score=ScoreType.GAME_POINTS,
    rounds=7,
    win_mp=2.0,
    draw_mp=1.0,
    loss_mp=0.0,
    team_player_count=4,
    # 4-player teams, 1-½-0 game scoring → a half match = 4 × ½ = 2 GP.
    draw_gp=2.0,
)


# Sanity-check expected totals from the published crosstable (§2.3 p.6).
_EXPECTED_TOTALS: dict[int, tuple[float, float]] = {
    1: (10, 17.5),
    2: (10, 17.0),
    3: (10, 16.0),
    4: (10, 17.0),
    5: (10, 18.0),
    6: (7, 12.5),
    7: (6, 11.5),
    8: (7, 15.0),
    9: (6, 14.5),
    10: (5, 13.0),
    11: (4, 11.5),
    12: (2, 7.5),
    13: (6, 11.5),
    14: (4, 11.5),
}


def _cut1_option() -> CutterTieBreakOption:
    return CutterTieBreakOption(Cut1TieBreakCutter.static_id())


def _bh(team_score: str, cut1: bool = False) -> StandardBuchholzTieBreak:
    """FIDE MTB26 BH:<team_score> [/C1] for the TEC fixture, in legacy
    mode — see the module docstring on the Art. 16.4 caps."""
    opts: list = [
        TeamScoreTieBreakOption(team_score),
        LegacyMarch2026TieBreakOption(True),
    ]
    if cut1:
        opts.append(CutterWithMedianTieBreakOption(Cut1TieBreakCutter.static_id()))
    return StandardBuchholzTieBreak(opts)


@pytest.mark.unit
class TecTeamTieBreakTestCase(TestCase):
    """Reproduces TEC-2023 Exercises 34-41 using pure TeamRecord input."""

    records: ClassVar[dict[int, TeamRecord]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = _build_records()

    def test_team_totals_match_published_crosstable(self):
        """Sanity check: the derived totals match the §2.3 crosstable."""
        for team_id, (mp, gp) in _EXPECTED_TOTALS.items():
            rec = self.records[team_id]
            self.assertEqual(rec.total_mp, mp, f'MP for team {team_id}')
            self.assertEqual(rec.total_gp, gp, f'GP for team {team_id}')

    # ----- Exercise 34: MPvGP -----------------------------------------------

    def test_ex34_mpvgp_with_mp_primary_returns_gp(self):
        """When MP is primary, MPvGP returns the GP total."""
        tb = MatchPointsVsGamePointsTieBreak([])
        for team_id, (_mp, gp) in _EXPECTED_TOTALS.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertEqual(value, gp, f'MPvGP for team {team_id}')

    def test_ex34_mpvgp_with_gp_primary_returns_mp(self):
        """And vice versa when GP is the primary score."""
        gp_context = TeamTieBreakContext(
            primary_score=ScoreType.GAME_POINTS,
            secondary_score=ScoreType.MATCH_POINTS,
            rounds=7,
            win_mp=2.0,
            draw_mp=1.0,
            loss_mp=0.0,
            team_player_count=4,
            draw_gp=2.0,
        )
        tb = MatchPointsVsGamePointsTieBreak([])
        for team_id, (mp, _gp) in _EXPECTED_TOTALS.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                gp_context,
                after_round=7,
            )
            self.assertEqual(value, mp, f'MPvGP for team {team_id}')

    # ----- Exercise 35: Sistema Buchholz (BH) with MP primary --------------

    # PDF Ex 35 p.55 final table (BH values, MP primary).
    EX35_BH_MP = {
        1: 64,
        2: 57,
        3: 58,
        4: 56,
        5: 55,
        6: 46,
        7: 44,
        8: 41,
        9: 50,
        10: 44,
        11: 41,
        12: 41,
        13: 52,
        14: 36,
    }

    def test_ex35_buchholz_total_mp_primary(self):
        tb = _bh(TeamScoreTieBreakOption.VALUE_MP)
        for team_id, expected in self.EX35_BH_MP.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertEqual(value, expected, f'BH for team {team_id}')

    # ----- Exercise 36: BH-C1 with MP primary -------------------------------

    EX36_BH_C1_MP = {
        1: 57,
        2: 52,
        3: 53,
        4: 52,
        5: 53,
        6: 39,
        7: 38,
        8: 39,
        9: 48,
        10: 42,
        11: 39,
        12: 39,
        13: 48,
        14: 32,
    }

    def test_ex36_buchholz_cut1_mp_primary(self):
        tb = _bh(TeamScoreTieBreakOption.VALUE_MP, cut1=True)
        for team_id, expected in self.EX36_BH_C1_MP.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertEqual(value, expected, f'BH-C1 for team {team_id}')

    # ----- Exercise 37: BH-C1 with GP primary -------------------------------

    # From the PDF Ex 37 table (BH-C1 with GP-primary scoring).
    EX37_BH_C1_GP = {
        1: 100.5,
        2: 96.0,
        3: 97.0,
        4: 94.5,
        5: 91.5,
        6: 79.5,
        7: 83.0,
        8: 82.5,
        9: 90.0,
        10: 84.5,
        11: 80.5,
        12: 84.5,
        13: 89.5,
        14: 75.5,
    }

    def test_ex37_buchholz_cut1_gp_primary(self):
        gp_context = TeamTieBreakContext(
            primary_score=ScoreType.GAME_POINTS,
            secondary_score=ScoreType.MATCH_POINTS,
            rounds=7,
            win_mp=2.0,
            draw_mp=1.0,
            loss_mp=0.0,
            team_player_count=4,
            draw_gp=2.0,
        )
        tb = _bh(TeamScoreTieBreakOption.VALUE_GP, cut1=True)
        for team_id, expected in self.EX37_BH_C1_GP.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                gp_context,
                after_round=7,
            )
            self.assertAlmostEqual(
                value, expected, places=1, msg=f'BH-C1 GP for team {team_id}'
            )

    # ----- Exercise 38: EMMSB-C1 for 10-MP teams ----------------------------

    EX38_EMMSB_TOTAL = {1: 88, 2: 74, 3: 76, 4: 72, 5: 70}
    EX38_EMMSB_C1 = {1: 74, 2: 64, 3: 66, 4: 64, 5: 66}

    def _esb(self, variant: ESBVariant, cut1: bool = False):
        opts: list = [
            ESBVariantTieBreakOption(variant.value),
            LegacyMarch2026TieBreakOption(True),
        ]
        if cut1:
            from data.tie_breaks.team_tie_breaks import ESBCutterTieBreakOption

            opts.append(ESBCutterTieBreakOption(Cut1TieBreakCutter.static_id()))
        return ExtendedSonnebornBergerTeamTieBreak(opts)

    def test_ex38_emmsb_total_for_tied_teams(self):
        tb = self._esb(ESBVariant.EMMSB)
        for team_id, expected in self.EX38_EMMSB_TOTAL.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertEqual(value, expected, f'EMMSB for team {team_id}')

    def test_ex38_emmsb_cut1_for_tied_teams(self):
        tb = self._esb(ESBVariant.EMMSB, cut1=True)
        for team_id, expected in self.EX38_EMMSB_C1.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertEqual(value, expected, f'EMMSB-C1 for team {team_id}')

    # ----- Exercise 39: EGMSB (no cut) --------------------------------------

    # PDF Ex 39 p.59 — opponent GP × own MP.
    EX39_EGMSB = {1: 158.0, 2: 144.0, 3: 150.0, 4: 146.0, 5: 132.0}

    def test_ex39_egmsb_for_tied_teams(self):
        tb = self._esb(ESBVariant.EGMSB)
        for team_id, expected in self.EX39_EGMSB.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertAlmostEqual(
                value, expected, places=1, msg=f'EGMSB for team {team_id}'
            )

    # ----- Exercise 40: EMGSB for 6-MP teams --------------------------------

    # PDF Ex 40 p.60 — opponent MP × own GP. Worked examples for #7, #9, #13.
    EX40_EMGSB = {7: 68.5, 9: 83.0, 13: 73.0}

    def test_ex40_emgsb_for_six_mp_teams(self):
        tb = self._esb(ESBVariant.EMGSB)
        for team_id, expected in self.EX40_EMGSB.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertAlmostEqual(
                value, expected, places=1, msg=f'EMGSB for team {team_id}'
            )

    # ----- Exercise 41: EGGSB for 7-MP teams --------------------------------

    # PDF Ex 41 p.60 — opponent GP × own GP. Worked examples for #6 and #8.
    EX41_EGGSB = {6: 157.5, 8: 181.5}

    def test_ex41_eggsb_for_seven_mp_teams(self):
        tb = self._esb(ESBVariant.EGGSB)
        for team_id, expected in self.EX41_EGGSB.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertAlmostEqual(
                value, expected, places=2, msg=f'EGGSB for team {team_id}'
            )

    # ----- Summary table (page 61) sanity-checks for the rest of the field -

    # Per-team EMMSB / EGMSB / EMGSB / EGGSB from the page 61 wrap-up
    # table. Falcons (#6) EMMSB is **32** here, not the 33 the PDF
    # summary prints — the PDF itself states on page 60 that
    # "forfeit losses... [their] contribution is always null" (the
    # rule confirmed by every other team and by Falcons' EGM/EMG/EGG
    # values, which all match the summary), so the printed 33 is a
    # transcription error in that single cell.
    EX_SUMMARY = {
        # team_id: (EMMSB, EGMSB, EMGSB, EGGSB)
        1: (88, 158.0, 158.5, 283.0),
        2: (74, 144.0, 131.0, 249.75),
        3: (76, 150.0, 128.0, 247.5),
        4: (72, 146.0, 130.0, 253.5),
        5: (70, 132.0, 125.0, 236.0),
        6: (32, 79.5, 73.0, 157.5),  # PDF prints EMMSB 33 — typo, correct value 32
        7: (33, 78.5, 68.5, 155.0),
        8: (30, 79.0, 77.0, 181.5),
        9: (26, 66.5, 83.0, 180.0),
        10: (19, 53.0, 72.5, 161.75),
        11: (16, 45.0, 61.0, 138.5),
        12: (6, 19.0, 33.5, 83.75),
        13: (30, 72.0, 73.0, 152.5),
        14: (19, 48.0, 58.0, 140.75),
    }

    def test_summary_table_emm_egm_emg_egg(self):
        for team_id, (emm, egm, emg, egg) in self.EX_SUMMARY.items():
            self._check_variant(team_id, ESBVariant.EMMSB, emm)
            self._check_variant(team_id, ESBVariant.EGMSB, egm)
            self._check_variant(team_id, ESBVariant.EMGSB, emg)
            self._check_variant(team_id, ESBVariant.EGGSB, egg)

    def _check_variant(
        self, team_id: int, variant: ESBVariant, expected: float
    ) -> None:
        tb = self._esb(variant)
        value = tb.compute_team_value(
            self.records[team_id],
            self.records,
            _CONTEXT,
            after_round=7,
        )
        self.assertAlmostEqual(
            value,
            expected,
            places=2,
            msg=f'{variant.value} for team {team_id}',
        )

    # ----- Exercise 42: EDE on 4-MP tied {Koalas, Narwhals} -----------------

    def test_ex42_ede_two_teams_drew(self):
        """Koalas (11) and Narwhals (14) drew their direct match; sub-MP
        and sub-GP both yield identical sub-scores → EDE cannot split."""
        ede = ExtendedDirectEncounterTieBreak([])
        group = [self.records[11], self.records[14]]
        values = ede.compute_all_team_values(
            [group], self.records, _CONTEXT, after_round=7
        )
        # Same rank delta = still tied.
        self.assertEqual(values[11], values[14])

    # ----- Exercise 43: EDE on 7-MP tied {Falcons, Hippopotami} -------------

    def test_ex43_ede_two_teams_one_won(self):
        """Falcons beat Hippopotami 3-1 in R3 → Falcons ranks ahead."""
        ede = ExtendedDirectEncounterTieBreak([])
        group = [self.records[6], self.records[8]]
        values = ede.compute_all_team_values(
            [group], self.records, _CONTEXT, after_round=7
        )
        # Higher delta = better. Falcons should outrank Hippopotami.
        self.assertGreater(values[6], values[8])
        self.assertEqual({values[6], values[8]}, {0.0, 1.0})

    # ----- Exercise 44: EDE on 6-MP tied {Giraffes, Iguanas, Moose} --------

    def test_ex44_ede_three_teams_unresolved(self):
        """Iguanas and Moose never played each other; even after the
        secondary-score retry, min/max ranges of the missing match keep
        all three in one bracket → EDE leaves the group tied."""
        ede = ExtendedDirectEncounterTieBreak([])
        group = [self.records[7], self.records[9], self.records[13]]
        values = ede.compute_all_team_values(
            [group], self.records, _CONTEXT, after_round=7
        )
        self.assertEqual(values[7], values[9])
        self.assertEqual(values[9], values[13])

    # ----- Exercise 45: EDE on 10-MP tied {1..5} ---------------------------

    EX45_EDE_RANK = {  # final rank, 0 = best
        4: 0,
        2: 1,
        1: 2,
        3: 3,
        5: 4,
    }

    def test_ex45_ede_five_teams_resolved_via_secondary(self):
        """The fallback to the secondary score — and, decisively, which
        score a subgroup uses afterwards.

        All five teams played each other and their sub-crosstable match
        points are tied 4-4-4-4-4, so the primary score splits nothing
        and EDE falls back to game points: 8.5 for team 4, 8.0 for
        teams 1-3, 7.5 for team 5.

        The subgroup {1, 2, 3} then decides the question, because its
        own sub-crosstable ranks differently under each score — 2, 1, 3
        by game points (5.5 / 5.0 / 1.5) but 1, 2, 3 by match points
        (4 / 2 / 0). The published answer is #4, #2, #1, #3, #5, i.e.
        game points, and the exercise spells out why: the subgroup is
        judged "still using the GP because we are still within the same
        application of the tie-break, as indicated by [6], endnote".
        """
        ede = ExtendedDirectEncounterTieBreak([])
        group = [self.records[i] for i in (1, 2, 3, 4, 5)]
        values = ede.compute_all_team_values(
            [group], self.records, _CONTEXT, after_round=7
        )
        # Higher delta = better; convert to final standings.
        order = sorted(values.items(), key=lambda kv: -kv[1])
        ranks = {team_id: rank for rank, (team_id, _v) in enumerate(order)}
        self.assertEqual(ranks, self.EX45_EDE_RANK)

    # ----- Exercise 49: SSSC values for every team -------------------------

    EX49_SSSC = {
        1: 38.83,
        2: 36.00,
        3: 35.33,
        4: 35.67,
        5: 36.33,
        6: 27.83,
        7: 26.17,
        8: 28.67,
        9: 31.17,
        10: 27.67,
        11: 25.17,
        12: 21.17,
        13: 28.83,
        14: 23.50,
    }

    def test_ex49_sssc_normalisation_factor(self):
        """7 rounds × 2 MP-per-win = 14 max primary; 4 GP-per-match max
        secondary; F_N = floor(14/4) = 3."""
        factor = ScoresAndScheduleStrengthCombinationTieBreak.normalization_factor(
            _CONTEXT
        )
        self.assertEqual(factor, 3)

    def test_ex49_sssc_all_teams(self):
        tb = ScoresAndScheduleStrengthCombinationTieBreak(
            [LegacyMarch2026TieBreakOption(True)]
        )
        for team_id, expected in self.EX49_SSSC.items():
            value = tb.compute_team_value(
                self.records[team_id],
                self.records,
                _CONTEXT,
                after_round=7,
            )
            self.assertAlmostEqual(
                value, expected, places=2, msg=f'SSSC for team {team_id}'
            )

    def test_ex49_sssc_normalization_factor_gp_primary_example(self):
        """PDF Ex 49 second example: 9 rounds, 4-player teams, GP
        primary → F_N = floor(36/2) = 18."""
        ctx = TeamTieBreakContext(
            primary_score=ScoreType.GAME_POINTS,
            secondary_score=ScoreType.MATCH_POINTS,
            rounds=9,
            win_mp=2.0,
            draw_mp=1.0,
            loss_mp=0.0,
            team_player_count=4,
            draw_gp=2.0,
        )
        factor = ScoresAndScheduleStrengthCombinationTieBreak.normalization_factor(ctx)
        self.assertEqual(factor, 18)


@pytest.mark.unit
class BerlinTieBreakTestCase(TestCase):
    """FFE Berlin / Coefficient d'échiquier (FFE rules §11.1).

    Reproduces the worked example from the FFE rulebook: 8-board match,
    Team A scores 1-0-0-½-1-0-½-1 → Berlin 16.5;
    Team B scores 0-1-1-½-0-1-½-0 → Berlin 19.5
    (so Team B wins on Berlin despite a 4-4 game-point draw)."""

    def test_ffe_rulebook_eight_board_example(self):
        from plugins.ffe.ffe_tie_breaks import BerlinTieBreak

        team_a_boards = (1.0, 0.0, 0.0, 0.5, 1.0, 0.0, 0.5, 1.0)
        team_b_boards = (0.0, 1.0, 1.0, 0.5, 0.0, 1.0, 0.5, 0.0)
        team_a = TeamRecord(
            team_id=1,
            name='A',
            total_mp=1.0,
            total_gp=4.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=1.0,
                    own_gp=4.0,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=team_a_boards,
                ),
            ],
        )
        team_b = TeamRecord(
            team_id=2,
            name='B',
            total_mp=1.0,
            total_gp=4.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=1,
                    own_mp=1.0,
                    own_gp=4.0,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=team_b_boards,
                ),
            ],
        )
        records = {1: team_a, 2: team_b}
        context = TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=1,
            win_mp=2.0,
            draw_mp=1.0,
            loss_mp=0.0,
            team_player_count=8,
            draw_gp=4.0,
        )
        tb = BerlinTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team_a, records, context, after_round=1),
            16.5,
        )
        self.assertEqual(
            tb.compute_team_value(team_b, records, context, after_round=1),
            19.5,
        )

    def test_berlin_ignores_unplayed_matches_with_no_board_data(self):
        """Forfeits / byes record no board_scores → Berlin contribution
        is zero for that round, matching the FFE convention that only
        actually-played boards carry a coefficient."""
        from plugins.ffe.ffe_tie_breaks import BerlinTieBreak

        team = TeamRecord(
            team_id=1,
            name='A',
            total_mp=2.0,
            total_gp=4.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=2.0,
                    own_gp=4.0,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=(1.0, 1.0, 1.0, 1.0),
                ),
                TeamMatchRecord(
                    round_=2,
                    opponent_id=None,
                    own_mp=0.0,
                    own_gp=0.0,
                    match_type=TeamMatchType.FORFEIT_LOSS,
                    board_scores=(),
                ),
            ],
        )
        records = {1: team}
        context = TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=2,
            win_mp=2.0,
            draw_mp=1.0,
            loss_mp=0.0,
            team_player_count=4,
            draw_gp=2.0,
        )
        tb = BerlinTieBreak([])
        # 4 + 3 + 2 + 1 = 10 from R1 only; R2 forfeit contributes 0.
        self.assertEqual(
            tb.compute_team_value(team, records, context, after_round=2),
            10.0,
        )


@pytest.mark.unit
class GamePointsDifferentialTieBreakTestCase(TestCase):
    """FFE *Différentiel des points de parties* — Σ (own_gp - opp_gp)
    across rounds. Coupe Loubatière §4.4.a."""

    @staticmethod
    def _context() -> TeamTieBreakContext:
        return TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=3,
            win_mp=3.0,
            draw_mp=2.0,
            loss_mp=1.0,
            team_player_count=4,
            draw_gp=0.0,
        )

    def test_two_team_played_match_subtracts_opponent_gp(self):
        from plugins.ffe.ffe_tie_breaks import GamePointsDifferentialTieBreak

        team_a = TeamRecord(
            team_id=1,
            name='A',
            total_mp=0.0,
            total_gp=3.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=3.0,
                    own_gp=3.0,
                    match_type=TeamMatchType.PLAYED,
                ),
            ],
        )
        team_b = TeamRecord(
            team_id=2,
            name='B',
            total_mp=0.0,
            total_gp=1.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=1,
                    own_mp=1.0,
                    own_gp=1.0,
                    match_type=TeamMatchType.PLAYED,
                ),
            ],
        )
        records = {1: team_a, 2: team_b}
        tb = GamePointsDifferentialTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team_a, records, self._context(), after_round=1),
            2.0,
        )
        self.assertEqual(
            tb.compute_team_value(team_b, records, self._context(), after_round=1),
            -2.0,
        )

    def test_pab_counts_full_own_gp_with_no_subtraction(self):
        """No opponent → no opp_gp → differential = own_gp."""
        from plugins.ffe.ffe_tie_breaks import GamePointsDifferentialTieBreak

        team = TeamRecord(
            team_id=1,
            name='A',
            total_mp=3.0,
            total_gp=4.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=None,
                    own_mp=3.0,
                    own_gp=4.0,
                    match_type=TeamMatchType.PAB,
                ),
            ],
        )
        tb = GamePointsDifferentialTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=1),
            4.0,
        )

    def test_forfeit_loss_contributes_zero(self):
        from plugins.ffe.ffe_tie_breaks import GamePointsDifferentialTieBreak

        team = TeamRecord(
            team_id=1,
            name='A',
            total_mp=0.0,
            total_gp=0.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=0.0,
                    own_gp=0.0,
                    match_type=TeamMatchType.FORFEIT_LOSS,
                ),
            ],
        )
        tb = GamePointsDifferentialTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=1),
            0.0,
        )

    def test_sums_across_rounds_and_respects_after_round(self):
        from plugins.ffe.ffe_tie_breaks import GamePointsDifferentialTieBreak

        team_a = TeamRecord(
            team_id=1,
            name='A',
            total_mp=0.0,
            total_gp=0.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=3.0,
                    own_gp=3.0,
                    match_type=TeamMatchType.PLAYED,
                ),
                TeamMatchRecord(
                    round_=2,
                    opponent_id=2,
                    own_mp=1.0,
                    own_gp=1.0,
                    match_type=TeamMatchType.PLAYED,
                ),
            ],
        )
        team_b = TeamRecord(
            team_id=2,
            name='B',
            total_mp=0.0,
            total_gp=0.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=1,
                    own_mp=1.0,
                    own_gp=1.0,
                    match_type=TeamMatchType.PLAYED,
                ),
                TeamMatchRecord(
                    round_=2,
                    opponent_id=1,
                    own_mp=1.0,
                    own_gp=2.0,
                    match_type=TeamMatchType.PLAYED,
                ),
            ],
        )
        records = {1: team_a, 2: team_b}
        tb = GamePointsDifferentialTieBreak([])
        # After R1 only: A = 3-1 = +2
        self.assertEqual(
            tb.compute_team_value(team_a, records, self._context(), after_round=1),
            2.0,
        )
        # After R2: A = (3-1) + (1-2) = +1
        self.assertEqual(
            tb.compute_team_value(team_a, records, self._context(), after_round=2),
            1.0,
        )

    def test_negative_match_total_clamps_before_subtracting(self):
        from plugins.ffe.ffe_tie_breaks import GamePointsDifferentialTieBreak

        # Raw match: A=2, B=-1 → adjusted A=2, B=0.
        team_a = TeamRecord(
            team_id=1,
            name='A',
            total_mp=0.0,
            total_gp=2.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=3.0,
                    own_gp=2.0,
                    match_type=TeamMatchType.PLAYED,
                )
            ],
        )
        team_b = TeamRecord(
            team_id=2,
            name='B',
            total_mp=0.0,
            total_gp=-1.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=1,
                    own_mp=1.0,
                    own_gp=-1.0,
                    match_type=TeamMatchType.PLAYED,
                )
            ],
        )
        records = {1: team_a, 2: team_b}
        tb = GamePointsDifferentialTieBreak([])
        # A: 2 - 0 = +2 ; B: 0 - 2 = -2
        self.assertEqual(
            tb.compute_team_value(team_a, records, self._context(), after_round=1),
            2.0,
        )
        self.assertEqual(
            tb.compute_team_value(team_b, records, self._context(), after_round=1),
            -2.0,
        )


@pytest.mark.unit
class GamePointsForTieBreakTestCase(TestCase):
    """FFE *Points de parties « pour »* — Σ of each match's own score
    floored at 0."""

    @staticmethod
    def _context() -> TeamTieBreakContext:
        return TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=3,
            win_mp=3.0,
            draw_mp=2.0,
            loss_mp=1.0,
            team_player_count=4,
            draw_gp=0.0,
        )

    def test_sums_clamped_match_scores(self):
        from plugins.ffe.ffe_tie_breaks import GamePointsForTieBreak

        team = TeamRecord(
            team_id=1,
            name='A',
            total_mp=0.0,
            total_gp=0.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=2,
                    own_mp=3.0,
                    own_gp=2.5,
                    match_type=TeamMatchType.PLAYED,
                ),
                # Negative raw match score clamps to 0 (not -1).
                TeamMatchRecord(
                    round_=2,
                    opponent_id=3,
                    own_mp=0.0,
                    own_gp=-1.0,
                    match_type=TeamMatchType.PLAYED,
                ),
                TeamMatchRecord(
                    round_=3,
                    opponent_id=None,
                    own_mp=3.0,
                    own_gp=4.0,
                    match_type=TeamMatchType.PAB,
                ),
            ],
        )
        tb = GamePointsForTieBreak([])
        # 2.5 + max(0,-1) + 4 = 6.5 ; respects after_round.
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=3),
            6.5,
        )
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=1),
            2.5,
        )


@pytest.mark.unit
class LowestOwnAverageRatingTieBreakTestCase(TestCase):
    """FFE *Moyenne des derniers Elo diffusés, la plus basse*. The
    tie-break reads ``TeamRecord.own_avg_rating`` and returns its
    negation so the lowest team wins the descending sort."""

    @staticmethod
    def _context() -> TeamTieBreakContext:
        return TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=3,
            win_mp=3.0,
            draw_mp=2.0,
            loss_mp=1.0,
            team_player_count=4,
            draw_gp=0.0,
        )

    @staticmethod
    def _team(
        team_id: int, name: str, ratings_per_round: list[tuple[int | None, ...]]
    ) -> TeamRecord:
        return TeamRecord(
            team_id=team_id,
            name=name,
            total_mp=0.0,
            total_gp=0.0,
            matches=[
                TeamMatchRecord(
                    round_=round_,
                    opponent_id=None,
                    own_mp=0.0,
                    own_gp=0.0,
                    match_type=TeamMatchType.PLAYED,
                    board_ratings=ratings,
                )
                for round_, ratings in enumerate(ratings_per_round, start=1)
            ],
        )

    def test_lower_rating_team_outranks_higher(self):
        from plugins.ffe.ffe_tie_breaks import LowestOwnAverageRatingTieBreak

        # One round, 4-board team, every player rated.
        low = self._team(1, 'Low', [(1400, 1500, 1500, 1600)])  # avg 1500
        high = self._team(2, 'High', [(1800, 1800, 1800, 1800)])  # avg 1800
        records = {1: low, 2: high}
        tb = LowestOwnAverageRatingTieBreak([])
        # Tie-break is descending — the higher returned value wins.
        # Lower rating must return the larger (less-negative) value.
        self.assertGreater(
            tb.compute_team_value(low, records, self._context(), after_round=1),
            tb.compute_team_value(high, records, self._context(), after_round=1),
        )
        self.assertEqual(
            tb.compute_team_value(low, records, self._context(), after_round=1),
            -1500.0,
        )

    def test_weighted_by_appearances_across_rounds(self):
        """A regular starter counts in every round; a substitute fielded
        once weighs 1/N. The average is over (player, round) samples,
        not over the roster."""
        from plugins.ffe.ffe_tie_breaks import LowestOwnAverageRatingTieBreak

        # 3 rounds, board 4 occupied by 1200-rated player only in R3.
        team = self._team(
            1,
            'A',
            [
                (1500, 1500, 1500, 1500),
                (1500, 1500, 1500, 1500),
                (1500, 1500, 1500, 1200),
            ],
        )
        tb = LowestOwnAverageRatingTieBreak([])
        # (11 × 1500 + 1 × 1200) / 12 = 1475
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=3),
            -1475.0,
        )

    def test_unrated_players_excluded_from_average(self):
        from plugins.ffe.ffe_tie_breaks import LowestOwnAverageRatingTieBreak

        team = self._team(1, 'A', [(1600, 1400, None, None)])  # avg of two rated
        tb = LowestOwnAverageRatingTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=1),
            -1500.0,
        )

    def test_no_ratings_returns_zero(self):
        from plugins.ffe.ffe_tie_breaks import LowestOwnAverageRatingTieBreak

        team = TeamRecord(
            team_id=1,
            name='Empty',
            total_mp=0.0,
            total_gp=0.0,
        )
        tb = LowestOwnAverageRatingTieBreak([])
        self.assertEqual(
            tb.compute_team_value(team, {1: team}, self._context(), after_round=1),
            0.0,
        )


# ---------------------------------------------------------------------------
# Art. 12 board tie-breaks (BC / TBR / BBE)
# ---------------------------------------------------------------------------

# Two rounds of 4-board matches, chosen so the three tie-breaks disagree:
# A and B are level on boards 1 and 2, A is ahead on board 3 and B on
# board 4. TBR therefore favours A (board 3 decides), while BC favours A
# too (B's points sit on the cheapest board), and C is level with A on
# every board total but with its points on different boards.
_BOARD_SCORES: dict[int, list[tuple[float, ...]]] = {
    1: [(1.0, 0.0, 1.0, 0.5), (0.5, 1.0, 0.0, 0.0)],  # A → 1.5, 1, 1, .5
    2: [(0.5, 1.0, 0.0, 1.0), (1.0, 0.0, 0.5, 0.5)],  # B → 1.5, 1, .5, 1.5
    3: [(0.5, 0.5, 1.0, 1.0), (1.0, 0.5, 0.0, 0.0)],  # C → 1.5, 1, 1, 1
}


def _board_records(
    forfeit_round: int | None = None,
    forfeit_win: bool = False,
) -> dict[int, TeamRecord]:
    """Records carrying per-board scores. ``forfeit_round`` marks that
    round as a forfeit for team 1 — a loss, or a win when
    ``forfeit_win`` — so the /P flag and Art. 15.2 can be tested.

    Every team always faces the next one round after round, which keeps
    the expected tie-break values easy to state.
    """
    records: dict[int, TeamRecord] = {}
    for team_id, rounds in _BOARD_SCORES.items():
        matches = []
        for round_index, boards in enumerate(rounds, start=1):
            forfeited = team_id == 1 and round_index == forfeit_round
            if not forfeited:
                match_type = TeamMatchType.PLAYED
                own_mp = 1.0
            elif forfeit_win:
                match_type = TeamMatchType.FORFEIT_WIN
                own_mp = 2.0
            else:
                match_type = TeamMatchType.FORFEIT_LOSS
                own_mp = 0.0
            matches.append(
                TeamMatchRecord(
                    round_=round_index,
                    opponent_id=(team_id % 3) + 1,
                    own_mp=own_mp,
                    own_gp=sum(boards),
                    match_type=match_type,
                    board_scores=boards,
                )
            )
        records[team_id] = TeamRecord(
            team_id=team_id,
            name=f'Team {team_id}',
            total_mp=sum(m.own_mp for m in matches),
            total_gp=sum(m.own_gp for m in matches),
            matches=matches,
        )
    return records


def _board_context(rounds: int = 2, predetermined: bool = False) -> TeamTieBreakContext:
    return TeamTieBreakContext(
        primary_score=ScoreType.MATCH_POINTS,
        secondary_score=ScoreType.GAME_POINTS,
        rounds=rounds,
        win_mp=2.0,
        draw_mp=1.0,
        loss_mp=0.0,
        team_player_count=4,
        draw_gp=2.0,
        predetermined_pairings=predetermined,
    )


_BOARD_CONTEXT = _board_context()


@pytest.mark.unit
class TecBoardTieBreakTestCase(TestCase):
    """TEC-2023 Exercises 46-48: BC, TBR and BBE applied to the round-3
    match between teams #11 (Koalas) and #14 (Narwhals), which the
    exercises resolve from the published lineup

        board 1  1-0    board 2  ½-½    board 3  ½-½    board 4  0-1

    Those exercises weigh only the head-to-head match, matching the
    2023 wording of Art. 12; the 2024 and 2026 editions weigh "all
    games played by the team in the tournament". The two readings
    coincide for a single match, which is what this fixture is.
    """

    KOALAS = (1.0, 0.5, 0.5, 0.0)
    NARWHALS = (0.0, 0.5, 0.5, 1.0)

    records: ClassVar[dict[int, TeamRecord]]
    context: ClassVar[TeamTieBreakContext]

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = {}
        for team_id, boards in ((11, cls.KOALAS), (14, cls.NARWHALS)):
            match = TeamMatchRecord(
                round_=1,
                opponent_id=14 if team_id == 11 else 11,
                own_mp=1.0,
                own_gp=sum(boards),
                match_type=TeamMatchType.PLAYED,
                board_scores=boards,
            )
            cls.records[team_id] = TeamRecord(
                team_id=team_id,
                name='Koalas' if team_id == 11 else 'Narwhals',
                total_mp=1.0,
                total_gp=sum(boards),
                matches=[match],
            )
        cls.context = _board_context(rounds=1)

    def _value(self, tie_break, team_id: int) -> float:
        return tie_break.compute_team_value(
            self.records[team_id], self.records, self.context, after_round=1
        )

    def test_ex46_board_count(self):
        # BC (#11) = 1×1 + ½×2 + ½×3 + 0×4 = 3.5
        # BC (#14) = 0×1 + ½×2 + ½×3 + 1×4 = 6.5
        # "the value for team #14 is higher, determining the precedence
        # of team #11" — we negate so that higher always ranks first.
        tb = BoardCountTieBreak()
        self.assertEqual(self._value(tb, 11), -3.5)
        self.assertEqual(self._value(tb, 14), -6.5)
        self.assertGreater(self._value(tb, 11), self._value(tb, 14))

    def test_ex47_top_board_results(self):
        # "On the first board, team #11 won, thus prevailing over the
        # opponent" — decided without needing the lower boards.
        tb = TopBoardResultsTieBreak()
        self.assertGreater(self._value(tb, 11), self._value(tb, 14))
        totals_11 = tb._board_totals(self.records[11], 4, 1, self.context)
        totals_14 = tb._board_totals(self.records[14], 4, 1, self.context)
        self.assertEqual((totals_11[0], totals_14[0]), (1.0, 0.0))

    def test_ex48_bottom_board_elimination(self):
        # BBE (#11) = 1 + ½ + ½ = 2 ; BBE (#14) = 0 + ½ + ½ = 1.
        tb = BottomBoardEliminationTieBreak()
        self.assertGreater(self._value(tb, 11), self._value(tb, 14))
        self.assertEqual(
            sum(tb._board_totals(self.records[11], 4, 1, self.context)[:3]), 2.0
        )
        self.assertEqual(
            sum(tb._board_totals(self.records[14], 4, 1, self.context)[:3]), 1.0
        )


@pytest.mark.unit
class BoardTieBreakTestCase(TestCase):
    """BC / TBR / BBE over more than one round, where the three
    tie-breaks are made to disagree with each other."""

    records: ClassVar[dict[int, TeamRecord]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = _board_records()

    def _value(self, tie_break, team_id: int, records=None) -> float:
        return tie_break.compute_team_value(
            (records or self.records)[team_id],
            records or self.records,
            _BOARD_CONTEXT,
            after_round=2,
        )

    def test_board_count_sums_board_number_times_points(self):
        tb = BoardCountTieBreak()
        # A: 1×1.5 + 2×1 + 3×1 + 4×0.5 = 8.5 ; B: 1×1.5 + 2×1 + 3×0.5 +
        # 4×1.5 = 11 ; C: 1×1.5 + 2×1 + 3×1 + 4×1 = 10.5. Negated,
        # because Art. 12.1 ranks the *lower* sum higher.
        self.assertEqual(self._value(tb, 1), -8.5)
        self.assertEqual(self._value(tb, 2), -11.0)
        self.assertEqual(self._value(tb, 3), -10.5)

    def test_board_count_ranks_the_lower_sum_first(self):
        tb = BoardCountTieBreak()
        values = {team_id: self._value(tb, team_id) for team_id in (1, 2, 3)}
        self.assertEqual(max(values, key=lambda k: values[k]), 1)
        self.assertLess(values[2], values[3])

    def test_top_board_results_compares_boards_from_the_top(self):
        tb = TopBoardResultsTieBreak()
        # A and B are level on boards 1 (1.5) and 2 (1.0); board 3
        # separates them, 1.0 against 0.5.
        self.assertGreater(self._value(tb, 1), self._value(tb, 2))
        # C matches A down to board 3 and is ahead on board 4.
        self.assertGreater(self._value(tb, 3), self._value(tb, 1))

    def test_top_board_results_is_not_the_plain_total(self):
        tb = TopBoardResultsTieBreak()
        # B has the higher game-point total (4.5 against A's 4) yet
        # ranks below: the top boards decide, not the sum.
        self.assertGreater(self.records[2].total_gp, self.records[1].total_gp)
        self.assertGreater(self._value(tb, 1), self._value(tb, 2))

    def test_bottom_board_elimination_drops_the_last_board_first(self):
        tb = BottomBoardEliminationTieBreak()
        # Excluding board 4: A has 3.5, B has 3.0, C has 3.5. A and C
        # are then separated by the next exclusion (boards 1-2: both
        # 2.5) and finally board 1 alone (both 1.5) — so they stay tied.
        self.assertGreater(self._value(tb, 1), self._value(tb, 2))
        self.assertEqual(self._value(tb, 1), self._value(tb, 3))

    def test_forfeited_match_counts_only_when_asked(self):
        with_forfeit = _board_records(forfeit_round=2)
        tb = TopBoardResultsTieBreak()
        # Round 2 no longer counts for team 1: board 1 drops to 1.0.
        self.assertLess(self._value(tb, 1, with_forfeit), self._value(tb, 1))
        played = TopBoardResultsTieBreak([PlayedModifierTieBreakOption(True)])
        self.assertEqual(
            played.compute_team_value(
                with_forfeit[1], with_forfeit, _BOARD_CONTEXT, after_round=2
            ),
            self._value(tb, 1),
        )

    def test_forfeited_match_always_counts_with_predetermined_pairings(self):
        # Art. 15.2 — and "individual forfeits are considered equivalent
        # to actually played matches" (TEC-2023 §12).
        with_forfeit = _board_records(forfeit_round=2)
        tb = TopBoardResultsTieBreak()
        self.assertEqual(
            tb.compute_team_value(
                with_forfeit[1],
                with_forfeit,
                _board_context(predetermined=True),
                after_round=2,
            ),
            self._value(tb, 1),
        )

    def test_after_round_bounds_the_boards_counted(self):
        tb = BoardCountTieBreak()
        first_round_only = tb.compute_team_value(
            self.records[1], self.records, _BOARD_CONTEXT, after_round=1
        )
        # Round 1 alone: 1×1 + 2×0 + 3×1 + 4×0.5 = 6.
        self.assertEqual(first_round_only, -6.0)
        self.assertNotEqual(first_round_only, self._value(tb, 1))


# ---------------------------------------------------------------------------
# Art. 15.2: forfeits in tournaments with pre-determined pairings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class PredeterminedPairingsTestCase(TestCase):
    """With pre-determined pairings (round-robin, Molter), a forfeit is
    a regular match, so opponent-based tie-breaks count the opponent's
    real total instead of the Art. 16 dummy."""

    records: ClassVar[dict[int, TeamRecord]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = _board_records(forfeit_round=2)

    def _buchholz(self, predetermined: bool) -> float:
        return StandardBuchholzTieBreak(
            [TeamScoreTieBreakOption(TeamScoreTieBreakOption.VALUE_MP)]
        ).compute_team_value(
            self.records[1],
            self.records,
            _board_context(predetermined=predetermined),
            after_round=2,
        )

    def test_forfeit_uses_the_real_opponent_when_pairings_are_predetermined(self):
        # Team 1 plays team 2 in both rounds and forfeited round 2.
        # Art. 15.2 counts that match as regular, so Buchholz is twice
        # team 2's real total; Art. 16 substitutes a dummy built from
        # team 1's own score for the forfeited round.
        opponent_total = self.records[2].total_mp
        own_total = self.records[1].total_mp
        self.assertEqual(self._buchholz(predetermined=True), 2 * opponent_total)
        self.assertEqual(
            self._buchholz(predetermined=False), opponent_total + own_total
        )
        self.assertNotEqual(own_total, opponent_total)

    def test_default_context_keeps_the_swiss_treatment(self):
        self.assertFalse(_board_context().predetermined_pairings)

    def test_esb_also_counts_the_forfeited_match(self):
        # Art. 16.4.1 caps a forfeit's dummy at the scheduled opponent's
        # adjusted score, so the Art. 16 and Art. 15.2 treatments only
        # part company when the forfeiting team's own score is the lower
        # of the two. Team 1 loses twice, then wins round 3 by forfeit
        # against a team that has won everything else.
        def _record(team_id: int, matches: list[TeamMatchRecord]) -> TeamRecord:
            return TeamRecord(
                team_id=team_id,
                name=f'Team {team_id}',
                total_mp=sum(m.own_mp for m in matches),
                total_gp=sum(m.own_gp for m in matches),
                matches=matches,
            )

        records = {
            1: _record(
                1,
                [
                    TeamMatchRecord(1, 3, 0.0, 1.0, TeamMatchType.PLAYED),
                    TeamMatchRecord(2, 3, 0.0, 1.0, TeamMatchType.PLAYED),
                    TeamMatchRecord(3, 2, 2.0, 4.0, TeamMatchType.FORFEIT_WIN),
                ],
            ),
            2: _record(
                2,
                [
                    TeamMatchRecord(1, 3, 2.0, 3.0, TeamMatchType.PLAYED),
                    TeamMatchRecord(2, 3, 2.0, 3.0, TeamMatchType.PLAYED),
                    TeamMatchRecord(3, 1, 0.0, 0.0, TeamMatchType.FORFEIT_LOSS),
                ],
            ),
            3: _record(
                3,
                [
                    TeamMatchRecord(1, 1, 2.0, 3.0, TeamMatchType.PLAYED),
                    TeamMatchRecord(2, 1, 2.0, 3.0, TeamMatchType.PLAYED),
                ],
            ),
        }
        context = _board_context(rounds=3)
        predetermined = _board_context(rounds=3, predetermined=True)
        esb = ExtendedSonnebornBergerTeamTieBreak([])
        swiss = esb.compute_team_value(records[1], records, context, after_round=3)
        round_robin = esb.compute_team_value(
            records[1], records, predetermined, after_round=3
        )
        # Own total 2 MP against the opponent's 4, so the dummy is 2
        # while the real opponent counts 4 — a difference of 2 × the
        # 2 MP team 1 scored in that round.
        self.assertEqual(round_robin - swiss, 4.0)

    def test_ede_counts_forfeits_with_predetermined_pairings(self):
        # Art. 6.1.1 excludes only forfeits "not covered by Article
        # 15.2", so a round-robin forfeit belongs in the EDE
        # sub-crosstable even without the /P flag.
        #
        # Two teams meeting twice: team 1 wins the first match, then
        # forfeits the second. Ignoring the forfeit leaves team 1 ahead
        # on the head-to-head; counting it levels the match points and
        # hands team 2 the game-point fallback.
        def _record(team_id: int, rounds: list[TeamMatchRecord]) -> TeamRecord:
            return TeamRecord(
                team_id=team_id,
                name=f'Team {team_id}',
                total_mp=sum(m.own_mp for m in rounds),
                total_gp=sum(m.own_gp for m in rounds),
                matches=rounds,
            )

        records = {
            1: _record(
                1,
                [
                    TeamMatchRecord(1, 2, 2.0, 2.5, TeamMatchType.PLAYED),
                    TeamMatchRecord(2, 2, 0.0, 0.0, TeamMatchType.FORFEIT_LOSS),
                ],
            ),
            2: _record(
                2,
                [
                    TeamMatchRecord(1, 1, 0.0, 1.5, TeamMatchType.PLAYED),
                    TeamMatchRecord(2, 1, 2.0, 4.0, TeamMatchType.FORFEIT_WIN),
                ],
            ),
        }
        ede = ExtendedDirectEncounterTieBreak([])
        group = [records[1], records[2]]
        swiss = ede.compute_all_team_values(
            [group], records, _board_context(), after_round=2
        )
        round_robin = ede.compute_all_team_values(
            [group], records, _board_context(predetermined=True), after_round=2
        )
        self.assertGreater(swiss[1], swiss[2])
        self.assertGreater(round_robin[2], round_robin[1])


@pytest.mark.unit
class EDEKnockoutVariantTestCase(TestCase):
    """TEC-2023 Exercises 46-48 as the exercises actually frame them:
    a single criterion, "EDE system with board count [13.3.2]", whose
    knock-out part reads the two tied teams' own encounter.

    Teams #11 and #14 drew their round-3 match 2-2 with the lineup

        board 1  1-0    board 2  ½-½    board 3  ½-½    board 4  0-1

    so 13.3.1 leaves them tied on both scores and 13.3.2 decides. Each
    team also played an unrelated round against a third team, which the
    knock-out tie-break must ignore — that is what distinguishes this
    from listing BC / TBR / BBE as tie-breaks of their own.
    """

    ENCOUNTER = {11: (1.0, 0.5, 0.5, 0.0), 14: (0.0, 0.5, 0.5, 1.0)}
    # Elsewhere #11 scores on the bottom board and #14 on the top one,
    # which is the expensive way round for board count: over the whole
    # tournament #11 reaches 7.5 against #14's 7.0 and so ranks second,
    # the opposite of the encounter-only verdict.
    ELSEWHERE = {11: (0.0, 0.0, 0.0, 1.0), 14: (0.5, 0.0, 0.0, 0.0)}

    records: ClassVar[dict[int, TeamRecord]]
    context: ClassVar[TeamTieBreakContext]

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = {}
        for team_id in (11, 14):
            encounter = cls.ENCOUNTER[team_id]
            elsewhere = cls.ELSEWHERE[team_id]
            matches = [
                TeamMatchRecord(
                    round_=1,
                    opponent_id=14 if team_id == 11 else 11,
                    own_mp=1.0,
                    own_gp=sum(encounter),
                    match_type=TeamMatchType.PLAYED,
                    board_scores=encounter,
                ),
                TeamMatchRecord(
                    round_=2,
                    opponent_id=99,
                    own_mp=1.0,
                    own_gp=sum(elsewhere),
                    match_type=TeamMatchType.PLAYED,
                    board_scores=elsewhere,
                ),
            ]
            cls.records[team_id] = TeamRecord(
                team_id=team_id,
                name='Koalas' if team_id == 11 else 'Narwhals',
                total_mp=2.0,
                total_gp=sum(encounter) + sum(elsewhere),
                matches=matches,
            )
        cls.context = _board_context(rounds=2)

    def _ranks(self, variant: str) -> dict[int, float]:
        ede = ExtendedDirectEncounterTieBreak(
            [EDEKnockoutTieBreakOption(variant)] if variant else []
        )
        group = [self.records[11], self.records[14]]
        return ede.compute_all_team_values(
            [group], self.records, self.context, after_round=2
        )

    def test_without_a_variant_the_teams_stay_tied(self):
        values = self._ranks('')
        self.assertEqual(values[11], values[14])

    def test_ex46_edebt_board_count_puts_koalas_first(self):
        # BC over the encounter: #11 = 3.5, #14 = 6.5, lower first.
        values = self._ranks(EDEKnockoutVariant.EDEBT.value)
        self.assertGreater(values[11], values[14])

    def test_ex47_edet_top_board_puts_koalas_first(self):
        values = self._ranks(EDEKnockoutVariant.EDET.value)
        self.assertGreater(values[11], values[14])

    def test_ex48_edeb_bottom_board_elimination_puts_koalas_first(self):
        # BBE over the encounter: #11 = 2, #14 = 1.
        values = self._ranks(EDEKnockoutVariant.EDEB.value)
        self.assertGreater(values[11], values[14])

    def test_edebb_also_puts_koalas_first(self):
        values = self._ranks(EDEKnockoutVariant.EDEBB.value)
        self.assertGreater(values[11], values[14])

    def test_the_knockout_part_ignores_the_rest_of_the_tournament(self):
        # Standalone, board count weighs every round and #14 comes out
        # ahead; inside EDE it weighs the encounter only and #11 does.
        standalone = BoardCountTieBreak()
        self.assertGreater(
            standalone.compute_team_value(
                self.records[14], self.records, self.context, after_round=2
            ),
            standalone.compute_team_value(
                self.records[11], self.records, self.context, after_round=2
            ),
        )
        values = self._ranks(EDEKnockoutVariant.EDEBT.value)
        self.assertGreater(values[11], values[14])

    def test_the_acronym_follows_the_variant(self):
        self.assertEqual(ExtendedDirectEncounterTieBreak([]).base_acronym, 'EDE')
        for variant in EDEKnockoutVariant:
            tie_break = ExtendedDirectEncounterTieBreak(
                [EDEKnockoutTieBreakOption(variant.value)]
            )
            self.assertEqual(tie_break.base_acronym, variant.acronym)


@pytest.mark.unit
class DummyOpponentCapTestCase(TestCase):
    """FIDE Art. 16.4: the dummy opponent takes the team's own score,
    capped — at the scheduled opponent's adjusted score for a forfeit
    (16.4.1), at draw points × rounds for a bye (16.4.2). The two are
    alternatives, and the 2024 edition had neither."""

    @staticmethod
    def _record(team_id: int, matches: list[TeamMatchRecord]) -> TeamRecord:
        return TeamRecord(
            team_id=team_id,
            name=f'Team {team_id}',
            total_mp=sum(m.own_mp for m in matches),
            total_gp=sum(m.own_gp for m in matches),
            matches=matches,
        )

    def test_forfeit_caps_at_the_opponent_score_not_at_the_draw_total(self):
        # Own 6 MP over 4 rounds, forfeit against an opponent on 5 MP.
        # 16.4.1 gives 5; capping at draw × rounds as well would give 4.
        own = self._record(
            1,
            [
                TeamMatchRecord(1, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(2, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(3, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(4, 2, 0.0, 0.0, TeamMatchType.FORFEIT_LOSS),
            ],
        )
        opponent = self._record(
            2,
            [
                TeamMatchRecord(1, 1, 1.0, 2.0, TeamMatchType.PLAYED),
                TeamMatchRecord(2, 1, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(3, 1, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(4, 1, 0.0, 0.0, TeamMatchType.FORFEIT_WIN),
            ],
        )
        self.assertEqual(own.total_mp, 6.0)
        self.assertEqual(opponent.total_mp, 5.0)
        value = dummy_opponent_score(
            own,
            ScoreType.MATCH_POINTS,
            after_round=4,
            rounds=4,
            draw_value=1.0,
            opponent_adjusted=opponent.total_mp,
        )
        self.assertEqual(value, 5.0)

    def test_bye_caps_at_draw_points_times_rounds(self):
        own = self._record(
            1,
            [
                TeamMatchRecord(1, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(2, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(3, None, 2.0, 2.0, TeamMatchType.PAB),
            ],
        )
        value = dummy_opponent_score(
            own,
            ScoreType.MATCH_POINTS,
            after_round=3,
            rounds=3,
            draw_value=1.0,
        )
        # Own 6 MP, capped at 3 rounds × 1 draw point.
        self.assertEqual(value, 3.0)

    def test_game_points_are_capped_too(self):
        # The closing note of Art. 16 makes "points" mean match points
        # and game points alike, so the GP dummy caps at draw_gp × rounds.
        own = self._record(
            1,
            [
                TeamMatchRecord(1, 2, 2.0, 4.0, TeamMatchType.PLAYED),
                TeamMatchRecord(2, None, 2.0, 2.0, TeamMatchType.PAB),
            ],
        )
        value = dummy_opponent_score(
            own,
            ScoreType.GAME_POINTS,
            after_round=2,
            rounds=2,
            draw_value=2.0,
        )
        self.assertEqual(value, 4.0)

    def test_legacy_mode_caps_nothing(self):
        own = self._record(
            1,
            [
                TeamMatchRecord(1, 2, 2.0, 3.0, TeamMatchType.PLAYED),
                TeamMatchRecord(2, None, 2.0, 2.0, TeamMatchType.PAB),
            ],
        )
        value = dummy_opponent_score(
            own,
            ScoreType.MATCH_POINTS,
            after_round=2,
            rounds=2,
            draw_value=1.0,
            legacy=True,
        )
        self.assertEqual(value, own.total_mp)


@pytest.mark.unit
class BoardDifferentialTieBreakTestCase(TestCase):
    """FFE *Somme des différentiels par échiquier* (F01 §4.4.a): tied
    teams are compared on their board-1 differential, then board 2, and
    so on. The value is a within-group rank delta, 0 being the worst of
    the group."""

    @staticmethod
    def _context() -> TeamTieBreakContext:
        return TeamTieBreakContext(
            primary_score=ScoreType.MATCH_POINTS,
            secondary_score=ScoreType.GAME_POINTS,
            rounds=1,
            win_mp=3.0,
            draw_mp=2.0,
            loss_mp=1.0,
            team_player_count=4,
            draw_gp=0.0,
        )

    @staticmethod
    def _team(team_id: int, name: str, boards: tuple[float, ...], opponent_id: int):
        return TeamRecord(
            team_id=team_id,
            name=name,
            total_mp=2.0,
            total_gp=sum(boards),
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=opponent_id,
                    own_mp=2.0,
                    own_gp=sum(boards),
                    match_type=TeamMatchType.PLAYED,
                    board_scores=boards,
                )
            ],
        )

    def _values(self, *teams: TeamRecord) -> dict[int, float]:
        from plugins.ffe.ffe_tie_breaks import BoardDifferentialTieBreak

        all_records = {team.team_id: team for team in teams}
        return BoardDifferentialTieBreak([]).compute_all_team_values(
            [list(teams)], all_records, self._context(), after_round=1
        )

    def test_board_one_decides(self):
        # Both teams drew 2-2, but #1 won on board 1 (+1) and lost the
        # bottom board, so it takes the tie-break.
        first = self._team(1, 'A', (1.0, 0.5, 0.5, 0.0), opponent_id=2)
        second = self._team(2, 'B', (0.0, 0.5, 0.5, 1.0), opponent_id=1)
        values = self._values(first, second)
        assert values[1] > values[2]
        assert min(values.values()) == 0.0

    def test_falls_through_to_the_next_board(self):
        # Board 1 is level (both drew it), board 2 separates them.
        first = self._team(1, 'A', (0.5, 1.0, 0.5, 0.0), opponent_id=2)
        second = self._team(2, 'B', (0.5, 0.0, 0.5, 1.0), opponent_id=1)
        values = self._values(first, second)
        assert values[1] > values[2]

    def test_identical_boards_stay_tied(self):
        first = self._team(1, 'A', (0.5, 0.5, 0.5, 0.5), opponent_id=2)
        second = self._team(2, 'B', (0.5, 0.5, 0.5, 0.5), opponent_id=1)
        values = self._values(first, second)
        assert values[1] == values[2]

    def test_differential_not_own_score(self):
        from plugins.ffe.ffe_tie_breaks import BoardDifferentialTieBreak

        # #1 scores 1 on board 1 against an opponent who also scored 1
        # there (a scoring scheme where both can); #2 scores 0.5 against
        # 0. The differentials are 0 and +0.5, so #2 wins despite the
        # smaller own score — the criterion is the differential.
        first = self._team(1, 'A', (1.0, 0.0, 0.0, 0.0), opponent_id=2)
        second = self._team(2, 'B', (1.0, 0.0, 0.0, 0.0), opponent_id=1)
        third = self._team(3, 'C', (0.5, 0.0, 0.0, 0.0), opponent_id=4)
        fourth = self._team(4, 'D', (0.0, 0.0, 0.0, 0.0), opponent_id=3)
        # #1's board-1 differential is 1 - 1 = 0, #3's is 0.5 - 0 = 0.5.
        all_records = {team.team_id: team for team in (first, second, third, fourth)}
        values = BoardDifferentialTieBreak([]).compute_all_team_values(
            [[first, third]], all_records, self._context(), after_round=1
        )
        assert values[3] > values[1]

    def test_rounds_after_the_cutoff_are_ignored(self):
        from plugins.ffe.ffe_tie_breaks import BoardDifferentialTieBreak

        def team(team_id: int, round_two_boards: tuple[float, ...]) -> TeamRecord:
            return TeamRecord(
                team_id=team_id,
                name=str(team_id),
                total_mp=4.0,
                total_gp=4.0,
                matches=[
                    TeamMatchRecord(
                        round_=1,
                        opponent_id=3 - team_id,
                        own_mp=2.0,
                        own_gp=2.0,
                        match_type=TeamMatchType.PLAYED,
                        board_scores=(0.5, 0.5, 0.5, 0.5),
                    ),
                    TeamMatchRecord(
                        round_=2,
                        opponent_id=3 - team_id,
                        own_mp=2.0,
                        own_gp=sum(round_two_boards),
                        match_type=TeamMatchType.PLAYED,
                        board_scores=round_two_boards,
                    ),
                ],
            )

        first = team(1, (1.0, 0.5, 0.5, 0.0))
        second = team(2, (0.0, 0.5, 0.5, 1.0))
        all_records = {1: first, 2: second}
        tie_break = BoardDifferentialTieBreak([])
        # Round 1 alone leaves them level; round 2 separates them.
        after_one = tie_break.compute_all_team_values(
            [[first, second]], all_records, self._context(), after_round=1
        )
        after_two = tie_break.compute_all_team_values(
            [[first, second]], all_records, self._context(), after_round=2
        )
        assert after_one[1] == after_one[2]
        assert after_two[1] > after_two[2]

    def test_bye_contributes_nothing(self):
        from plugins.ffe.ffe_tie_breaks import BoardDifferentialTieBreak

        # A bye awards match-level points with no board scores, so it
        # must not shift any board's differential.
        played = TeamMatchRecord(
            round_=1,
            opponent_id=2,
            own_mp=2.0,
            own_gp=2.0,
            match_type=TeamMatchType.PLAYED,
            board_scores=(0.5, 0.5, 0.5, 0.5),
        )
        bye = TeamMatchRecord(
            round_=2,
            opponent_id=None,
            own_mp=3.0,
            own_gp=2.0,
            match_type=TeamMatchType.PAB,
            board_scores=(),
        )
        first = TeamRecord(
            team_id=1, name='A', total_mp=5.0, total_gp=4.0, matches=[played, bye]
        )
        second = TeamRecord(
            team_id=2,
            name='B',
            total_mp=2.0,
            total_gp=2.0,
            matches=[
                TeamMatchRecord(
                    round_=1,
                    opponent_id=1,
                    own_mp=2.0,
                    own_gp=2.0,
                    match_type=TeamMatchType.PLAYED,
                    board_scores=(0.5, 0.5, 0.5, 0.5),
                )
            ],
        )
        values = BoardDifferentialTieBreak([]).compute_all_team_values(
            [[first, second]], {1: first, 2: second}, self._context(), after_round=2
        )
        assert values[1] == values[2]
