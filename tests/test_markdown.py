"""Parsing a note: tags, headings, blocks, tasks, inline fields and what must be ignored."""

from __future__ import annotations

from hvk.parse.markdown import parse_note, split_frontmatter


def tags(text):
    return [(t.tag, t.source) for t in parse_note(text).tags]


def test_frontmatter_split_reports_the_first_body_line():
    yaml_text, body, start = split_frontmatter("---\na: 1\n---\nbody\n")
    assert yaml_text == "a: 1"
    assert body.startswith("body")
    assert start == 4


def test_unterminated_frontmatter_is_body():
    yaml_text, body, start = split_frontmatter("---\na: 1\nno closing fence\n")
    assert yaml_text is None
    assert start == 1
    assert body.startswith("---")


def test_inline_and_frontmatter_tags_are_both_recorded():
    note = parse_note("---\ntags: [alpha, beta]\n---\n\ntext #gamma and #nested/tag\n")
    assert ("alpha", "frontmatter") in tags_of(note)
    assert ("gamma", "inline") in tags_of(note)
    assert ("nested/tag", "inline") in tags_of(note)


def tags_of(note):
    return [(t.tag, t.source) for t in note.tags]


def test_headings_are_not_tags():
    note = parse_note("# Title\n\n## Section\n")
    assert note.tags == []
    assert [(h.level, h.text) for h in note.headings] == [(1, "Title"), (2, "Section")]


def test_a_purely_numeric_tag_is_not_a_tag():
    assert tags("issue #2026 and #v2\n") == [("v2", "inline")]


def test_closing_hashes_are_stripped_from_headings():
    note = parse_note("## Section ##\n")
    assert note.headings[0].text == "Section"


def test_block_ids_are_captured_and_removed_from_the_line():
    note = parse_note("A paragraph. ^my-block\n")
    assert [(b.block_id, b.line) for b in note.blocks] == [("my-block", 1)]


def test_task_states_and_nesting():
    text = (
        "- [ ] pending\n"
        "- [x] done\n"
        "- [X] capital\n"
        "- [-] cancelled\n"
        "    - [ ] nested\n"
    )
    note = parse_note(text)
    assert [(t.status, t.done) for t in note.tasks] == [
        (" ", False), ("x", True), ("X", True), ("-", False), (" ", False)
    ]


def test_task_inside_a_blockquote_counts():
    note = parse_note("> - [ ] quoted task\n")
    assert [t.text for t in note.tasks] == ["quoted task"]


def test_fenced_code_suppresses_everything():
    note = parse_note("```\n- [ ] task\n[[Link]]\n#tag\n```\n")
    assert note.tasks == [] and note.links == [] and note.tags == []


def test_tilde_fences_work_too():
    note = parse_note("~~~\n[[Link]]\n~~~\n")
    assert note.links == []


def test_inline_code_suppresses_links():
    note = parse_note("real [[One]] but not `[[Two]]`\n")
    assert [ln.target_raw for ln in note.links] == ["One"]


def test_indented_code_after_a_blank_line_is_code():
    note = parse_note("text\n\n    [[Hidden]]\n\nmore\n")
    assert note.links == []


def test_indentation_inside_a_list_is_not_code():
    note = parse_note("- item\n    - [ ] nested task with [[Link]]\n")
    assert [t.text for t in note.tasks] == ["nested task with [[Link]]"]
    assert [ln.target_raw for ln in note.links] == ["Link"]


def test_obsidian_comments_are_ignored():
    note = parse_note("before %%[[Hidden]]%% after [[Shown]]\n")
    assert [ln.target_raw for ln in note.links] == ["Shown"]


def test_multiline_comments_span_lines():
    note = parse_note("%%\n[[Hidden]]\n%%\n[[Shown]]\n")
    assert [ln.target_raw for ln in note.links] == ["Shown"]


def test_inline_fields_are_properties():
    note = parse_note("Owner:: Angel\n")
    field = [p for p in note.props if p.inline]
    assert [(p.key, p.value) for p in field] == [("Owner", "Angel")]


def test_bracketed_inline_fields():
    note = parse_note("text [rating:: 8] more\n")
    assert [(p.key, p.value) for p in note.props if p.inline] == [("rating", "8")]


def test_a_task_line_is_not_an_inline_field():
    note = parse_note("- [ ] call Ana:: tomorrow\n")
    assert [p.key for p in note.props if p.inline] == []


def test_title_prefers_frontmatter_then_h1_then_filename():
    assert parse_note("---\ntitle: From YAML\n---\n\n# From H1\n").title == "From YAML"
    assert parse_note("# From H1\n").title == "From H1"
    assert parse_note("no headings\n", fallback_title="From File").title == "From File"


def test_line_numbers_account_for_frontmatter():
    note = parse_note("---\na: 1\n---\n\n# Heading\n")
    assert note.headings[0].line == 5


def test_markdown_link_targets_are_separated_from_their_subpath():
    note = parse_note("[text](Some%20Note.md#Heading)\n")
    assert note.links[0].target_raw == "Some%20Note.md"
    assert note.links[0].subpath == "#Heading"
    assert note.links[0].kind == "markdown"


def test_external_targets_are_classified_as_external():
    note = parse_note("[a](https://example.com) [b](mailto:x@y.z) [c](//host/x)\n")
    assert {ln.kind for ln in note.links} == {"external"}
