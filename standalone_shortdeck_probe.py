from __future__ import annotations

from pokerkit import Automation
from pokerkit.games import NoLimitShortDeckHoldem


def build_state():
    return NoLimitShortDeckHoldem.create_state(
        automations=(
            Automation.ANTE_POSTING,
            Automation.BET_COLLECTION,
            Automation.BLIND_OR_STRADDLE_POSTING,
            Automation.CARD_BURNING,
            Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
            Automation.HAND_KILLING,
            Automation.CHIPS_PUSHING,
            Automation.CHIPS_PULLING,
        ),
        ante_trimming_status=False,
        raw_antes=(0, 0),
        raw_blinds_or_straddles=(1, 2),
        min_bet=1,
        raw_starting_stacks=(60, 60),
        player_count=2,
    )


def print_state(label: str, state) -> None:
    print(f"\n{label}")
    print("actor_index:", getattr(state, "actor_index", None))
    print("opener_index:", getattr(state, "opener_index", None))
    print("street:", getattr(state, "street", None))
    print("board_cards:", list(getattr(state, "board_cards", []) or []))
    print("hole_cards:", list(getattr(state, "hole_cards", []) or []))
    print("total_pot_amount:", getattr(state, "total_pot_amount", None))
    print("stacks:", list(getattr(state, "stacks", []) or []))
    print("legal_actions:")
    actions = []
    if hasattr(state, "can_check_or_call") and state.can_check_or_call():
        actions.append(("check_or_call", 0))
    if hasattr(state, "can_fold") and state.can_fold():
        actions.append(("fold", 0))
    can_complete = getattr(state, "can_complete_bet_or_raise_to", None)
    if callable(can_complete):
        for amount in (1, 2, 4, 8, 16, 32, 60):
            if can_complete(amount):
                actions.append(("bet_or_raise", int(amount)))
    print(actions)


def main() -> None:
    state = build_state()

    # Post blinds and deal hole cards using the engine's actual state progression.
    if hasattr(state, "can_collect_bets") and state.can_collect_bets():
        state.collect_bets()
    for _ in range(2):
        if hasattr(state, "can_post_blind_or_straddle") and state.can_post_blind_or_straddle():
            state.post_blind_or_straddle()
    for _ in range(4):
        if hasattr(state, "can_deal_hole") and state.can_deal_hole():
            state.deal_hole()

    print_state("INITIAL PRE-FLOP STATE", state)

    # Preflop open to 4 chips. This is the action that the state decides is legal for the current actor.
    if hasattr(state, "can_complete_bet_or_raise_to") and state.can_complete_bet_or_raise_to(4):
        state.complete_bet_or_raise_to(4)
    print_state("AFTER PRE-FLOP OPEN TO 4", state)

    # Call the open. This follows PokerKit's actor progression, no manual actor assignment.
    if hasattr(state, "can_check_or_call") and state.can_check_or_call():
        state.check_or_call()
    print_state("AFTER PRE-FLOP CALL", state)

    # Deal the flop.
    for _ in range(3):
        if hasattr(state, "can_deal_board") and state.can_deal_board():
            state.deal_board()
    print_state("AFTER FLOP DEAL", state)

    # Now force a normal turn progression to test a 6-chip bet.
    # We only do this if PokerKit says 6 is legal in the current state.
    if hasattr(state, "can_deal_board") and state.can_deal_board():
        state.deal_board()
    print_state("AFTER TURN DEAL", state)

    legal_bet_amounts = []
    if hasattr(state, "can_complete_bet_or_raise_to"):
        for amount in (1, 2, 4, 6, 8, 16, 32):
            if state.can_complete_bet_or_raise_to(amount):
                legal_bet_amounts.append(amount)

    print("\nLEGAL BET/RAISE AMOUNTS AT TURN:", legal_bet_amounts)
    print("CAN BET 6 ON TURN?", hasattr(state, "can_complete_bet_or_raise_to") and state.can_complete_bet_or_raise_to(6))

    if hasattr(state, "can_complete_bet_or_raise_to") and state.can_complete_bet_or_raise_to(6):
        state.complete_bet_or_raise_to(6)
        print_state("AFTER TURN BET 6", state)
    else:
        print("Turn bet 6 is not legal in the current PokerKit state.")
        print("This is the correct engine behavior: do not force 6 unless the state says it is legal.")


if __name__ == "__main__":
    main()
