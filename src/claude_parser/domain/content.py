from dataclasses import dataclass, field


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
