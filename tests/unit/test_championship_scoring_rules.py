"""Tests for the extended championship rule set, the stage coefficient, the
per-rule acronyms/metadata, and the class registry that replaced the rule-type
enum. The engine is exercised with light fakes standing in for source stages."""

import pytest

from data.championship.options import TeamScoreBasis
from data.championship.reconciliation import ReconciledParticipation, ReconciledPlayer
from data.championship.scoring import (
    AveragePointsRule,
    AverageRankRule,
    AverageTieBreakRule,
    CountPlacesRule,
    CountWinsRule,
    DirectEncounterRule,
    F1PointsRule,
    ManualRule,
    RankingPointsWithBonusRule,
    ScaledPointsRule,
    ScoringContext,
    SumTieBreakRule,
    TotalPointsRule,
    best_participations,
    build_rule,
    championship_rule_class,
    championship_rules,
    rank_competitors,
    rank_players,
)


class FakeFieldPlayer:
    """A ranked entrant of a source tournament: only the field size and the
    fact that it counts towards it matter here."""

    is_excluded_from_standings = False


class FakeTournament:
    def __init__(self, field_size=0):
        self._field_size = field_size

    @property
    def tournament_players(self):
        return [FakeFieldPlayer() for _ in range(self._field_size)]

    def ensure_tournament_player_ranks_computed(self):
        pass


class FakeSource:
    def __init__(self, event_uniq_id, tournament_id, coefficient=1.0, field_size=0):
        self.event_uniq_id = event_uniq_id
        self.tournament_id = tournament_id
        self.coefficient = coefficient
        self.tournament = FakeTournament(field_size)
        self.event = None


class FakeTournamentPlayer:
    def __init__(self, player_id, points, rank=0, last_name='X'):
        self.id = player_id
        self.points = points
        self.rank = rank
        self.pairings_by_round = {}
        self.last_name = last_name
        self.first_name = 'Y'
        self.fide_id = None
        self.date_of_birth = None


def competitor(name, stages):
    """``stages`` = list of ``(FakeSource, FakeTournamentPlayer)``."""
    return ReconciledPlayer(
        [ReconciledParticipation(source, tp) for source, tp in stages]
    )


def order(groups):
    return [
        group[0].last_name if len(group) == 1 else [p.last_name for p in group]
        for group in groups
    ]


# ---------------------------------------------------------------------------
# Rule semantics
# ---------------------------------------------------------------------------


def test_scaled_points_winner_scores_one_last_scores_zero():
    stage = FakeSource('ev', 1, field_size=10)
    top = competitor('T', [(stage, FakeTournamentPlayer(1, 0, rank=1, last_name='T'))])
    mid = competitor('M', [(stage, FakeTournamentPlayer(2, 0, rank=5, last_name='M'))])
    last = competitor(
        'L', [(stage, FakeTournamentPlayer(3, 0, rank=10, last_name='L'))]
    )
    # (10-1)/9 = 1, (10-5)/9 ≈ 0.556, (10-10)/9 = 0.
    assert order(rank_players([mid, last, top], [ScaledPointsRule()])) == [
        'T',
        'M',
        'L',
    ]


def test_f1_points_awards_table_positions():
    stage = FakeSource('ev', 1, field_size=20)
    a = competitor('A', [(stage, FakeTournamentPlayer(1, 0, rank=1, last_name='A'))])
    b = competitor('B', [(stage, FakeTournamentPlayer(2, 0, rank=2, last_name='B'))])
    c = competitor('C', [(stage, FakeTournamentPlayer(3, 0, rank=9, last_name='C'))])
    rule = F1PointsRule(table=[20.0, 15.0, 12.0])
    # rank 1 -> 20, rank 2 -> 15, rank 9 -> 0 (beyond the table).
    assert order(rank_players([c, b, a], [rule])) == ['A', 'B', 'C']


