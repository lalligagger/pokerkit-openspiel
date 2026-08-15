# PokerKit Short-Deck MCCFR Roadmap

## Goal

Integrate a PokerKit-backed short-deck HUNL MCCFR loop while preserving PokerKit legal action generation and filtering through a policy layer instead of inventing a custom action engine.

## Principles

- PokerKit legal actions are the source of truth.
- Policy filtering is a constraint layer, not a replacement for PokerKit legality.
- Keep compact string representations for MCCFR internal keys, but preserve raw tuple actions at the boundary.
- Use a strict smoke-test loop before enabling training logic.

## Phase 1: State and legality validation

### 1.1 Terminal-state validation
- [ ] Confirm a full hand can run from preflop through showdown or forced terminal state.
- [ ] Check that state progression through streets is stable and consistent.
- [ ] Confirm `status` flips to a terminal state under the actual PokerKit game.
- [ ] Ensure no unknown streets appear in the progression loop.

### 1.2 Policy-filter validation
- [ ] Validate legal actions are filtered correctly without removing all legal actions unexpectedly.
- [ ] Confirm the reducer preserves PokerKit legal families while enforcing policy constraints.
- [ ] Confirm the strict mode (`--no-fallback-on-empty`) is safe for training use.

### 1.3 Node/action observation validation
- [ ] Continue validating per-state node keys and actor identity.
- [ ] Confirm observed histories are grouped correctly by betting history rather than raw node ID when requested.
- [ ] Confirm action families and sizes are consistent with PokerKit legal action generation.

## Phase 2: Compact MCCFR action encoding

### 2.1 Raw-to-compact translation
- [ ] Keep raw PokerKit action tuples as the external truth.
- [ ] Provide canonical compact string encodings for trainer internals.
- [ ] Round-trip compact strings back to tuple form without ambiguity.

Examples:
- `('check_or_call', 0)` -> `cc`
- `('fold', 0)` -> `f`
- `('bet_or_raise', 4)` -> `b4`
- `('bet_or_raise', 16)` -> `b16`

### 2.2 Trainer keying
- [ ] Use compact strings as node/action keys in MCCFR tables.
- [ ] Keep readable debug output using the human-friendly raw tuple names when needed.
- [ ] Ensure key normalization is consistent across all streets and actor positions.

## Phase 3: MCCFR integration

### 3.1 Single-hand MCCFR smoke test
- [ ] Build a trainer loop that plays one hand end-to-end.
- [ ] Confirm legal actions are generated from PokerKit and filtered through policy.
- [ ] Confirm each chosen action is applied correctly via `apply_action`.
- [ ] Confirm regret tables and strategy tables update without crashing.

### 3.2 Uniform policy baseline
- [ ] Use uniform policy as the default smoke-test strategy.
- [ ] Confirm the runner reaches terminal states over repeated iterations.
- [ ] Track node accumulation and legal action counts under the filtered policy.

### 3.3 Multi-iteration training
- [ ] Run multiple iterations with the uniform baseline.
- [ ] Check strategy updates are stable and finite.
- [ ] Inspect node accumulation and action frequencies for anomalies.

## Phase 4: Production checks

- [ ] No synthetic action families beyond PokerKit legal actions.
- [ ] No hardcoded false assumptions about betting sizes or street invariants.
- [ ] No unknown-street states in aggregated diagnostics.
- [ ] Terminal progression and node accumulation remain stable over long runs.

## Immediate next step

Implement the terminal-state fix and the compact-string action adapter, then run a single-hand MCCFR smoke test before scaling to repeated iterations.

## Files of interest

- `pokerkit_poc.py`
- `node_action_probe.py`
- `test_action_space_reducer.py`
- `shortdeck_hunl_action_overrides.json`
- `pokerkit_fork/pokerkit/state.py`
