import bisect
from collections import defaultdict

LineRange = tuple[int, int]


class ContentPartition:
    """List-like container enforcing that all content belongs to a partition of chunks."""

    def __init__(self, content_list: list["Content"] = []):
        self.data: dict[tuple[int, int], "Content"] = {}
        self.content_boundaries: defaultdict[int, list[LineRange]] = defaultdict(list)

        for content in content_list:
            partition_id = (content.chunk_number, content.first_line)
            if partition_id in self.data:
                raise ValueError(f"Partition {partition_id} is already assigned.")

            # ensure that the content does not not intersect any existing boundaries
            if (
                (
                    content.first_line >= boundary[0]
                    and content.first_line <= boundary[1]
                )
                or (
                    content.last_line <= boundary[1]
                    and content.last_line <= boundary[1]
                )
                for boundary in self.content_boundaries[content.chunk_number]
            ):
                pass

            self.data[partition_id] = content
            bisect.insort(
                self.content_boundaries[content.chunk_number],
                (content.first_line, content.last_line),
            )


class Content:
    def __init__(self):
        self.chunk_number: int
        self.first_line: int
        self.last_line: int

    @property
    def n_lines(self) -> int:
        return self.last_line - self.first_line + 1

    def __lt__(self, other: "Content") -> bool:
        if self.chunk_number != other.chunk_number:
            return self.chunk_number < other.chunk_number
        return self.first_line < other.first_line

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Content):
            return NotImplemented
        return (self.chunk_number == other.chunk_number) and (
            self.first_line == other.first_line
        )