def test_ranking_points_with_bonus_matches_worked_example():
    # 200 players, top 5% (10 players) get a bonus, winner bonus 50% of ranking
    # points (100). Ranking points: winner = field size, last = 1.
    stage = FakeSource('ev', 1, field_size=200)
    players = {
        rank: competitor(
            f'R{rank}',
            [(stage, FakeTournamentPlayer(rank, 0, rank=rank, last_name=f'R{rank}'))],
        )
        for rank in (1, 2, 10, 11, 200)
    }
    group = list(players.values())
    rule = RankingPointsWithBonusRule(winner_bonus=50, bonus_share=5)
    scores = rule.scores(group, ScoringContext(group))
    assert scores[id(players[1])] == 300  # 200 RP + 100 BP
    assert scores[id(players[2])] == 289  # 199 RP +  90 BP
    assert scores[id(players[10])] == 201  # 191 RP + 10 BP
    assert scores[id(players[11])] == 190  # 190 RP +  0 BP (outside the top 5%)
    assert scores[id(players[200])] == 1  # last place, 1 RP


def test_average_rank_prefers_lower_positions():
    s1 = FakeSource('e1', 1, field_size=30)
    s2 = FakeSource('e2', 1, field_size=30)
    steady = competitor(
        'S',
        [
            (s1, FakeTournamentPlayer(1, 0, rank=3, last_name='S')),
            (s2, FakeTournamentPlayer(1, 0, rank=3, last_name='S')),
        ],
    )
    swingy = competitor(
        'W',
        [
            (s1, FakeTournamentPlayer(2, 0, rank=1, last_name='W')),
            (s2, FakeTournamentPlayer(2, 0, rank=10, last_name='W')),
        ],
    )
    # mean ranks: S = 3, W = 5.5 -> S ranked first.
    assert order(rank_players([swingy, steady], [AverageRankRule()])) == ['S', 'W']


def test_count_places_counts_a_chosen_position():
    s1, s2 = FakeSource('e1', 1, field_size=30), FakeSource('e2', 1, field_size=30)
    winner = competitor(
        'A',
        [
            (s1, FakeTournamentPlayer(1, 0, rank=1, last_name='A')),
            (s2, FakeTournamentPlayer(1, 0, rank=1, last_name='A')),
        ],
    )
    runner = competitor(
        'B',
        [
            (s1, FakeTournamentPlayer(2, 0, rank=1, last_name='B')),
            (s2, FakeTournamentPlayer(2, 0, rank=2, last_name='B')),
        ],
    )
    # First places: A = 2, B = 1.
    assert order(rank_players([runner, winner], [CountPlacesRule(place=1)])) == [
        'A',
        'B',
    ]


# ---------------------------------------------------------------------------
# Manual tie-break
# ---------------------------------------------------------------------------


def test_manual_rule_orders_tied_competitors_by_pinned_position():
    stage = FakeSource('e1', 1, field_size=10)
    a = competitor('A', [(stage, FakeTournamentPlayer(1, 5, last_name='A'))])
    b = competitor('B', [(stage, FakeTournamentPlayer(2, 5, last_name='B'))])
    c = competitor('C', [(stage, FakeTournamentPlayer(3, 5, last_name='C'))])
    rules = [TotalPointsRule(), ManualRule()]
    # Equal points and no manual positions: everyone stays tied.
    groups = rank_competitors([a, b, c], rules)
    assert len(groups) == 1 and len(groups[0]) == 3
    # A pinned position (higher = better) fully orders the tie.
    manual = {a.key: 1, b.key: 3, c.key: 2}
    groups = rank_competitors([a, b, c], rules, manual_positions=manual)
    assert [group[0].last_name for group in groups] == ['B', 'C', 'A']  # type: ignore[union-attr]


def test_manual_rule_only_separates_pinned_competitors():
    stage = FakeSource('e1', 1, field_size=10)
    a = competitor('A', [(stage, FakeTournamentPlayer(1, 5, last_name='A'))])
    b = competitor('B', [(stage, FakeTournamentPlayer(2, 5, last_name='B'))])
    c = competitor('C', [(stage, FakeTournamentPlayer(3, 5, last_name='C'))])
    # Only A is pinned above the rest; B and C remain tied with each other.
    manual = {a.key: 1}
    groups = rank_competitors(
        [a, b, c], [TotalPointsRule(), ManualRule()], manual_positions=manual
    )
    assert [len(group) for group in groups] == [1, 2]
    assert groups[0][0].last_name == 'A'  # type: ignore[union-attr]
    assert sorted(p.last_name for p in groups[1]) == ['B', 'C']  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Stage coefficient
# ---------------------------------------------------------------------------


