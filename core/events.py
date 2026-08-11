"""Domain events and connection model."""

from dataclasses import dataclass
from enum import Enum, auto


class ObserverEvent(Enum):
    NodeAdded = auto()
    NodeRemoved = auto()
    NodeModified = auto()
    NodesMoved = auto()
    ConnectionCreated = auto()
    ConnectionRemoved = auto()
    FrameChanged = auto()
    ActiveViewerChanged = auto()
    ProjectModified = auto()


# Document mutations that should mark the project dirty (excludes playhead).
DOCUMENT_DIRTY_EVENTS: frozenset[ObserverEvent] = frozenset(
    {
        ObserverEvent.NodeAdded,
        ObserverEvent.NodeRemoved,
        ObserverEvent.NodeModified,
        ObserverEvent.NodesMoved,
        ObserverEvent.ConnectionCreated,
        ObserverEvent.ConnectionRemoved,
        ObserverEvent.ActiveViewerChanged,
        ObserverEvent.ProjectModified,
    }
)


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
