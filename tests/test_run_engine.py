from claude_parser.application.run_engine import (
    BatchPlan,
    RunSnapshot,
    advance,
    clamp_cutoff,
    complete,
    plan_next,
)


def test_plan_next_computes_expected_batch_fields() -> None:
    snapshot = RunSnapshot(next_start_line=0, next_chunk_id=3, sections_completed=2)
    raw_lines = ["aa\n", "bbbb\n", "cc\n"]

    plan = plan_next(snapshot, raw_lines, batch_tokens=5, token_counter=len)

    assert plan == BatchPlan(
        ordinal=3,
        chunk_id="chunk_003",
        start_line=0,
        end_line=2,
        raw_content="aa\nbbbb\n",
        raw_line_count=2,
        raw_token_count=8,
        clean_token_target=4,
    )


def test_plan_next_raises_when_no_raw_left() -> None:
    try:
        plan_next(
            RunSnapshot(next_start_line=2, next_chunk_id=1, sections_completed=1),
            ["a\n", "b\n"],
            batch_tokens=10,
            token_counter=len,
        )
    except RuntimeError as exc:
        assert "No raw content left" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_clamp_cutoff_respects_plan_bounds() -> None:
    plan = BatchPlan(
        ordinal=0,
        chunk_id="chunk_000",
        start_line=10,
        end_line=20,
        raw_content="",
        raw_line_count=10,
        raw_token_count=100,
        clean_token_target=50,
    )

    assert clamp_cutoff(plan, 5) == 11
    assert clamp_cutoff(plan, 15) == 15
    assert clamp_cutoff(plan, 99) == 20


def test_advance_moves_snapshot_forward() -> None:
    snapshot = RunSnapshot(next_start_line=0, next_chunk_id=4, sections_completed=9)

    updated = advance(snapshot, cutoff_line=123)

    assert updated == RunSnapshot(
        next_start_line=123,
        next_chunk_id=5,
        sections_completed=10,
    )


def test_complete_uses_next_start_line() -> None:
    assert complete(RunSnapshot(next_start_line=5), total_raw_lines=5)
    assert not complete(RunSnapshot(next_start_line=4), total_raw_lines=5)
