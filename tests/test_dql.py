"""The Dataview subset: what it answers, and what it refuses by name (ADR-0016).

Two halves, and the second matters more. A query language that silently drops the clause it did
not understand returns a table that looks right and is not — so most of this file is about
unsupported syntax raising with its own name in the message.
"""

from __future__ import annotations

import pytest

from hvk import dql


def rows_of(result) -> list:
    return [row["path"] for row in result.rows]


def values_of(result, column: str) -> list:
    return [row["values"].get(column) for row in result.rows]


@pytest.fixture
def vault(index):
    location, conn, _ = index("dataview")
    return conn


def run(conn, query: str):
    return dql.run(dql.parse(query), conn)


# -- the clauses ------------------------------------------------------------------------------

def test_list_from_a_tag(vault):
    assert sorted(rows_of(run(vault, "LIST FROM #active"))) == [
        "Projects/Alpha.md", "Projects/Gamma.md",
    ]


def test_from_a_folder_does_not_reach_outside_it(vault):
    paths = rows_of(run(vault, 'LIST FROM "Projects"'))
    assert "Archive/Old.md" not in paths
    assert len(paths) == 3


def test_a_negated_source(vault):
    assert "Projects/Alpha.md" not in rows_of(run(vault, "LIST FROM -#active"))


def test_where_uses_one_equals_the_way_dataview_writes_it(vault):
    assert sorted(rows_of(run(vault, 'LIST WHERE status = "closed"'))) == [
        "Archive/Old.md", "Projects/Beta.md",
    ]


def test_a_bare_field_in_where_means_it_has_one(vault):
    assert rows_of(run(vault, "LIST WHERE rating")) == ["Projects/Alpha.md", "Projects/Beta.md"]


def test_and_or_not_are_words_here(vault):
    result = run(vault, 'LIST WHERE status = "open" and rating > 3')
    assert rows_of(result) == ["Projects/Alpha.md"]


def test_table_columns_and_headers(vault):
    result = run(vault, 'TABLE status, rating AS "Score" FROM "Projects"')
    assert result.headers == ["File", "status", "Score"]


def test_table_without_id_drops_the_file_column(vault):
    result = run(vault, 'TABLE WITHOUT ID status FROM "Projects"')
    assert result.headers == ["status"]


def test_sort_puts_nulls_last_whichever_way_it_points(vault):
    """A note with no rating is not the highest-rated note, and not the lowest either."""
    descending = values_of(run(vault, 'TABLE rating FROM "Projects" SORT rating DESC'), "rating")
    ascending = values_of(run(vault, 'TABLE rating FROM "Projects" SORT rating ASC'), "rating")
    assert descending == [5, 2, None]
    assert ascending == [2, 5, None]


def test_limit(vault):
    result = run(vault, 'LIST FROM "Projects" LIMIT 1')
    assert len(result.rows) == 1
    assert result.total == 3, "the total is what matched, not what was shown"


# -- the difference from Bases -----------------------------------------------------------------

def test_inline_fields_are_visible_here(vault):
    """The real distinction. Bases sees Obsidian properties; Dataview sees `key:: value` too,
    because that is what Dataview writes."""
    result = run(vault, "TABLE owner WHERE owner")
    assert sorted(values_of(result, "owner")) == ["Ana", "Bruno"]


def test_frontmatter_and_inline_fields_answer_the_same_way(vault):
    assert rows_of(run(vault, 'LIST WHERE owner = "Ana"')) == ["Projects/Alpha.md"]
    assert rows_of(run(vault, 'LIST WHERE status = "open" and owner = "Ana"')) == [
        "Projects/Alpha.md"
    ]


# -- functions ----------------------------------------------------------------------------------

def test_dataview_calls_a_function_where_the_engine_calls_a_method(vault):
    assert rows_of(run(vault, 'LIST WHERE contains(file.name, "Alph")')) == ["Projects/Alpha.md"]


def test_an_unknown_function_is_refused_rather_than_answered_with_nothing(vault):
    with pytest.raises(Exception) as caught:
        run(vault, "LIST WHERE dateformat(file.mtime, \"yyyy\") = \"2026\"")
    assert "dateformat" in str(caught.value)


# -- what it will not do, said out loud ---------------------------------------------------------

@pytest.mark.parametrize("query, expected", [
    ("TASK WHERE done", "TASK"),
    ("CALENDAR file.day", "CALENDAR"),
    ("LIST GROUP BY status", "GROUP"),
    ("LIST FLATTEN authors", "FLATTEN"),
    ("LIST FROM [[Some Note]]", "[[link]]"),
    ('LIST FROM #a and #b', "one source"),
    ("SELECT * FROM notes", "LIST or TABLE"),
    ("LIST LIMIT plenty", "LIMIT takes a number"),
    ("", "empty query"),
])
def test_unsupported_syntax_names_itself(query, expected):
    with pytest.raises(dql.DqlError) as caught:
        dql.parse(query)
    assert expected in str(caught.value)


def test_an_expression_that_will_not_parse_says_which_one(vault):
    with pytest.raises(dql.DqlError) as caught:
        run(vault, "LIST WHERE status ===== ")
    assert "status" in str(caught.value)


# -- blocks in a note ----------------------------------------------------------------------------

def test_the_blocks_of_a_note_are_found_in_order():
    text = (
        "# Note\n\n```dataview\nLIST FROM #a\n```\n\n"
        "```dataviewjs\ndv.list([])\n```\n\n"
        "```dataview\nTABLE x\n```\n"
    )
    assert dql.blocks_in(text) == ["LIST FROM #a", "TABLE x"]


def test_dataviewjs_is_not_a_query():
    """Executing plugin code is permanently out of scope, so its blocks are not even read."""
    assert dql.blocks_in("```dataviewjs\ndv.pages()\n```\n") == []


def test_a_note_with_no_blocks_yields_none():
    assert dql.blocks_in("# Just a note\n") == []


# -- through the command line ---------------------------------------------------------------

@pytest.fixture
def cli_run(tmp_path, capsys):
    from hvk import cli
    from conftest import VAULTS

    base = ["--vault", str(VAULTS / "dataview"), "--index", str(tmp_path / "idx")]
    cli.main([*base, "scan"])
    capsys.readouterr()

    def _run(*args):
        code = cli.main([*base, *args])
        return code, capsys.readouterr()

    return _run


def test_a_note_that_is_not_there_is_not_a_note_without_blocks(cli_run):
    """Reading a missing file gives empty text by design (ADR-0007), so without a check a
    typo in the note name reads as "this note has no blocks" and you believe it."""
    code, output = cli_run("dql", "--note", "Nope.md")
    assert code != 0
    assert "no such note" in output.err


def test_a_note_with_no_blocks_says_exactly_that(cli_run):
    code, output = cli_run("dql", "--note", "Projects/Alpha.md")
    assert code == 0
    assert "no dataview blocks" in output.out


def test_an_unsupported_query_is_a_message_and_not_a_traceback(cli_run):
    code, output = cli_run("dql", "TASK WHERE done")
    assert code != 0
    assert output.err.startswith("hvk: ")
    assert "TASK" in output.err
    assert "Traceback" not in output.err


def test_the_blocks_of_a_note_are_all_run(cli_run):
    code, output = cli_run("dql", "--note", "Dashboard.md")
    assert code == 0
    assert output.out.count("LIST FROM #active") == 1
    assert "TABLE" in output.out
    assert "dv.list" not in output.out, "the dataviewjs block is not a query"
