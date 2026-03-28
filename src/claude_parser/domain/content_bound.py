from dataclasses import dataclass
from claude_parser.domain.ports import ContentBase


@dataclass
class ContentBound[T: ContentBase]:
    lower: T
    upper: T

    def union(self, x: "ContentBound[T] | None") -> "ContentBound[T]":
        if x is None:
            return self
        return ContentBound(min(self.lower, x.lower), max(self.upper, x.upper))

    def intersect(self, x: "ContentBound[T] | None") -> "ContentBound[T] | None":
        if x is None:
            return None
        lower = max(self.lower, x.lower)
        upper = min(self.upper, x.upper)

        return ContentBound(lower, upper) if lower <= upper else None
