import os
import sys

sys.path.insert(0, 'src')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.nodes.catalog import BUILTIN_NODE_TYPES

WANT = {
    "io": ["Video Input", "Image Input", "Viewer"],
    "key": ["Chroma Key", "Spill Suppress", "Matte Edge", "Combine Masks",
            "Premult", "Clean Plate", "Despill Pro"],
    "comp": ["Merge", "Dissolve", "Alpha Over", "Alpha Under", "Stencil",
             "Matte Combine Pro"],
    "xf": ["Transform 2D", "Transform 3D", "Crop", "Corner Pin", "Corner Pin Mask",
           "Perspective", "Spherical Warp", "Polar Warp", "Swirl", "Shear"],
    "fx": ["Gaussian Blur", "Sharpen", "Denoise", "Edge Detect", "Pixelate",
           "Vignette", "Motion Blur"],
    "mask": ["Channel Mask", "Invert Mask", "Frame Switch"],
    "roto": ["Roto"],
    "track": ["Tracker", "Planar Tracker", "Shape Tracker"],
    "math": ["Value", "Math", "Math Function", "Clamp", "Remap", "Property Link",
             "Property Drive", "Oscillator", "Random", "Compare", "Logic Gate",
             "Select", "Range Check", "Smooth Step"],
    "time": ["Timeline Frame", "Timeline Time", "Timeline FPS", "Timeline Max Frame",
             "Timeline Normalized"],
}
NAMES = {n for group in WANT.values() for n in group}


def fmt(value):
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


for node_type in BUILTIN_NODE_TYPES:
    if node_type.node_type not in NAMES:
        continue
    node = node_type()
    print(f"### {node.node_type}")
    print(f"  category: {node.node_category}")
    print(f"  inputs : {[(s.name, s.socket_type.name) for s in node.inputs.values()]}")
    print(f"  outputs: {[(s.name, s.socket_type.name) for s in node.outputs.values()]}")
    props = sorted(node.properties.items(), key=lambda kv: getattr(kv[1], "priority", 0))
    for key, p in props:
        rng = ""
        if getattr(p, "slider_min_value", None) is not None:
            rng = f" [{p.slider_min_value}..{p.slider_max_value}]"
        print(f"    {key:<22} {p.input_type.name:<14} {fmt(p.value)}{rng}"
              f"  ({getattr(p, 'group', '')} / {getattr(p, 'label', '')})")
    print()
