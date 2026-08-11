"""Domain events and connection model."""

from dataclasses import dataclass
from enum import Enum, auto


class ObserverEvent(Enum):
    NodeAdded = auto()
    NodeRemoved = auto()
    NodeModified = auto()
    ConnectionCreated = auto()
    ConnectionRemoved = auto()
    FrameChanged = auto()
    ProjectModified = auto()


@dataclass(frozen=True)
class Connection:
    output_node_id: str
    output_slot: str
    input_node_id: str
    input_slot: str

    def __hash__(self) -> int:
        return hash(
            (self.output_node_id, self.output_slot, self.input_node_id, self.input_slot)
        )
