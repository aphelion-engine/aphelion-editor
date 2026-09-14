# Shape Tracker

Add **Tracking > Shape Tracker** and connect a source frame. Select the node
and place its tracking point over a visible textured feature. Use Track forward
or Track backward in the control strip above the preview.

Placing the point near a frame edge is supported: the pattern box is clamped to
the image and the point stays anchored to the feature you picked.

Choose Ellipse or Rectangle in Properties and adjust Width, Height, and Feather.
For a custom outline, enable **Draw polygon**, click at least three vertices
around the subject, then turn drawing off. The outline closes automatically.
**Undo vertex** removes the last point; **Clear polygon** resets the outline.
These edits support normal Undo/Redo. **Clear** removes motion keyframes only.

The **mask** output supplies a grayscale matte for compositing. X/Y outputs
remain available for driving other nodes. Shape settings, polygon vertices,
and tracked motion are saved with the project and custom node definitions.

The shape follows translation from one tracked feature. It does not estimate
rotation, scale, perspective, or deformation of individual polygon vertices.
Choose a Planar Tracker for four-corner tracking.

Tracker controls occupy their own strip outside the preview image, separate
from performance statistics. They disappear when no tracker is selected.
