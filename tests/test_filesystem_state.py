from pathlib import Path
import json

from math_parser.adapters.state.filesystem import FilesystemStateStore
from math_parser.application.run_engine import RunSnapshot


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


def test_state_resume_defaults_missing_continuation_and_persists_new_value(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw.md"
    raw_path.write_text("raw\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "next_start_line": 1,
                "next_chunk_id": 2,
                "sections_completed": 2,
            }
        ),
        encoding="utf-8",
    )
    store = FilesystemStateStore(str(state_dir), str(raw_path), resume=True)
    store.init()

    assert store.snapshot.continuation_node_id is None

    store.save_snapshot(
        RunSnapshot(
            next_start_line=1,
            next_chunk_id=2,
            sections_completed=2,
            continuation_node_id="def_alpha",
        )
    )
    saved = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert saved["continuation_node_id"] == "def_alpha"


def test_read_prior_clean_returns_content_before_cutoff(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    clean_dir = state_dir / "clean"
    clean_dir.mkdir(parents=True)
    (clean_dir / "clean_0.md").write_text(
        "first\nsecond\n<!-- cutoff -->\nignored\n",
        encoding="utf-8",
    )
    store = FilesystemStateStore(str(state_dir), __file__)

    assert store.read_prior_clean(1) == "first\nsecond\n"


def test_raw_batch_and_next_context_are_separate_artifacts(tmp_path: Path) -> None:
    raw_path = tmp_path / "source.md"
    raw_path.write_text("source\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    store = FilesystemStateStore(str(state_dir), str(raw_path))
    store.init()

    store.write_raw_batch(3, "committable core\n")
    store.write_next_raw_context(3, "read-only following context\n")

    assert (state_dir / "raw" / "raw_3.md").read_text(encoding="utf-8") == (
        "committable core\n"
    )
    assert (state_dir / "raw" / "next_context_3.md").read_text(
        encoding="utf-8"
    ) == "read-only following context\n"
