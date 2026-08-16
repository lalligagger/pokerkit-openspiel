from pokerkit_poc import (
    ActionSpaceReducer,
    StructuredActionPolicy,
    StreetActionRule,
    build_config,
    build_state,
    legal_actions_for_state,
)

spec = build_config()
state = build_state(spec)

# start hand to a legal preflop state
if hasattr(state, "can_collect_bets") and state.can_collect_bets():
    state.collect_bets()
if hasattr(state, "can_post_blind_or_straddle"):
    for _ in range(2):
        if state.can_post_blind_or_straddle():
            state.post_blind_or_straddle()
if hasattr(state, "can_deal_hole"):
    for _ in range(state.player_count * 2):
        if state.can_deal_hole():
            state.deal_hole()

policy = StructuredActionPolicy(streets={
    "preflop": StreetActionRule(
        allow_limp=False,
        bet_amounts=(4,),
        opening_raise_amounts=(4,),
        raise_amounts=(),
        allowed_bet_pcts=(0.5, 1.0),
        allow_all_in=True,
        raise_multiplier=2.5,
    )
})

reducer = ActionSpaceReducer(policy=policy)
print("free:", legal_actions_for_state(state, reducer=None))
print("filtered:", legal_actions_for_state(state, reducer=reducer))