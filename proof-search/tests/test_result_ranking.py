"""
ResultReducer's entry ranking: the two signals that never fired.

_rank_entries scores parsed search entries against the goal -- keyword hits in
the name, signature and module, a bonus for short names, a bonus for the
standard library, and a decay for entries already handed back. Two of those
were dead.

The stdlib bonus lowercased the module and then compared it against
['Z', 'Nat', 'List', 'Bool', 'Arith'], so it could not match. The decay counted
retrievals under hash(frozenset(entry.items())) in _structured_summarization and
looked them up under md5(name) in _rank_entries -- different key spaces, so
hit_count was always 0 and every search came back with the same top ten.

No Rocq process: ranking is pure text work.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_search import ResultReducer

GOAL = "forall n m : Z, Z.add n m = Z.add m n"


def entry(name, module="", signature="forall n m : Z, Z.add n m = Z.add m n"):
    full_name = f"{module}.{name}" if module else name
    return {
        'name': name,
        'full_name': full_name,
        'signature': signature,
        'module': module,
        'raw_line': f"{full_name}: {signature}",
    }


def search_output(names, module="Z"):
    """A search result big enough to be summarized rather than truncated."""
    lines = []
    for name in names:
        lines.append(f"{module}.{name}: forall n m : Z, Z.add n m = Z.add m n")
        lines.append("  " + "padding " * 12)  # indented: a continuation line
    return "\n".join(lines)


def summarized(reducer, content):
    reduced, method = reducer.reduce_result(content, 'direct_search', GOAL)
    assert method == "structured_summary", method
    return [line for line in reduced.splitlines() if line[:2].strip().rstrip('.').isdigit()]


def test_a_standard_library_entry_outranks_an_equal_local_one():
    """The bonus decides it: same keywords, same name length, same signature."""
    local = entry("add_commutative_local", module="MyProject")
    stdlib = entry("add_commutative_stdlb", module="Z")
    assert len(local['name']) == len(stdlib['name']), "the tie-break must not decide this"

    # Local first, so only the bonus can move the stdlib entry above it.
    ranked = ResultReducer()._rank_entries([local, stdlib], GOAL)

    assert [e['name'] for e in ranked] == [stdlib['name'], local['name']]


def test_the_stdlib_bonus_does_not_reward_a_lookalike_module():
    """It is the module list that earns the point, not any module at all."""
    reducer = ResultReducer()
    stdlib = entry("add_commutative_stdlb", module="Nat")
    other = entry("add_commutative_local", module="Zoology")

    ranked = reducer._rank_entries([other, stdlib], GOAL)
    assert ranked[0]['name'] == stdlib['name']

    # Two non-stdlib modules: nothing separates them, so input order stands.
    a = entry("add_commutative_aaaaa", module="Zoology")
    b = entry("add_commutative_bbbbb", module="Frobnicate")
    assert [e['name'] for e in reducer._rank_entries([a, b], GOAL)] == [a['name'], b['name']]


def test_entries_already_handed_back_make_way_for_new_ones():
    """The decay: a second search must not return the same ten lemmas."""
    names = [f"add_lemma_{i:02d}" for i in range(1, 13)]  # 12, and only 10 are shown
    content = search_output(names)
    reducer = ResultReducer()

    first = summarized(reducer, content)
    assert len(first) == reducer.max_entries == 10
    unseen = [n for n in names if not any(n in line for line in first)]
    assert len(unseen) == 2, "the summary should have left two entries out"

    second = summarized(reducer, content)

    for name in unseen:
        assert any(name in line for line in second), (
            f"{name} was never returned and still did not surface: {second[:3]}"
        )
    assert second[0] != first[0], "the same entry came back at the top"


def test_a_fresh_reducer_has_no_memory():
    """The decay is per session: a new reducer must rank from scratch."""
    content = search_output([f"add_lemma_{i:02d}" for i in range(1, 13)])

    first = summarized(ResultReducer(), content)
    again = summarized(ResultReducer(), content)

    assert first == again, "ranking is not deterministic for a fresh reducer"


def test_ranking_keeps_every_entry():
    """Ranking reorders; it must never drop or duplicate an entry."""
    entries = [entry(f"add_lemma_{i:02d}", module="Z") for i in range(1, 8)]
    ranked = ResultReducer()._rank_entries(entries, GOAL)

    assert sorted(e['name'] for e in ranked) == sorted(e['name'] for e in entries)
    assert len(ranked) == len(entries)


def test_without_a_goal_there_is_nothing_to_rank_against():
    entries = [entry("add_lemma_b", module="Z"), entry("add_lemma_a")]
    assert ResultReducer()._rank_entries(entries, "") == entries
