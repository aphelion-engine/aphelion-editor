"""Shared tracking port terminology and documentation helpers."""
from __future__ import annotations

from core.nodes.base import Node

DOC_VIDEO = "Video frames used by the tracker to observe the selected target across time."
DOC_CONFIDENCE = "Normalized tracking confidence from 0.0 to 1.0. Higher values indicate stronger visual and geometric evidence."
DOC_STATE = "Current tracker lifecycle state, including tracking, partial visibility, occlusion, off-screen prediction, searching, reacquisition, or loss."
DOC_HOMOGRAPHY = "3x3 projective transformation mapping the reference surface into its current source-frame position."
DOC_POSITION = "Current tracked position in normalized source-frame coordinates. Values may be outside 0.0-1.0 while the target is off-screen."
DOC_PREDICTED = "Indicates that the current result is produced by the motion model rather than direct visual evidence."
DOC_VALID = "Indicates whether the current result is a direct measured observation. Predicted geometry remains available separately."
DOC_CORNER = "Current perspective corner position in normalized source-frame coordinates. The value is not clamped when the surface leaves the frame."


def document(node: Node, *, inputs: dict[str, str] | None = None,
             outputs: dict[str, str] | None = None) -> None:
    """Attach docs to only the ports that actually exist on ``node``."""
    for name, description in (inputs or {}).items():
        if name in node.inputs:
            node.set_port_documentation(name, input_port=True, doc=description)
    for name, description in (outputs or {}).items():
        if name in node.outputs:
            node.set_port_documentation(name, input_port=False, doc=description)


def document_point_tracker(node: Node) -> None:
    document(node, inputs={"frame": DOC_VIDEO}, outputs={
        "x": DOC_POSITION + " X component.",
        "y": DOC_POSITION + " Y component.",
        "valid": DOC_VALID,
        "confidence": DOC_CONFIDENCE,
        "predicted": DOC_PREDICTED,
    })


def document_planar_tracker(node: Node) -> None:
    outputs = {name: DOC_CORNER for name in node.outputs if name.endswith("_x") or name.endswith("_y")}
    outputs.update({"confidence": DOC_CONFIDENCE, "inliers": "Number of feature correspondences supporting the accepted projective transform.",
                    "reprojection_error": "Mean inlier reprojection error in source-frame pixels. Lower values indicate a more consistent homography.",
                    "valid": DOC_VALID,
                    "drift_score": "Normalized disagreement between incremental tracking and trusted-reference correction. Higher values indicate greater drift risk.",
                    "feature_coverage": "Fraction of spatial tracking cells containing reliable inlier features. Low coverage makes a homography less trustworthy.",
                    "correcting": "Indicates that this frame accepted an absolute reference correction rather than relying only on incremental flow."})
    document(node, inputs={"frame": DOC_VIDEO}, outputs=outputs)


def document_professional_tracker(node: Node) -> None:
    document(node, inputs={
        "frame": DOC_VIDEO,
    }, outputs={
        "x": DOC_POSITION + " X component.", "y": DOC_POSITION + " Y component.",
        "confidence": DOC_CONFIDENCE, "visible": "Whether direct visual evidence currently overlaps the image.",
        "predicted": DOC_PREDICTED, "state": DOC_STATE,
        "backend": "Numeric identifier for the backend currently supplying the primary result.",
    })
