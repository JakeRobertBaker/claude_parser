from pathlib import Path

from claude_parser.adapters.state.filesystem import FilesystemStateStore


def _write_clean(path: Path, text: str) -> None:
    path.write_text(text + "<!-- cutoff -->\n", encoding="utf-8")


def test_read_all_clean_before_cutoff_uses_numeric_clean_file_order(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    clean_dir = state_dir / "clean"
    clean_dir.mkdir(parents=True)

    _write_clean(clean_dir / "clean_0.md", "zero\n")
    _write_clean(clean_dir / "clean_1.md", "one\n")
    _write_clean(clean_dir / "clean_2.md", "two\n")
    _write_clean(clean_dir / "clean_10.md", "ten\n")

    store = FilesystemStateStore(
        state_dir=str(state_dir),
        raw_path=__file__,
        resume=False,
    )

    merged = store.read_all_clean_before_cutoff()
    assert merged == "zero\none\ntwo\nten\n"
