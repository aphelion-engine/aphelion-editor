"""Graph sections: the coarse processing stages used when arranging nodes.

Aphelion has no first-class group object in the project document — the
``.apgraph`` exchange format carries ``groups`` as data, and the graph
renderer draws them, but the live project only stores node positions. Rather
than inventing project state, the assistant's "group" tools operate on
*sections*: a labelled set of nodes that is physically arranged into its own
column band and remembered by the host for the session.

That keeps the feature honest (the only thing it changes is real node
positions, through ``MoveNodesCommand``) while still giving the user the
INPUT → TRACKING → EFFECTS → COMPOSITING → OUTPUT organisation the design
calls for.
"""

from __future__ import annotations

from typing import Any

#: Display order of the processing stages.
SECTION_ORDER: tuple[str, ...] = (
    "INPUT",
    "TRACKING",
    "EFFECTS",
    "COMPOSITING",
    "OUTPUT",
)

#: Registry category → section. Anything unlisted lands in ``EFFECTS``, which
#: is the safe default: it is where most processing nodes genuinely live.
CATEGORY_SECTIONS: dict[str, str] = {
    "Input/Output": "INPUT",
    "Generators": "INPUT",
    "Audio": "INPUT",
    "Tracking": "TRACKING",
    "VFX": "TRACKING",
    "Roto": "EFFECTS",
    "Color": "EFFECTS",
    "Filter": "EFFECTS",
    "Distort": "EFFECTS",
    "Stylize": "EFFECTS",
    "Creative": "EFFECTS",
    "Depth": "EFFECTS",
    "Keying": "EFFECTS",
    "Timing": "EFFECTS",
    "Transform": "COMPOSITING",
    "Compositing": "COMPOSITING",
    "Math": "EFFECTS",
    "Logic": "EFFECTS",
    "Utility": "EFFECTS",
    "Value": "EFFECTS",
}

DEFAULT_SECTION: str = "EFFECTS"


def classify_section(node: Any) -> str:
    """Return the processing stage ``node`` belongs to."""
    if getattr(node, "node_type", "") == "Viewer":
        return "OUTPUT"
    category = str(getattr(node, "node_category", "") or "")
    if category in CATEGORY_SECTIONS:
        return CATEGORY_SECTIONS[category]
    # A node that consumes nothing is a source, whatever its category says.
    if not getattr(node, "inputs", None):
        return "INPUT"
    return DEFAULT_SECTION


def group_by_section(nodes: dict[str, Any]) -> dict[str, list[str]]:
    """Bucket ``node_id``s by section, in canonical section order."""
    buckets: dict[str, list[str]] = {name: [] for name in SECTION_ORDER}
    extra: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        section = classify_section(node)
        bucket = buckets.get(section)
        if bucket is None:
            extra.setdefault(section, []).append(node_id)
        else:
            bucket.append(node_id)
    for name, ids in extra.items():
        buckets[name] = ids
    return {name: ids for name, ids in buckets.items() if ids}


def next_section_name(existing: list[str]) -> str:
    """Return a unique default name for a new custom section."""
    used = {name.upper() for name in existing}
    if "CUSTOM" not in used:
        return "CUSTOM"
    index = 2
    while f"CUSTOM {index}" in used:
        index += 1
    return f"CUSTOM {index}"
