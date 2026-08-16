#!/usr/bin/env python3
"""Bootstrap an MCCFR-ready launch script for PokerKit + OpenSpiel.

This script is intentionally small and explicit:
- it ensures OpenSpiel is importable under either pyspiel or open_spiel
- it imports the existing PokerKit action-space framework from pokerkit_poc
- it runs a strict terminal-data collection pass with the same reducer used in the
  smoke tests and node probes
- it prepares the ground for the actual MCCFR trainer loop without re-implementing
  game legality or terminal rules in a custom engine
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
FORK = ROOT / "pokerkit_fork"
for candidate in (ROOT, FORK):
    path = str(candidate)
    if path not in sys.path:
        sys.path.insert(0, path)


class RegretTable:
    """Minimal regret accumulator for MCCFR smoke-test visibility.

    This is intentionally lightweight: it exposes the same shape a real regret
    table would need (info-set keyed, action keyed, cumulative regrets) but it
    keeps the bootstrap path simple and scriptable.
    """

    def __init__(self) -> None:
        self._regrets: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._visit_counts: Dict[str, int] = defaultdict(int)
        self._action_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def _normalize_policy(self, policy: Optional[Dict[str, float]], legal_actions: Iterable[str]) -> Dict[str, float]:
        actions = list(legal_actions)
        if not actions:
            return {}
        if policy:
            cleaned = {action: float(policy.get(action, 0.0)) for action in actions}
            total = sum(cleaned.values())
            if total > 0:
                return {action: value / total for action, value in cleaned.items()}
        uniform = 1.0 / len(actions)
        return {action: uniform for action in actions}

    def strategy_for_info_set(self, info_set_key: str, action_source: Any) -> Dict[str, float]:
        if isinstance(action_source, dict):
            actions = sorted(action_source.keys())
            current = {action: float(action_source.get(action, 0.0)) for action in actions}
        else:
            actions = list(action_source)
            current = self._regrets.get(info_set_key, {})
            current = {action: float(current.get(action, 0.0)) for action in actions}

        if not actions:
            return {}
        positive = {action: max(float(current.get(action, 0.0)), 0.0) for action in actions}
        total = sum(positive.values())
        if total <= 0.0:
            uniform = 1.0 / len(actions)
            return {action: uniform for action in actions}
        return {action: positive[action] / total for action in actions}

    def choose_action(self, info_set_key: str, legal_actions: Iterable[str]) -> Optional[str]:
        actions = list(legal_actions)
        if not actions:
            return None
        policy = self.strategy_for_info_set(info_set_key, actions)
        choices = list(policy.keys())
        weights = [float(policy[action]) for action in choices]
        return random.choices(choices, weights=weights, k=1)[0]

    def observe(
        self,
        *,
        info_set_key: str,
        legal_actions: Iterable[str],
        chosen_action: Optional[str],
        realized_utility: float,
        policy: Optional[Dict[str, float]] = None,
    ) -> None:
        actions = list(legal_actions)
        if not actions:
            return

        self._visit_counts[info_set_key] += 1
        if chosen_action is not None:
            self._action_counts[info_set_key][chosen_action] += 1
        probs = self._normalize_policy(policy, actions)
        if chosen_action is None:
            chosen_action = actions[0]

        action_values = {
            action: float(realized_utility if action == chosen_action else 0.0)
            for action in actions
        }
        avg_utility = sum(probs.get(action, 0.0) * action_values[action] for action in actions)

        current = self._regrets[info_set_key]
        for action in actions:
            regret = action_values[action] - avg_utility
            current[action] = current.get(action, 0.0) + float(regret)

    def summary(self) -> Dict[str, Any]:
        infoset_count = len(self._regrets)
        all_entries = [
            (info_set, action, value)
            for info_set, action_map in self._regrets.items()
            for action, value in action_map.items()
        ]
        nonzero = sum(1 for _, _, value in all_entries if abs(value) > 1e-12)
        regret_table = {info_set: dict(sorted(action_map.items())) for info_set, action_map in sorted(self._regrets.items())}
        strategy_table = {
            info_set: dict(sorted(self.strategy_for_info_set(info_set, action_map).items()))
            for info_set, action_map in sorted(self._regrets.items())
        }
        top_infosets = [
            {
                "info_set": info_set,
                "visits": self._visit_counts.get(info_set, 0),
                "actions": dict(sorted(action_map.items())),
                "action_frequency": dict(sorted(self._action_counts.get(info_set, {}).items())),
                "strategy": dict(sorted(self.strategy_for_info_set(info_set, action_map).items())),
            }
            for info_set, action_map in sorted(self._regrets.items(), key=lambda item: sum(abs(v) for v in item[1].values()), reverse=True)[:5]
        ]
        node_table = [
            {
                "index": idx,
                "node": info_set,
                "visits": self._visit_counts.get(info_set, 0),
                "action_frequency": dict(sorted(self._action_counts.get(info_set, {}).items())),
                "regret": dict(sorted(action_map.items())),
                "strategy": dict(sorted(self.strategy_for_info_set(info_set, action_map).items())),
            }
            for idx, (info_set, action_map) in enumerate(sorted(self._regrets.items()))
        ]
        return {
            "infoset_count": infoset_count,
            "total_regret_entries": len(all_entries),
            "nonzero_regret_entries": nonzero,
            "top_infosets": top_infosets,
            "node_table": node_table,
            "regret_table": regret_table,
            "strategy_table": strategy_table,
        }


def require_openspiel():
    """Return the OpenSpiel module or raise a clear installation error."""
    errors: List[str] = []
    for name in ("pyspiel", "open_spiel"):
        try:
            module = __import__(name)
            return module
        except Exception as exc:  # pragma: no cover - environment-dependent path
            errors.append(f"{name}: {exc}")

    raise RuntimeError(
        "OpenSpiel is required for the MCCFR launch path. "
        "Install it in the active environment or use the included Docker / conda setup. "
        f"Import attempts: {errors}"
    )


def build_default_action_reducer():
    from pokerkit_poc import ActionSpaceReducer, build_default_policy

    return ActionSpaceReducer(
        max_legal_actions=6,
        allowed_bet_amounts=(1, 2, 4, 8, 16, 32, 60),
        policy=build_default_policy(),
    )


def compact_card(card: Any) -> str:
    text = str(card).strip()
    if "(" in text and ")" in text:
        inner = text[text.rfind("(") + 1:text.rfind(")")]
        if inner:
            return inner
    if isinstance(card, str):
        return card
    return text.replace(" ", "").replace("-", "")


def compact_cards(cards: Iterable[Any]) -> str:
    compacted = [compact_card(card) for card in cards]
    compacted = [value for value in compacted if value]
    return "".join(compacted) if compacted else "none"


def compact_betting_history(state: Any) -> str:
    history: List[str] = []
    for operation in getattr(state, "operations", []) or []:
        cls_name = type(operation).__name__
        player_index = getattr(operation, "player_index", 0)
        if cls_name == "CompletionBettingOrRaisingTo":
            history.append(f"p{player_index}:bet{getattr(operation, 'amount', 0)}")
        elif cls_name == "CheckingOrCalling":
            history.append(f"p{player_index}:cc{getattr(operation, 'amount', 0)}")
        elif cls_name == "Folding":
            history.append(f"p{player_index}:f")
    return "|".join(history) if history else "start"


def compact_action_label(action: Any) -> str:
    from pokerkit_poc import compact_action_repr

    if isinstance(action, str):
        return action
    if isinstance(action, (tuple, list)):
        if len(action) == 2:
            return compact_action_repr((str(action[0]), int(action[1]) if action[1] is not None else None))
        return compact_action_repr((str(action[0]), None))
    return str(action)


def canonical_info_set_key(state: Any, legal_actions: Optional[Iterable[Any]] = None) -> str:
    from pokerkit_poc import ActionSpaceReducer

    street = ActionSpaceReducer._current_street_name(state)
    actor_index = int(getattr(state, "actor_index", 0) or 0)
    board_cards = list(getattr(state, "board_cards", []) or [])
    hole_cards = list(getattr(state, "hole_cards", []) or [])
    actor_hole = hole_cards[actor_index] if actor_index < len(hole_cards) else []
    board_key = compact_cards(board_cards)
    hole_key = compact_cards(actor_hole)
    history = compact_betting_history(state)
    legal = list(legal_actions or [])
    legal_key = "|".join(sorted({compact_action_label(action) for action in legal})) if legal else "none"
    return f"{street}:p{actor_index}:board={board_key}:hole={hole_key}:hist={history}:legal={legal_key}"


def simulate_hand_trace(spec: Any, reducer: Any, regret_table: Optional["RegretTable"] = None) -> List[Dict[str, Any]]:
    from pokerkit_poc import (
        ActionSpaceReducer,
        apply_action,
        legal_actions_for_state,
        build_state,
    )

    state = build_state(spec)
    if hasattr(state, "can_collect_bets") and state.can_collect_bets():
        state.collect_bets()
    if hasattr(state, "can_post_blind_or_straddle"):
        for _ in range(2):
            if state.can_post_blind_or_straddle():
                state.post_blind_or_straddle()
    if hasattr(state, "can_deal_hole"):
        for _ in range(getattr(state, "player_count", spec.num_players) * 2):
            if state.can_deal_hole():
                state.deal_hole()

    trace: List[Dict[str, Any]] = []
    for _ in range(200):
        if getattr(state, "status", None) is False:
            break

        legal = legal_actions_for_state(state, reducer=reducer)
        if not legal:
            if callable(getattr(state, "can_deal_board", None)) and state.can_deal_board():
                state.deal_board()
                continue
            if callable(getattr(state, "can_select_runout_count", None)) and state.can_select_runout_count():
                state.select_runout_count(None)
                continue
            if callable(getattr(state, "can_show_or_muck_hole_cards", None)) and state.can_show_or_muck_hole_cards():
                state.show_or_muck_hole_cards()
                continue
            break

        key = canonical_info_set_key(state, legal)
        if regret_table is not None:
            policy = regret_table.strategy_for_info_set(key, [compact_action_label(item) for item in legal])
            action_label = regret_table.choose_action(key, [compact_action_label(item) for item in legal])
            if action_label is None:
                break
            chosen_action = next(item for item in legal if compact_action_label(item) == action_label)
        else:
            action_label = random.choice([compact_action_label(item) for item in legal])
            chosen_action = next(item for item in legal if compact_action_label(item) == action_label)
            policy = {compact_action_label(item): 1.0 / len(legal) for item in legal}

        trace.append(
            {
                "info_set_key": key,
                "legal_actions": [compact_action_label(item) for item in legal],
                "chosen_action": compact_action_label(chosen_action),
                "policy": policy,
                "street": ActionSpaceReducer._current_street_name(state),
                "actor_index": int(getattr(state, "actor_index", 0) or 0),
            }
        )
        apply_action(state, chosen_action)

        if getattr(state, "status", None) is not None and str(getattr(state, "status")).lower().endswith("terminal"):
            break

    final_stacks = list(getattr(state, "stacks", []) or [])
    if len(final_stacks) < 2:
        final_stacks = [0, 0]
    for event in trace:
        actor_index = int(event.get("actor_index", 0) or 0)
        event["realized_utility"] = float(final_stacks[actor_index] if actor_index < len(final_stacks) else 0)
    return trace


def print_mccfr_summary(label: str, data: List[Dict[str, Any]], refresh_interval: int) -> None:
    summary = build_regret_summary(data)
    print(f"\n=== MCCFR summary {label} (refresh every {refresh_interval} iterations) ===")
    print(f"infoset_count={summary['infoset_count']}")
    print(f"total_regret_entries={summary['total_regret_entries']}")
    print(f"nonzero_regret_entries={summary['nonzero_regret_entries']}")
    print("node_index | visits | node | regrets | strategy")
    for row in summary.get("node_table", []):
        node = row["node"]
        regrets = ", ".join(f"{k}={v:.4f}" for k, v in row["regret"].items())
        strategy = ", ".join(f"{k}={v:.4f}" for k, v in row["strategy"].items())
        print(f"{row['index']:>3} | {row['visits']:>6} | {node} | {regrets} | {strategy}")


def collect_terminal_runs(iterations: int, reducer=None, refresh_interval: int = 100, verbose: bool = False) -> List[Dict[str, Any]]:
    from pokerkit_poc import build_config, simulate_uniform_hand_to_showdown

    spec = build_config()
    reducer_obj = reducer or build_default_action_reducer()
    regret_table = RegretTable()
    rows: List[Dict[str, Any]] = []
    for idx in range(iterations):
        trace = simulate_hand_trace(spec, reducer_obj, regret_table=regret_table)
        result = simulate_uniform_hand_to_showdown(spec, reducer=reducer_obj)

        for event in trace:
            legal_actions = [str(action) for action in event.get("legal_actions", [])]
            if not legal_actions:
                continue
            info_set_key = event.get("info_set_key")
            chosen_action = event.get("chosen_action")
            realized_utility = float(event.get("realized_utility", 0.0))
            if info_set_key is None:
                continue
            regret_table.observe(
                info_set_key=info_set_key,
                legal_actions=legal_actions,
                chosen_action=chosen_action,
                realized_utility=realized_utility,
                policy=event.get("policy", {}) or {},
            )

        rows.append(
            {
                "iteration": idx,
                "final_stacks": list(result.get("final_stacks", [])),
                "final_board": list(result.get("final_board", [])),
                "final_hole": list(result.get("final_hole", [])),
                "final_status": result.get("final_status"),
                "stats": result.get("stats", {}),
                "strategy_impact": result.get("strategy_impact", {}),
                "node_events": trace,
                "node_count": len(trace),
            }
        )
        if verbose and ((idx + 1) % refresh_interval == 0 or idx == iterations - 1):
            print_mccfr_summary(f"after_{idx + 1}_iterations", rows, refresh_interval)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch an MCCFR-ready PokerKit + OpenSpiel bootstrap.")
    parser.add_argument("--iterations", type=int, default=1, help="Number of terminal runs to collect before training.")
    parser.add_argument("--refresh-interval", type=int, default=100, help="How often to print the MCCFR summary to stdout.")
    parser.add_argument(
        "--output-path",
        type=str,
        default="/app/mccfr_bootstrap.json",
        help="Where to save the final JSON output. In Docker this should be a bind-mounted repo path so it is visible on the host.",
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed for deterministic smoke runs.")
    parser.add_argument("--verbose", action="store_true", help="Print the compact MCCFR summary table to stdout.")
    return parser.parse_args()


def build_regret_summary(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    regret_table = RegretTable()
    for run in data:
        node_events = run.get("node_events", []) or []
        if not node_events:
            stats = run.get("stats", {}) or {}
            action_frequency = stats.get("action_frequency", {}) or {}
            last_policy = stats.get("last_policy", {}) or {}
            if not action_frequency:
                continue
            info_set_key = f"terminal:iter_{run.get('iteration', 0)}"
            legal_actions = [str(action) for action in action_frequency.keys()]
            chosen_action = max(last_policy, key=last_policy.get, default=max(action_frequency, key=action_frequency.get))
            realized_utility = float(stats.get("avg_payoff", 0.0))
            regret_table.observe(
                info_set_key=info_set_key,
                legal_actions=legal_actions,
                chosen_action=chosen_action,
                realized_utility=realized_utility,
                policy=last_policy or action_frequency,
            )
            continue

        for event in node_events:
            legal_actions = [str(action) for action in event.get("legal_actions", []) or []]
            if not legal_actions:
                continue
            policy = event.get("policy", {}) or {}
            chosen_action = event.get("chosen_action")
            realized_utility = float(event.get("realized_utility", 0.0))
            info_set_key = event.get("info_set_key")
            if not info_set_key:
                continue
            regret_table.observe(
                info_set_key=info_set_key,
                legal_actions=legal_actions,
                chosen_action=chosen_action,
                realized_utility=realized_utility,
                policy=policy,
            )
    return regret_table.summary()


def main() -> None:
    args = parse_args()

    try:
        pyspiel = require_openspiel()
    except RuntimeError as exc:
        print(f"OpenSpiel bootstrap failed: {exc}")
        raise SystemExit(1) from exc

    import random

    random.seed(args.seed)

    print("OpenSpiel module available:", getattr(pyspiel, "__file__", pyspiel))
    print("PokerKit framework import path:", ROOT)

    reducer = build_default_action_reducer()
    refresh_interval = max(1, args.refresh_interval)
    data = collect_terminal_runs(args.iterations, reducer=reducer, refresh_interval=refresh_interval, verbose=args.verbose)

    regret_summary = build_regret_summary(data)
    payload = {
        "seed": args.seed,
        "iterations": args.iterations,
        "game": "shortdeck_hunl",
        "engine": "PokerKit + OpenSpiel bootstrap",
        "terminal_runs": data,
        "mccfr_summary": regret_summary,
    }

    output_path = Path(args.output_path)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"Terminal-run data written to: {output_path}")

    if args.verbose:
        print(f"Final summary: infoset_count={regret_summary['infoset_count']}, nonzero_regret_entries={regret_summary['nonzero_regret_entries']}")
        print("node_index | visits | node | regrets | strategy")
        for row in regret_summary.get("node_rows", []):
            node = row["node"]
            regrets = ", ".join(f"{k}={v:.4f}" for k, v in row["regret"].items())
            strategy = ", ".join(f"{k}={v:.4f}" for k, v in row["strategy"].items())
            print(f"{row['index']:>3} | {row['visits']:>6} | {node} | {regrets} | {strategy}")

    print("Bootstrap complete. Next stage: wire the actual MCCFR trainer loop to this terminal data and compact action keys.")


if __name__ == "__main__":
    main()
