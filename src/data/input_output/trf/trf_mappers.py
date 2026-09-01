from data.pairings import PairingVariation
from data.pairings.variations import (
    BergerRoundRobinVariation,
    BergerTeamRoundRobinVariation,
    DoubleBergerRoundRobinVariation,
    DoubleBergerTeamRoundRobinVariation,
    StandardSwissVariation,
    StandardTeamSwissVariation,
)
from data.pairings.acceleration import BakuSwissVariation
from utils import CoreMapper
from utils.enum import (
    BoardColor,
    PlayerGender,
    PlayerTitle,
    Result,
    ScoreType,
    TeamColourType,
)


class TrfPlayerGender(CoreMapper[str, PlayerGender]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, PlayerGender]:
        return {
            '': PlayerGender.NONE,
            ' ': PlayerGender.NONE,
            'm': PlayerGender.MAN,
            'w': PlayerGender.WOMAN,
        }


class TrfPlayerTitle(CoreMapper[str, PlayerTitle]):
    """001 positions 11-13. Both TRF16 and TRF26 spell the titles
    ``GM``, ``IM``, ``WGM`` …, and those are what we write, being first
    here. The lowercase forms below are a vendor convention (older
    Swiss-Manager exports and the like, which spell the women's titles
    both ``gf`` and ``wg``); they are accepted so those files load."""

    @staticmethod
    def _core_object_by_outer_value() -> dict[str, PlayerTitle]:
        return {
            '': PlayerTitle.NONE,
            'GM': PlayerTitle.GRANDMASTER,
            'IM': PlayerTitle.INTERNATIONAL_MASTER,
            'FM': PlayerTitle.FIDE_MASTER,
            'CM': PlayerTitle.CANDIDATE_MASTER,
            'WGM': PlayerTitle.WOMAN_GRANDMASTER,
            'WIM': PlayerTitle.WOMAN_INTERNATIONAL_MASTER,
            'WFM': PlayerTitle.WOMAN_FIDE_MASTER,
            'WCM': PlayerTitle.WOMAN_CANDIDATE_MASTER,
            'g': PlayerTitle.GRANDMASTER,
            'm': PlayerTitle.INTERNATIONAL_MASTER,
            'f': PlayerTitle.FIDE_MASTER,
            'c': PlayerTitle.CANDIDATE_MASTER,
            'gf': PlayerTitle.WOMAN_GRANDMASTER,
            'mf': PlayerTitle.WOMAN_INTERNATIONAL_MASTER,
            'ff': PlayerTitle.WOMAN_FIDE_MASTER,
            'cf': PlayerTitle.WOMAN_CANDIDATE_MASTER,
            'wg': PlayerTitle.WOMAN_GRANDMASTER,
            'wm': PlayerTitle.WOMAN_INTERNATIONAL_MASTER,
            'wf': PlayerTitle.WOMAN_FIDE_MASTER,
            'wc': PlayerTitle.WOMAN_CANDIDATE_MASTER,
        }


class TrfResult(CoreMapper[str, Result]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, Result]:
        return {
            '0': Result.LOSS,
            '=': Result.DRAW,
            '1': Result.WIN,
            'L': Result.UNRATED_LOSS,
            'D': Result.UNRATED_DRAW,
            'W': Result.UNRATED_WIN,
            '-': Result.FORFEIT_LOSS,
            '+': Result.FORFEIT_WIN,
            'H': Result.HALF_POINT_BYE,
            'F': Result.FULL_POINT_BYE,
            'U': Result.PAIRING_ALLOCATED_BYE,
            'Z': Result.ZERO_POINT_BYE,
        }

    @classmethod
    def get_outer_value(cls, core_object: Result) -> str:
        if trf_result := super().get_outer_value(core_object):
            return trf_result
        trf_result_by_result = {
            Result.DOUBLE_FORFEIT: '-',
            Result.PENALTY_LL: '0',
            Result.PENALTY_LD: '0',
            Result.PENALTY_DL: '=',
            Result.UNRATED_PENALTY_LL: 'L',
            Result.UNRATED_PENALTY_LD: 'L',
            Result.UNRATED_PENALTY_DL: 'D',
            Result.REST_GAME: ' ',
            Result.NO_RESULT: ' ',
        }
        if core_object in trf_result_by_result:
            return trf_result_by_result[core_object]
        raise ValueError(f'Unhandled result ({core_object.value})')

    @classmethod
    def get_core_object(
        cls,
        outer_value: str,
        has_opponent: bool = False,
        is_round_robin: bool = False,
    ) -> Result:
        if outer_value == ' ':
            if has_opponent:
                return Result.NO_RESULT
            if is_round_robin:
                return Result.REST_GAME
            return Result.ZERO_POINT_BYE
        return super().get_core_object(outer_value)


