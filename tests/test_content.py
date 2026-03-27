import pytest
from content import Content, ContentPartition


def make_content(chunk: int, first: int, last: int) -> Content:
    return Content(chunk_number=chunk, first_line=first, last_line=last)


class TestContentOrdering:
    def test_lt_same_chunk(self):
        a = make_content(0, 1, 10)
        b = make_content(0, 11, 20)
        assert a < b
        assert not b < a

    def test_lt_different_chunks(self):
        a = make_content(0, 50, 100)
        b = make_content(1, 1, 10)
        assert a < b
        assert not b < a

    def test_eq_same_position(self):
        a = make_content(0, 1, 10)
        b = make_content(0, 1, 10)
        assert a == b

    def test_eq_different_last_line(self):
        # eq only compares chunk_number and first_line
        a = make_content(0, 1, 10)
        b = make_content(0, 1, 20)
        assert a == b

    def test_not_eq_different_chunk(self):
        a = make_content(0, 1, 10)
        b = make_content(1, 1, 10)
        assert a != b


class TestContentBool:
    def test_always_true(self):
        assert bool(make_content(0, 1, 10))

    def test_truthy_in_conditional(self):
        c: Content | None = make_content(0, 1, 10)
        assert c


class TestContentPartition:
    def test_append_non_overlapping(self):
        p = ContentPartition()
        p.append(make_content(0, 1, 10))
        p.append(make_content(0, 11, 20))
        assert len(p.data) == 2

    def test_append_overlap_raises(self):
        p = ContentPartition()
        p.append(make_content(0, 1, 15))
        with pytest.raises(ValueError):
            p.append(make_content(0, 10, 20))

    def test_append_duplicate_partition_raises(self):
        p = ContentPartition()
        p.append(make_content(0, 1, 10))
        with pytest.raises(ValueError):
            p.append(make_content(0, 1, 10))

    def test_append_different_chunks_no_overlap_check(self):
        p = ContentPartition()
        p.append(make_content(0, 1, 100))
        p.append(make_content(1, 1, 100))
        assert len(p.data) == 2
