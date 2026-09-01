"""Public compatibility surface for the knock-out pairing system.

The implementation is split by responsibility:

* ``knockout_helpers.systems`` exposes pairing-system capability flags.
* ``knockout_helpers.variations`` registers the supported variation classes.
* ``knockout_helpers.engines`` adapts bracket mechanics to individual/team pairings.
* Other ``knockout_helpers`` modules hold bracket, colour, grouping, display,
  advancement, two-game, and double-elimination rules.
"""

from data.pairings.knockout_helpers.advancement import (
    AdvancementValue as AdvancementValue,
    KnockoutAdvancement as KnockoutAdvancement,
)
from data.pairings.knockout_helpers.colour import (
    KnockoutColourRule as KnockoutColourRule,
    KnockoutColourRuleSetting as KnockoutColourRuleSetting,
)
from data.pairings.knockout_helpers.common import (
    board_winner_player_id as board_winner_player_id,
    team_match_winner_id as team_match_winner_id,
)
from data.pairings.knockout_helpers.double import (
    DoubleEliminationResetSetting as DoubleEliminationResetSetting,
)
from data.pairings.knockout_helpers.engines import (
    DoubleEliminationEngine as DoubleEliminationEngine,
    DoubleEliminationTwoGameEngine as DoubleEliminationTwoGameEngine,
    KnockoutEngine as KnockoutEngine,
    KnockoutTwoGameEngine as KnockoutTwoGameEngine,
    TeamDoubleEliminationEngine as TeamDoubleEliminationEngine,
    TeamDoubleEliminationTwoGameEngine as TeamDoubleEliminationTwoGameEngine,
    TeamKnockoutEngine as TeamKnockoutEngine,
    TeamKnockoutTwoGameEngine as TeamKnockoutTwoGameEngine,
)
from data.pairings.knockout_helpers.grouping import (
    KnockoutGroupingSetting as KnockoutGroupingSetting,
)
from data.pairings.knockout_helpers.settings import (
    KnockoutThirdPlaceSetting as KnockoutThirdPlaceSetting,
)
from data.pairings.knockout_helpers.single import (
    SingleEliminationBracketMixin as SingleEliminationBracketMixin,
)
from data.pairings.knockout_helpers.systems import (
    KnockoutPairingSystem as KnockoutPairingSystem,
    TeamKnockoutPairingSystem as TeamKnockoutPairingSystem,
)
from data.pairings.knockout_helpers.variations import (
    DoubleEliminationTwoGameVariation as DoubleEliminationTwoGameVariation,
    DoubleEliminationVariation as DoubleEliminationVariation,
    KnockoutTwoGameVariation as KnockoutTwoGameVariation,
    KnockoutVariation as KnockoutVariation,
    KnockoutVariationManager as KnockoutVariationManager,
    TeamDoubleEliminationTwoGameVariation as TeamDoubleEliminationTwoGameVariation,
    TeamDoubleEliminationVariation as TeamDoubleEliminationVariation,
    TeamKnockoutTwoGameVariation as TeamKnockoutTwoGameVariation,
    TeamKnockoutVariation as TeamKnockoutVariation,
    TeamKnockoutVariationManager as TeamKnockoutVariationManager,
)
