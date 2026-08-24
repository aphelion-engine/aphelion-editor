# User guide

Aphelion is a node compositor: media and effects live on a graph, preview plays through a Viewer, and export reads the active Viewer.

## Workspace

The main window is a set of docks:

| Dock | Role |
|---|---|
| Viewport | Preview of the active Viewer |
| Node graph | Create, wire, and select nodes |
| Timeline | Playhead, in/out, duration |
| Properties | Selected node's parameters and keyframes |
| Media pool | Project media |
| Logs | Application log (`Ctrl+Shift+L`) |

Focus shortcuts: viewport `Ctrl+1`, graph `Ctrl+2`, timeline `Ctrl+3`, properties `Ctrl+4`.

Reset docks with **Reset Layout** (`Ctrl+Shift+R`). Show every dock with `Ctrl+Shift+P`. Fullscreen is `F11`.

## Node graph

- **Tab** opens the node search palette.
- **Add Node** menus (graph context menu and the application menu) list every registered type, including plugins that are enabled.
- Number keys `1` and `2` create **Video Input** and **Viewer** by default. Slots `3`–`0` are unassigned; bind them in Preferences.
- Wire output sockets to compatible inputs. Unary video effects take one frame and emit one frame.
- **F** / **Shift+F** fit the graph. **Ctrl+Shift+O** auto-layouts by data flow.

Copy, paste, duplicate, and delete operate on the selection (`Ctrl+C` / `Ctrl+V` / `Ctrl+D` / `Delete`).

## Playback and preview

Space toggles play. Left/Right step a frame. Home/End jump to the start/end. **I** / **O** set in/out.

Preview is a float32 RGB pipeline in `[0, 1]`. Decode-time proxy width defaults to **960px**. Playback can independently drop to a **640px** proxy (Preferences → Performance). Frame cache default budget is **2048 MB** (range 256–16384 MB).

**Ctrl+Shift+K** clears the frame cache.

## Timeline and keyframes

The timeline drives `current_frame` for the project. Animated properties are edited in the properties dock / keyframes panel. Project resolution, fps, and duration are under **Project Settings** (`Ctrl+Shift+,`).

## Export

**Ctrl+E** exports the **active Viewer** to MP4 or a PNG sequence on a background worker. If no Viewer is active, set one in the graph first.

## Projects

Projects are `.aph` JSON documents. **Ctrl+S** saves; **Ctrl+Shift+S** saves as. Autosave runs every **30 seconds** once the project has a path (disable in Preferences → General).

## Preferences

**Ctrl+,** opens Preferences.

| Tab | Typical settings |
|---|---|
| General | Font, graph grid, autosave, status key hints |
| Performance | Cache size, decode cache, prefetch, playback proxy, drop-frames |
| Plugins | Discovery sources, enable/disable, reload, plugin folders |
| Keybinds | Remap every action and create-node slot |
| Appearance | Built-in themes or a custom `.aph.theme` |
| Node Colors | Header colors per node type |

**Ctrl+/** opens the keyboard shortcuts overview.

## Default shortcuts

| Action | Shortcut |
|---|---|
| New / Open / Save / Save As | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` |
| Export | `Ctrl+E` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Search nodes | `Tab` |
| Fit graph | `F` |
| Organize graph | `Ctrl+Shift+O` |
| Play / Pause | `Space` |
| Previous / Next frame | `Left` / `Right` |
| In / Out | `I` / `O` |
| Preferences | `Ctrl+,` |
| Keyboard shortcuts | `Ctrl+/` |

Pin frequently used actions on the pin bar (toolbar). Visibility is remembered in preferences.