def test_coefficient_weights_points_but_not_positions():
    plain = FakeSource('e1', 1, coefficient=1.0, field_size=10)
    doubled = FakeSource('e2', 1, coefficient=2.0, field_size=10)
    # Equal raw points, but B's single stage counts double.
    a = competitor('A', [(plain, FakeTournamentPlayer(1, 5, rank=2, last_name='A'))])
    b = competitor('B', [(doubled, FakeTournamentPlayer(2, 5, rank=2, last_name='B'))])
    assert order(rank_players([a, b], [TotalPointsRule()])) == ['B', 'A']
    # Average rank is ordinal: the coefficient must not change it (equal ranks).
    ranked = rank_players([a, b], [AverageRankRule()])
    assert len(ranked) == 1 and sorted(p.last_name for p in ranked[0]) == ['A', 'B']


def test_uses_coefficient_flags():
    weighted = {
        TotalPointsRule,
        ScaledPointsRule,
        F1PointsRule,
        AveragePointsRule,
        SumTieBreakRule,
        AverageTieBreakRule,
    }
    unweighted = {AverageRankRule, CountPlacesRule, CountWinsRule, DirectEncounterRule}
    assert all(rule.uses_coefficient for rule in weighted)  # type: ignore[attr-defined]
    assert not any(rule.uses_coefficient for rule in unweighted)  # type: ignore[attr-defined]


def test_point_rules_read_use_coefficient_option():
    assert (
        build_rule('TOTAL_POINTS', None, {'use_coefficient': False}).use_coefficient
        is False
    )
    assert build_rule('TOTAL_POINTS', None, {}).use_coefficient is True
    assert (
        build_rule('SCALED_POINTS', None, {'use_coefficient': False}).use_coefficient
        is False
    )
    assert (
        build_rule('AVERAGE_POINTS', None, {'use_coefficient': False}).use_coefficient
        is False
    )
    f1 = build_rule('F1_POINTS', None, {'points': [10], 'use_coefficient': False})
    assert f1.use_coefficient is False
    assert f1.table == [10.0]  # type: ignore[attr-defined]


def test_unweighted_rules_force_coefficient_off():
    # The flag is meaningless for ordinal/count rules, so it is forced off even
    # when a stored payload (or a caller) asks for it.
    assert AverageRankRule(use_coefficient=True).use_coefficient is False
    assert CountPlacesRule(place=1).use_coefficient is False
    assert DirectEncounterRule().use_coefficient is False
    assert (
        build_rule('COUNT_WINS', None, {'use_coefficient': True}).use_coefficient
        is False
    )


def test_total_points_coefficient_can_be_disabled():
    plain = FakeSource('e1', 1, coefficient=1.0, field_size=10)
    doubled = FakeSource('e2', 1, coefficient=2.0, field_size=10)
    a = competitor('A', [(plain, FakeTournamentPlayer(1, 5, rank=2, last_name='A'))])
    b = competitor('B', [(doubled, FakeTournamentPlayer(2, 5, rank=2, last_name='B'))])
    # On (default): B's doubled stage wins. Off: equal raw points -> tie.
    assert order(rank_players([a, b], [TotalPointsRule()])) == ['B', 'A']
    unweighted = rank_players([a, b], [TotalPointsRule(use_coefficient=False)])
    assert len(unweighted) == 1
    assert sorted(p.last_name for p in unweighted[0]) == ['A', 'B']


# ---------------------------------------------------------------------------
# Tie-break aggregation rules (sum / average of a source tie-break)
# ---------------------------------------------------------------------------


class FakeTieBreakContext:
    """Stands in for ``ScoringContext``: returns canned per-participation
    tie-break values (keyed by ``source_competitor_id``) instead of computing
    them from the source games, and records the (type, options) it was asked
    for."""

    def __init__(
        self,
        values,
        team_score_basis=TeamScoreBasis.SOURCE_PRIMARY,
    ):
        self.values = values
        self.team_score_basis = team_score_basis
        self.rules = []
        self.calls = []

    def tie_break_value(self, participation, type_id, options):
        self.calls.append((type_id, options))
        return self.values.get(participation.source_competitor_id)


def _sum_rule(use_coefficient=True, best_n=None, tie_break_type='X', options=None):
    return SumTieBreakRule(
        best_n,
        tie_break_type=tie_break_type,
        tie_break_options=options or {},
        tie_break_acronym='Bh',
        use_coefficient=use_coefficient,
    )


