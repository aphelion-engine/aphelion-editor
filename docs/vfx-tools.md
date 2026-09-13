# Tracking and VFX tools

New nodes appear in the Add Node menu after restarting the editor.

| Category | Node | Use |
| --- | --- | --- |
| Tracking | Track Offset | Offset or scale Tracker X/Y coordinates. |
| Tracking | Track Distance | Distance, angle, and midpoint of two tracks, measured in percent coordinates. |
| Tracking | Match Move | Connect Tracker X/Y to in_x/in_y and set reference coordinates. Amount -1 applies inverse translation for stabilization. |
| Transform | Perspective Tilt | Project a flat image card with X/Y tilt and focal length. |
| Transform | Keystone | Adjust horizontal and vertical trapezoid perspective. |
| VFX | Chromatic Aberration | Offset red and blue channels for lens fringing. |
| VFX | Directional Blur | Apply directional motion streaks; length is a radius in pixels. |
| Color | Channel Shuffle | Reorder or replicate RGB channels in rendered passes. |

Numeric controls have in_ sockets for animation or tracking connections. Tracking utilities consume existing tracks; they do not run a new tracking solver. Perspective nodes project a flat image, not a 3D scene. Warps retain the original frame size and use black outside the image.

Creating a custom node now exposes unconnected main inputs and outputs as well as externally wired sockets. Optional in_ parameter sockets are exposed when externally wired. Existing definitions retain their declared interface; use Edit Custom Node to add ports to previously saved definitions that lack them.
