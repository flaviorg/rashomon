from rashomon.spec import apply_to_speckit, speckit_session

ANSWERED = [{"question": "Which rows?", "value": "the filtered view"}, {"question": "Format?", "value": "cents"}]


def test_speckit_session_format():
    assert speckit_session(ANSWERED, "2026-11-21") == (
        "### Session 2026-11-21\n\n- Q: Which rows? → A: the filtered view\n- Q: Format? → A: cents\n"
    )


def test_creates_clarifications_section(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Feature\n\nbody\n")
    apply_to_speckit(p, ANSWERED, "2026-11-21")
    assert p.read_text() == (
        "# Feature\n\nbody\n\n## Clarifications\n\n### Session 2026-11-21\n\n"
        "- Q: Which rows? → A: the filtered view\n- Q: Format? → A: cents\n"
    )


def test_appends_session_inside_existing_section(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# F\n\n## Clarifications\n\n### Session 2026-11-01\n\n- Q: a → A: b\n\n## Requirements\n\n- R1\n")
    apply_to_speckit(p, ANSWERED[:1], "2026-11-21")
    text = p.read_text()
    assert text.index("Session 2026-11-01") < text.index("Session 2026-11-21") < text.index("## Requirements")
    assert text.endswith("## Requirements\n\n- R1\n")


def test_missing_file_is_created(tmp_path):
    p = tmp_path / "new.md"
    apply_to_speckit(p, ANSWERED[:1], "2026-11-21")
    assert p.read_text().startswith("## Clarifications\n\n### Session 2026-11-21")
