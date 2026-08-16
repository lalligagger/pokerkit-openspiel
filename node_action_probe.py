import argparse
import ast
import json
from collections import Counter
from pathlib import Path

from pokerkit_poc import (
    ActionSpaceReducer,
    NodeObservation,
    StreetActionRule,
    StructuredActionPolicy,
    apply_action,
    build_config,
    build_state,
    choose_uniform_action,
    legal_actions_for_state,
)


def parse_args():
    parser = argparse.ArgumentParser(description='Compare free vs filtered action-space reachability in PokerKit.')
    parser.add_argument('--iterations', type=int, default=1000)
    parser.add_argument('--modes', nargs='*', default=['free', 'filtered'])
    parser.add_argument('--top-n', type=int, default=15)
    parser.add_argument('--node-detail', type=str, choices=['preflop', 'flop', 'turn', 'river'], default=None,
                        help='Print detailed node summaries for one street only (e.g. flop) instead of dumping all nodes.')
    parser.add_argument('--policy-json', type=str, default=str(Path(__file__).with_name('shortdeck_hunl_action_overrides.json')))
    return parser.parse_args()


def policy_from_json(path: str):
    with open(path, 'r', encoding='utf-8') as handle:
        payload = json.load(handle)

    rules = payload.get('rules', {})
    streets = {}
    for street_name, spec in rules.items():
        open_amounts = tuple(int(v) for v in spec.get('open_amounts', ()))
        streets[street_name] = StreetActionRule(
            allow_limp=bool(spec.get('allow_limp', False)),
            opening_raise_amounts=open_amounts,
            bet_amounts=open_amounts,
            raise_amounts=(),
            allowed_bet_pcts=tuple(float(v) for v in spec.get('bet_percent_of_pot', ())),
            allow_all_in=True,
            raise_multiplier=float(spec.get('raise_multiplier', 2.5)),
            raise_only_all_in=False,
        )
    return StructuredActionPolicy(streets=streets)


def start_hand(state, spec):
    if spec.ante > 0:
        if callable(getattr(state, 'can_post_ante', None)) and state.can_post_ante():
            state.post_ante()
    if callable(getattr(state, 'can_collect_bets', None)) and state.can_collect_bets():
        state.collect_bets()
    if callable(getattr(state, 'can_post_blind_or_straddle', None)):
        for _ in range(2):
            if state.can_post_blind_or_straddle():
                state.post_blind_or_straddle()
    if callable(getattr(state, 'deal_hole', None)):
        for _ in range(getattr(state, 'player_count', spec.num_players) * 2):
            if state.can_deal_hole():
                state.deal_hole()
    return state


def build_reducer(policy_path: str):
    return ActionSpaceReducer(
        max_legal_actions=6,
        allowed_bet_amounts=(1, 2, 4, 8, 16, 32, 60),
        policy=policy_from_json(policy_path),
    )


def betting_history_signature(state) -> str:
    actions = []
    for operation in getattr(state, 'operations', []) or []:
        cls_name = type(operation).__name__
        if cls_name == 'CompletionBettingOrRaisingTo':
            actions.append(f"p{operation.player_index}:bet{operation.amount}")
        elif cls_name == 'CheckingOrCalling':
            actions.append(f"p{operation.player_index}:cc{operation.amount}")
        elif cls_name == 'Folding':
            actions.append(f"p{operation.player_index}:f")
    return ' | '.join(actions) if actions else 'start'