def test_sum_tie_break_adds_values_across_stages():
    s1, s2 = FakeSource('e1', 1), FakeSource('e2', 1)
    a = competitor(
        'A',
        [
            (s1, FakeTournamentPlayer(1, 10, last_name='A')),
            (s2, FakeTournamentPlayer(2, 10, last_name='A')),
        ],
    )
    b = competitor(
        'B',
        [
            (s1, FakeTournamentPlayer(3, 10, last_name='B')),
            (s2, FakeTournamentPlayer(4, 10, last_name='B')),
        ],
    )
    context = FakeTieBreakContext({1: 5, 2: 4, 3: 6, 4: 2})
    scores = _sum_rule().scores([a, b], context)
    assert scores[id(a)] == 9  # 5 + 4
    assert scores[id(b)] == 8  # 6 + 2


def test_average_tie_break_means_over_stages_that_have_it():
    s1, s2 = FakeSource('e1', 1), FakeSource('e2', 1)
    a = competitor(
        'A',
        [
            (s1, FakeTournamentPlayer(1, 10, last_name='A')),
            (s2, FakeTournamentPlayer(2, 10, last_name='A')),
        ],
    )
    b = competitor(
        'B',
        [
            (s1, FakeTournamentPlayer(3, 10, last_name='B')),
            (s2, FakeTournamentPlayer(4, 10, last_name='B')),
        ],
    )
    # A's second stage never computed the tie-break -> skipped, not counted 0.
    context = FakeTieBreakContext({1: 6, 2: None, 3: 4, 4: 4})
    rule = AverageTieBreakRule(
        tie_break_type='X', tie_break_options={}, tie_break_acronym='Bh'
    )
    scores = rule.scores([a, b], context)
    assert scores[id(a)] == 6.0  # mean of just the one stage that had it
    assert scores[id(b)] == 4.0  # mean(4, 4)


def test_sum_tie_break_skips_stages_without_the_value():
    s1, s2 = FakeSource('e1', 1), FakeSource('e2', 1)
    a = competitor(
        'A',
        [
            (s1, FakeTournamentPlayer(1, 10, last_name='A')),
            (s2, FakeTournamentPlayer(2, 10, last_name='A')),
        ],
    )
    context = FakeTieBreakContext({1: 5, 2: None})
    assert _sum_rule().scores([a], context)[id(a)] == 5


def test_tie_break_applies_coefficient_by_default():
    doubled = FakeSource('e1', 1, coefficient=2.0)
    a = competitor('A', [(doubled, FakeTournamentPlayer(1, 10, last_name='A'))])
    context = FakeTieBreakContext({1: 5})
    assert _sum_rule().scores([a], context)[id(a)] == 10.0  # 5 * 2


def test_tie_break_coefficient_can_be_disabled():
    doubled = FakeSource('e1', 1, coefficient=2.0)
    a = competitor('A', [(doubled, FakeTournamentPlayer(1, 10, last_name='A'))])
    context = FakeTieBreakContext({1: 5})
    assert _sum_rule(use_coefficient=False).scores([a], context)[id(a)] == 5.0


def test_tie_break_best_n_limits_the_stages_counted():
    strong = FakeSource('e1', 1)
    weak = FakeSource('e2', 1)
    a = competitor(
        'A',
        [
            (strong, FakeTournamentPlayer(1, 10, last_name='A')),
            (weak, FakeTournamentPlayer(2, 1, last_name='A')),
        ],
    )
    # best_n=1 keeps the higher-points stage (id 1) only.
    context = FakeTieBreakContext({1: 7, 2: 3})
    assert _sum_rule(best_n=1).scores([a], context)[id(a)] == 7


def test_tie_break_forwards_the_configured_type_and_options():
    a = competitor('A', [(FakeSource('e1', 1), FakeTournamentPlayer(1, 10))])
    context = FakeTieBreakContext({1: 3})
    _sum_rule(tie_break_type='BUCHHOLZ', options={'cut': 1}).scores([a], context)
    assert context.calls == [('BUCHHOLZ', {'cut': 1})]


