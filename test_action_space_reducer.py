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


def test_end_to_end_hand_reaches_terminal_with_expected_street_progression():
    from pokerkit_poc import (
        ActionSpaceReducer,
        build_config,
        build_state,
        compact_action_repr,
        legal_actions_for_state,
        parse_action_repr,
        simulate_uniform_hand_to_showdown,
    )

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

    seen_streets = []
    max_steps = 200
    for _ in range(max_steps):
        current_street = ActionSpaceReducer._current_street_name(state)
        seen_streets.append(current_street)
        legal = legal_actions_for_state(state)
        if not legal:
            if callable(getattr(state, 'can_deal_board', None)) and state.can_deal_board():
                state.deal_board()
                continue
            break

        action = legal[0]
        assert compact_action_repr(action) == parse_action_repr(compact_action_repr(action))[0]
        if action[0] == 'bet_or_raise':
            assert action[1] is not None
            state.complete_bet_or_raise_to(int(action[1]))
        elif action[0] == 'check_or_call':
            state.check_or_call()
        else:
            state.fold()

        if callable(getattr(state, 'can_deal_board', None)) and state.can_deal_board() and getattr(state, 'street', None) is not None:
            state.deal_board()

        if getattr(state, 'status', None) is not None and str(getattr(state, 'status')).lower().endswith('terminal'):
            break

    assert seen_streets[0] == 'preflop'
    assert 'preflop' in seen_streets
    assert 'flop' in seen_streets or 'turn' in seen_streets or 'river' in seen_streets
    assert str(getattr(state, 'status', 'unknown')).lower().endswith('terminal')

    result = simulate_uniform_hand_to_showdown(spec)
    assert result['final_status']
    assert 'final_stacks' in result


def test_compact_action_repr_round_trips_for_core_action_family():
    from pokerkit_poc import compact_action_repr, parse_action_repr

    round_trip = [
        ('check_or_call', 0),
        ('fold', 0),
        ('bet_or_raise', 4),
        ('bet_or_raise', 16),
    ]

    for action in round_trip:
        encoded = compact_action_repr(action)
        decoded = parse_action_repr(encoded)
        assert decoded == action
