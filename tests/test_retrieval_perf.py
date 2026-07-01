"""Regression guard: the per-prompt FTS retrieval must not spin on common words or long
prompts. A UserPromptSubmit hook once pegged 99% CPU for tens of seconds because the
recall-biased OR query OR-joined every word (including stopwords), unioning ~the whole vault
into the BM25 candidate set. The query is now stopword-filtered, deduped, and term-capped."""

from precept.knowledge import index as kx


def test_fts_or_query_drops_stopwords_and_dedupes():
    q = kx._fts_query("the of and is to the code and the code vault", match_any=True)
    # true stopwords (present in _ROUTE_STOPWORDS) are dropped from the OR query
    for stop in ('"the"', '"of"', '"and"', '"is"', '"to"'):
        assert stop not in q, stop
    assert '"code"' in q and '"vault"' in q and " OR " in q
    assert q.count('"code"') == 1  # deduped, not repeated


def test_fts_or_query_caps_term_count():
    big = kx._fts_query(" ".join(f"token{i}" for i in range(200)), match_any=True)
    assert (big.count(" OR ") + 1) <= kx._MAX_QUERY_TERMS


def test_fts_and_query_is_unchanged_verbatim():
    # The precise AND path (CLI/audit) keeps tokens verbatim, including short/common words:
    # AND-ing is already selective, so it never explodes.
    assert kx._fts_query("alpha beta", match_any=False) == '"alpha" "beta"'
    assert kx._fts_query("the code", match_any=False) == '"the" "code"'


def test_query_ceiling_helper_installs_without_error(tmp_path):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        kx._install_query_ceiling(conn, budget_s=0.5)  # must not raise
    finally:
        conn.close()