def run(mode: str, iterations: int, spec, reducer=None):
    node_map = {}
    for _ in range(iterations):
        state = build_state(spec)
        start_hand(state, spec)

        while True:
            reducer_obj = None if mode == 'free' else reducer
            legal = legal_actions_for_state(state, reducer=reducer_obj)

            if not legal:
                if callable(getattr(state, 'can_deal_board', None)) and state.can_deal_board():
                    state.deal_board()
                    continue
                if getattr(state, 'status', None) is not None and str(getattr(state, 'status')).lower().endswith('terminal'):
                    break
                break

            obs = NodeObservation.from_state(state, actor_index=getattr(state, 'actor_index', 0))
            key = obs.full_info_key
            history = betting_history_signature(state)
            entry = node_map.setdefault(key, {
                'count': 0,
                'actions': set(),
                'action_counts': Counter(),
                'observed_data': {
                    'street': obs.street,
                    'actor_index': obs.actor_index,
                    'public_board_key': obs.public_board_key,
                    'private_key': obs.private_key,
                    'full_info_key': obs.full_info_key,
                },
                'betting_history': history,
                'regret_updates': {},
            })
            entry['betting_history'] = history
            entry['count'] += 1

            for action in legal:
                action_tuple = tuple(action)
                entry['actions'].add(action_tuple)
                entry['action_counts'][action_tuple] += 1

            # A simple regret-style summary: proportional action exposure under the restricted game tree.
            total_action_observations = sum(entry['action_counts'].values())
            entry['regret_updates'] = {
                str(action): count / total_action_observations
                for action, count in sorted(entry['action_counts'].items(), key=lambda item: (str(item[0][0]), int(item[0][1] or 0)))
            }

            action = choose_uniform_action(state, reducer=reducer_obj)
            if action is None:
                break
            apply_action(state, action)

            if callable(getattr(state, 'can_deal_board', None)) and state.can_deal_board() and getattr(state, 'street', None) is not None:
                state.deal_board()

            if getattr(state, 'status', None) is not None and str(getattr(state, 'status')).lower().endswith('terminal'):
                break

    rows = []
    for key, meta in sorted(node_map.items(), key=lambda kv: (-kv[1]['count'], kv[0])):
        actions = sorted([list(a) for a in meta['actions']], key=lambda a: (str(a[0]), int(a[1] or 0)))
        rows.append({
            'node': key,
            'visits': meta['count'],
            'actions': actions,
            'action_counts': {str(tuple(action)): count for action, count in sorted(meta['action_counts'].items(), key=lambda item: (str(item[0][0]), int(item[0][1] or 0)))},
            'observed_data': meta['observed_data'],
            'regret_updates': meta['regret_updates'],
            'betting_history': meta.get('betting_history'),
        })
    return rows


if __name__ == '__main__':
    args = parse_args()
    spec = build_config()
    reducer = build_reducer(args.policy_json)

    for mode in args.modes:
        rows = run(mode, args.iterations, spec, reducer=reducer)
        total_visits = sum(row['visits'] for row in rows)
        action_counter = Counter()
        street_counter = Counter()
        for row in rows:
            for action in row['actions']:
                action_counter[tuple(action)] += 1
            street = row['observed_data'].get('street', 'unknown')
            street_counter[street] += 1

        print(f'=== MODE: {mode} ===')
        print(f'unique_nodes={len(rows)}')
        print(f'total_visits={total_visits}')
        print('fallback_on_empty=False')
        print(f'postflop_nodes={sum(1 for row in rows if row["node"].startswith("flop:") or row["node"].startswith("turn:") or row["node"].startswith("river:"))}')
        print(f'average_actions_per_node={sum(len(row["actions"]) for row in rows) / len(rows) if rows else 0.0}')
        print(f'action_family_counts={dict(sorted(((str(k[0]), v) for k, v in action_counter.items()), key=lambda item: item[0]))}')
        print(f'street_counts={dict(sorted(street_counter.items()))}')
        print(f'missing_street_nodes={street_counter.get("unknown", 0)}')

        if args.node_detail:
            detail_rows = [row for row in rows if row['node'].startswith(f'{args.node_detail}:')]
            grouped = {}
            for row in detail_rows:
                history_key = row.get('betting_history', 'start')
                grouped.setdefault(history_key, {
                    'visits': 0,
                    'examples': [],
                    'action_counts': Counter(),
                    'history': history_key,
                })
                grouped[history_key]['visits'] += row['visits']
                grouped[history_key]['examples'].append(row)
                for action_key, count in row['action_counts'].items():
                    grouped[history_key]['action_counts'][action_key] += count

            ordered = sorted(
                grouped.items(),
                key=lambda item: (-item[1]['visits'], item[0]),
            )

            print(f'detail_street={args.node_detail}')
            print(f'unique_histories={len(ordered)} total_visits={sum(summary["visits"] for _, summary in ordered)}')
            if ordered:
                for rank, (history_key, summary) in enumerate(ordered[:args.top_n], start=1):
                    action_families = sorted(
                        {
                            ast.literal_eval(action_key)[0]
                            for action_key in summary['action_counts'].keys()
                        },
                        key=lambda name: str(name),
                    )
                    print(
                        f'  [{rank}] history={history_key} count={summary["visits"]} '
                        f'families={action_families} merged_nodes={len(summary["examples"])}'
                    )
                    if args.top_n is not None and rank <= args.top_n:
                        print(
                            f'      action_counts={dict(sorted(summary["action_counts"].items(), key=lambda item: str(item[0])))}'
                        )
                        sample_actions = sorted(
                            {tuple(action) for row in summary['examples'] for action in row['actions']},
                            key=lambda a: (str(a[0]), int(a[1] or 0)),
                        )
                        print(f'      observed_actions={sample_actions}')
            else:
                print(f'  no rows for street={args.node_detail}')
        print('')
