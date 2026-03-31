import bisect
from collections import defaultdict
from claude_parser.domain.content import Content

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