class TrfPointSystemResult(CoreMapper[str, Result]):
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, Result]:
        return {
            'W': Result.WIN,
            'D': Result.DRAW,
            'L': Result.LOSS,
            'A': Result.ZERO_POINT_BYE,
            'P': Result.PAIRING_ALLOCATED_BYE,
        }


class TrfEncodedType:
    #: Codes the tournament-type table defines as meaning another code.
    ALIASES: dict[str, str] = {
        'FIDE_TEAM': 'FIDE_TEAM_TYPEA_MP_GP',
        'FIDE_TEAM_BAKU': 'FIDE_TEAM_TYPEA_MP_GP_BAKU',
    }

    @classmethod
    def canonical(cls, encoded_type: str) -> str:
        return cls.ALIASES.get(encoded_type, encoded_type)

    @classmethod
    def get_pairing_variation(cls, encoded_type: str) -> PairingVariation:
        variation = cls.get_supported_pairing_variation(encoded_type)
        if variation:
            return variation
        variation = cls.get_supported_pairing_variation(
            cls.get_not_supported_default_type(encoded_type)
        )
        assert variation is not None
        return variation

    @classmethod
    def get_supported_pairing_variation(
        cls, encoded_type: str
    ) -> PairingVariation | None:
        encoded_type = cls.canonical(encoded_type)
        match encoded_type:
            # ``FIDE_DUTCH`` follows the date: the 2017 rules before
            # February 1st 2026, the 2026 rules after. The 2017 rules are
            # not implemented here, so ``FIDE_DUTCH_2017`` is left to the
            # fallback, which says so rather than pairing it silently by
            # the wrong rules.
            #
            # ``_2025`` is not a code the type table defines. It is the
            # name bbpPairings gives the same ruleset, and versions of
            # this program up to 5.0 wrote it, so files carrying it load.
            case 'FIDE_DUTCH_2026' | 'FIDE_DUTCH' | 'FIDE_DUTCH_2025':
                return StandardSwissVariation()
            case 'FIDE_DUTCH_2026_BAKU' | 'FIDE_DUTCH_BAKU' | 'FIDE_DUTCH_2025_BAKU':
                return BakuSwissVariation()
            case 'FIDE_ROUNDROBIN' | 'BERGER_ROUNDROBIN' | 'BERGER_ROUNDROBIN_G1':
                return BergerRoundRobinVariation()
            case 'FIDE_DOUBLEROUNDROBIN':
                return DoubleBergerRoundRobinVariation()
            case (
                'FIDE_TEAM_ROUNDROBIN'
                | 'BERGER_TEAM_ROUNDROBIN'
                | 'BERGER_TEAM_ROUNDROBIN_G1'
                | 'CUSTOM_TEAM_ROUNDROBIN'
                | 'OTHER_TEAM_ROUNDROBIN'
            ):
                return BergerTeamRoundRobinVariation()
            case (
                'FIDE_TEAM_DOUBLEROUNDROBIN'
                | 'BERGER_TEAM_DOUBLEROUNDROBIN'
                | 'OTHER_TEAM_DOUBLEROUNDROBIN'
            ):
                return DoubleBergerTeamRoundRobinVariation()
            case _ if encoded_type.endswith('_BAKU'):
                # Baku acceleration is only implemented for individual
                # Swiss. Falling through to the plain team system would
                # drop the acceleration without saying so.
                return None
            case _ if encoded_type.startswith(
                ('FIDE_TEAM_TYPEA_', 'FIDE_TEAM_TYPEB_', 'FIDE_TEAM_')
            ):
                # FIDE_TEAM_[TYPE<A|B>_]<primary>[_<secondary>] team-Swiss
                # code. Score config + colour-preference rule are
                # recovered separately via ``get_team_score_config`` and
                # ``get_team_colour_type``; the variation itself is the
                # same Standard Team Swiss in every case (the bare
                # ``FIDE_TEAM_…`` prefix is the no-preference variant).
                return StandardTeamSwissVariation()
            case _:
                return None

    @staticmethod
    def get_team_score_config(
        encoded_type: str,
    ) -> tuple[ScoreType, ScoreType | None] | None:
        """Decode a ``FIDE_TEAM_TYPE<A|B>_<primary>[_<secondary>]``
        team-Swiss code into ``(primary_score, secondary_score)``.
        Returns ``None`` for codes that don't carry score config
        (non-team or unparseable). The secondary is ``None`` for the
        MP-only / GP-only codes: they are how the TRF spells "the
        secondary score is not used for colour allocation" (FIDE Swiss
        Team Pairing System §1.2.1)."""
        suffix = TrfEncodedType._team_code_suffix(encoded_type)
        if suffix is None:
            return None
        parts = suffix.split('_')
        score_by_code = {'MP': ScoreType.MATCH_POINTS, 'GP': ScoreType.GAME_POINTS}
        if not parts or parts[0] not in score_by_code:
            return None
        primary = score_by_code[parts[0]]
        if len(parts) == 1:
            return primary, None
        if parts[1] not in score_by_code:
            return None
        secondary = score_by_code[parts[1]]
        # A code naming the same score twice says nothing more than the
        # primary-only form does.
        return primary, secondary if secondary != primary else None

    @staticmethod
    def get_team_colour_type(encoded_type: str) -> TeamColourType | None:
        """Decode the colour-preference rule (A / B / NONE) embedded in a
        team-Swiss encoded type. Returns ``None`` if the code isn't a
        team-Swiss code at all. The bare ``FIDE_TEAM_<P>[_<S>]`` prefix
        (no ``TYPE<A|B>_`` infix) corresponds to ``TeamColourType.NONE``
        — the FIDE convention for events that opt out of colour
        preferences."""
        encoded_type = TrfEncodedType.canonical(encoded_type)
        if encoded_type.startswith('FIDE_TEAM_TYPEA_'):
            return TeamColourType.A
        if encoded_type.startswith('FIDE_TEAM_TYPEB_'):
            return TeamColourType.B
        if encoded_type.startswith('FIDE_TEAM_'):
            return TeamColourType.NONE
        return None

    @staticmethod
    def _team_code_suffix(encoded_type: str) -> str | None:
        encoded_type = TrfEncodedType.canonical(encoded_type)
        for prefix in ('FIDE_TEAM_TYPEA_', 'FIDE_TEAM_TYPEB_', 'FIDE_TEAM_'):
            if encoded_type.startswith(prefix):
                return encoded_type[len(prefix) :]
        return None

    @classmethod
    def get_not_supported_default_type(cls, encoded_type: str) -> str:
        encoded_type = cls.canonical(encoded_type)
        # A team code must not fall back to an individual system.
        if 'TEAM' in encoded_type:
            if encoded_type.endswith('_BAKU'):
                return encoded_type[: -len('_BAKU')]
            return 'FIDE_TEAM_TYPEA_MP_GP'
        match encoded_type:
            case (
                'BERGER_ROUNDROBIN_G2'
                | 'BERGER_DOUBLEROUNDROBIN'
                | 'FIDE_SCHEVENINGEN_G2'
                | 'FIDE_DOUBLESCHEVENINGEN'
            ):
                return 'FIDE_DOUBLEROUNDROBIN'
            case (
                'CUSTOM_ROUNDROBIN'
                | 'FIDE_SCHILLER'
                | 'CUSTOM_SCHILLER'
                | 'CUSTOM_SCHEVENINGEN'
                | 'FIDE_SCHEVENINGEN_G1'
                | 'CUSTOM_KNOCKOUT'
                | 'CUSTOM_TEAM_KNOCKOUT'
            ):
                return 'FIDE_ROUNDROBIN'
            case _:
                if 'ROUNDROBIN' in encoded_type or 'SCHEVENINGEN' in encoded_type:
                    return 'FIDE_ROUNDROBIN'
                return 'FIDE_DUTCH_2026'


class TrfColor(CoreMapper[str, BoardColor | None]):  # type: ignore
    @staticmethod
    def _core_object_by_outer_value() -> dict[str, BoardColor | None]:
        return {
            'w': BoardColor.WHITE,
            'b': BoardColor.BLACK,
            ' ': None,
            '-': None,
        }

    @classmethod
    def get_outer_value(
        cls,
        core_object: BoardColor | None,
        is_bye: bool = False,
    ) -> str:
        if is_bye:
            return '-'
        return super().get_outer_value(core_object) or ' '
