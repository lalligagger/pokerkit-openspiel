from pokerkit_poc import (
    ActionSpaceReducer,
    StreetActionRule,
    StructuredActionPolicy,
    build_config,
    build_state,
    legal_actions_for_state,
)


def _started_preflop_state():
    spec = build_config()
    state = build_state(spec)
    if hasattr(state, 'can_collect_bets') and state.can_collect_bets():
        state.collect_bets()
    if hasattr(state, 'can_post_blind_or_straddle'):
        for _ in range(2):
            if state.can_post_blind_or_straddle():
                state.post_blind_or_straddle()
    if hasattr(state, 'can_deal_hole'):
        for _ in range(state.player_count * 2):
            if state.can_deal_hole():
                state.deal_hole()
    return state


def test_reducer_can_disable_fallback_on_empty():
    reducer = ActionSpaceReducer(
        policy=StructuredActionPolicy(streets={}),
        fallback_on_empty=False,
    )
    state = build_state(build_config())

    assert reducer.reduce(state, []) == []


def test_no_limp_preflop_removes_check_or_call_for_first_actor():
    policy = StructuredActionPolicy(streets={
        'preflop': StreetActionRule(
            allow_limp=False,
            bet_amounts=(4,),
            opening_raise_amounts=(4,),
            raise_amounts=(),
            allowed_bet_pcts=(0.5, 1.0),
            allow_all_in=True,
            raise_multiplier=2.5,
        )
    })
    reducer = ActionSpaceReducer(policy=policy, fallback_on_empty=False)
    state = _started_preflop_state()

    assert ('check_or_call', 0) in legal_actions_for_state(state, reducer=None)
    filtered = legal_actions_for_state(state, reducer=reducer)
    assert ('check_or_call', 0) not in filtered


def test_live_betting_state_keeps_pokerkit_legal_bet_family():
    policy = StructuredActionPolicy(streets={
        'preflop': StreetActionRule(
            allow_limp=False,
            bet_amounts=(4,),
            opening_raise_amounts=(4,),
            raise_amounts=(),
            allowed_bet_pcts=(0.5, 1.0),
            allow_all_in=True,
            raise_multiplier=2.5,
        ),
        'flop': StreetActionRule(
            allow_limp=False,
            bet_amounts=(4,),
            opening_raise_amounts=(4,),
            raise_amounts=(),
            allowed_bet_pcts=(0.5, 1.0),
            allow_all_in=True,
            raise_multiplier=2.5,
        ),
    })
    reducer = ActionSpaceReducer(policy=policy, fallback_on_empty=False)
    state = _started_preflop_state()
    state.complete_bet_or_raise_to(4)

    filtered = legal_actions_for_state(state, reducer=reducer)
    bet_family = [action for action in filtered if action[0] == 'bet_or_raise']
    assert bet_family
    assert any(amount in {8, 16, 32, 60} for _, amount in bet_family)


def test_first_to_act_allowlist_removes_open_fold_on_this_street():
    policy = StructuredActionPolicy(streets={
        'preflop': StreetActionRule(
            first_to_act_allowed=('fold', 'bet_or_raise'),
            allow_limp=False,
            bet_amounts=(4,),
            opening_raise_amounts=(4,),
            raise_amounts=(),
            allowed_bet_pcts=(0.5, 1.0),
            allow_all_in=True,
            raise_multiplier=2.5,
        ),
        'flop': StreetActionRule(
            first_to_act_allowed=('check_or_call', 'bet_or_raise'),
            allow_limp=False,
            bet_amounts=(4,),
            opening_raise_amounts=(4,),
            raise_amounts=(),
            allowed_bet_pcts=(0.5, 1.0),
            allow_all_in=True,
            raise_multiplier=2.5,
        ),
    })
    reducer = ActionSpaceReducer(policy=policy, fallback_on_empty=False)
    state = _started_preflop_state()

    filtered = legal_actions_for_state(state, reducer=reducer)
    assert ('fold', 0) in filtered
    assert ('check_or_call', 0) not in filtered

    # Once the action has already opened, the allowlist should no longer remove the normal
    # check/call family for the next actor.
    state.complete_bet_or_raise_to(4)
    state.actor_index = 0
    filtered_after_bet = legal_actions_for_state(state, reducer=reducer)
    assert ('check_or_call', 0) in filtered_after_bet