def test_build_rule_reads_tie_break_and_coefficient_options():
    rule = build_rule(
        'SUM_TIE_BREAK',
        3,
        {
            'tie_break': {
                'type': 'BUCHHOLZ',
                'options': {'cut': 1},
                'acronym': 'Bh',
            },
            'use_coefficient': False,
        },
    )
    assert isinstance(rule, SumTieBreakRule)
    assert rule.best_n == 3
    assert rule.tie_break_type == 'BUCHHOLZ'
    assert rule.tie_break_options == {'cut': 1}
    assert rule.tie_break_acronym == 'Bh'
    assert rule.use_coefficient is False


def test_tie_break_use_coefficient_defaults_true():
    rule = build_rule(
        'AVERAGE_TIE_BREAK',
        None,
        {'tie_break': {'type': 'X', 'options': {}, 'acronym': 'Bh'}},
    )
    assert rule.use_coefficient is True


def test_tie_break_acronyms_include_selection_and_best_n():
    assert _sum_rule().acronym == 'ΣBh'
    assert _sum_rule(best_n=4).acronym == 'ΣBh/4'
    assert AverageTieBreakRule(tie_break_acronym='Bh').acronym == 'øBh'
    # No tie-break chosen yet.
    assert SumTieBreakRule().acronym == 'Σ?'


# ---------------------------------------------------------------------------
# Acronyms / metadata
# ---------------------------------------------------------------------------


def test_acronyms_include_best_n_and_place():
    assert TotalPointsRule().acronym == 'Pts'
    assert TotalPointsRule(4).acronym == 'Pts4'
    assert ScaledPointsRule(5).acronym == 'PS5'
    assert CountPlacesRule(place=1).acronym == 'Pl1'
    assert CountPlacesRule(3, place=1).acronym == 'Pl1/3'
    # Direct encounter cannot be scoped to best-N.
    assert DirectEncounterRule().supports_best_n is False
    assert DirectEncounterRule().best_n is None


def test_every_rule_has_a_description():
    for rule_class in championship_rules():
        assert rule_class.description()
        assert rule_class.label()
        assert rule_class.base_acronym()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_lists_every_rule_and_round_trips_ids():
    ids = {rule_class.static_id() for rule_class in championship_rules()}
    assert ids == {
        'TOTAL_POINTS',
        'SCALED_POINTS',
        'F1_POINTS',
        'RANKING_POINTS_BONUS',
        'AVERAGE_POINTS',
        'AVERAGE_RANK',
        'COUNT_PLACES',
        'COUNT_WINS',
        'DIRECT_ENCOUNTER',
        'SUM_TIE_BREAK',
        'AVERAGE_TIE_BREAK',
        'MANUAL',
    }
    for rule_class in championship_rules():
        assert championship_rule_class(rule_class.static_id()) is rule_class


def test_build_rule_reads_options():
    f1 = build_rule('F1_POINTS', 4, {'points': [20, 15, 12]})
    assert isinstance(f1, F1PointsRule)
    assert f1.best_n == 4
    assert f1.table == [20.0, 15.0, 12.0]

    places = build_rule('COUNT_PLACES', None, {'place': 2})
    assert isinstance(places, CountPlacesRule)
    assert places.place == 2


def test_build_rule_rejects_unknown_type():
    with pytest.raises(ValueError):
        build_rule('NOPE', None, {})


def test_stage_selection_ties_broken_by_configured_rule_chain():
    from data.championship.scoring import ScoringContext

    # Two stages tied on points: one finished 5th, the other 1st.
    stage_bad = FakeSource('bad', 1, field_size=10)
    stage_good = FakeSource('good', 1, field_size=10)
    player = competitor(
        'P',
        [
            (stage_bad, FakeTournamentPlayer(1, 4, rank=5, last_name='P')),
            (stage_good, FakeTournamentPlayer(2, 4, rank=1, last_name='P')),
        ],
    )

    def kept_rank(rules):
        context = ScoringContext([player], rules=rules)
        best = best_participations(player, 1, TeamScoreBasis.SOURCE_PRIMARY, context)
        return best[0].rank

    # With only a points rule, the points tie is unbroken -> stable order keeps
    # the first-listed stage (5th).
    assert kept_rank([TotalPointsRule()]) == 5
    # Adding finishing position as the next rule breaks the tie by position, so
    # the 1st-place stage is now kept. The chain — not a fixed order — decides.
    assert kept_rank([TotalPointsRule(), AverageRankRule()]) == 1
