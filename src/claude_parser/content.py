from dataclasses import dataclass, field
import bisect
from collections import defaultdict

LineRange = tuple[int, int]


class ContentPartition:
    """List-like container enforcing that all content belongs to a partition of chunks."""

    def __init__(self, content_list: list[Content] = []):
        self.data: dict[tuple[int, int], Content] = {}
        self.content_boundaries: defaultdict[int, list[LineRange]] = defaultdict(list)

        for content in content_list:
            self.append(content)

    def append(self, content: Content):
        partition_id = (content.chunk_number, content.first_line)
        if partition_id in self.data:
            raise ValueError(f"Partition {partition_id} is already assigned.")

        boundaries = self.content_boundaries[content.chunk_number]
        new_range: LineRange = (content.first_line, content.last_line)
        idx = bisect.bisect_left(boundaries, new_range)

        if idx > 0 and boundaries[idx - 1][1] >= new_range[0]:
            raise ValueError(
                f"{new_range} overlaps with existing boundary {boundaries[idx - 1]}."
            )
        if idx < len(boundaries) and new_range[1] >= boundaries[idx][0]:
            raise ValueError(
                f"{new_range} overlaps with existing boundary {boundaries[idx]}."
            )

        self.data[partition_id] = content
        boundaries.insert(idx, new_range)


@dataclass(order=True)
class Content:
    chunk_number: int
    first_line: int
    last_line: int = field(compare=False)

    @property
    def n_lines(self) -> int:
        return self.last_line - self.first_line + 1

    def __bool__(self) -> bool:
        return True


@dataclass
class ContentBound:
    lower: Content
    upper: Content

    def union(self, x: ContentBound | None) -> ContentBound:
        if x is None:
            return self
        return ContentBound(min(self.lower, x.lower), max(self.upper, x.upper))

    def intersect(self, x: ContentBound | None) -> ContentBound | None:
        if x is None:
            return None
        lower = max(self.lower, x.lower)
        upper = min(self.upper, x.upper)

        return ContentBound(lower, upper) if lower <= upper else None
