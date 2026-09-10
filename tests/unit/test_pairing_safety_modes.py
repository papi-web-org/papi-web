import pytest

from data.pairings.knockout import KnockoutPairingSystem, TeamKnockoutPairingSystem
from data.pairings.molter import MolterPairingSystem
from data.pairings.scheveningen import ScheveningenPairingSystem
from data.pairings.systems import SwissPairingSystem, TeamRoundRobinPairingSystem
from data.safety_mode import PairingAction, RoundStatus, SafetyMode


@pytest.mark.parametrize(
    'pairing_system',
    [
        TeamRoundRobinPairingSystem(),
        ScheveningenPairingSystem(),
        MolterPairingSystem(),
        KnockoutPairingSystem(),
        TeamKnockoutPairingSystem(),
    ],
)
def test_unpairing_does_not_require_safety_mode_for_regenerable_pairings(
    pairing_system,
):
    allowed_actions = pairing_system.permission_handler.allowed_actions(
        RoundStatus.CURRENT, SafetyMode.SAFE
    )

    assert PairingAction.FULL_UNPAIRING in allowed_actions
    assert PairingAction.MANUAL_UNPAIRING in allowed_actions


def test_swiss_unpairing_still_requires_safety_mode():
    allowed_actions = SwissPairingSystem().permission_handler.allowed_actions(
        RoundStatus.CURRENT, SafetyMode.SAFE
    )

    assert PairingAction.FULL_UNPAIRING not in allowed_actions
    assert PairingAction.MANUAL_UNPAIRING not in allowed_actions
