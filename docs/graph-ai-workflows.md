# Graph Snapshots and AI Tutorials

Aphelion graph documents use versioned JSON with the `aphelion-graph` format.
They are safe data files: they contain nodes, properties, positions, connections,
groups, and annotations, but no executable code.

## CLI

```bash
aphelion nodes list
aphelion nodes describe "Floor Tracker" --json
aphelion nodes export-schema > nodes.json
aphelion graph schema > graph-schema.json
aphelion graph validate floor-tracking.apgraph --json
aphelion graph render floor-tracking.apgraph --output floor.png --scale 2 --theme dark
aphelion graph inspect floor-tracking.apgraph
aphelion graph format floor-tracking.apgraph --write
aphelion graph export project.aph --output main.apgraph
aphelion graph import main.apgraph --output imported.aph
aphelion tutorial validate examples/floor-tracking.aptutorial --json
aphelion tutorial render examples/floor-tracking.aptutorial --output floor-tutorial
aphelion tutorial schema > tutorial-schema.json
```

Graph rendering is headless and uses model coordinates, so it does not depend on
the current graph viewport or zoom. `--no-watermark`, `--padding`, `--max-width`,
and `--max-height` control export safety and presentation.

## AI Workflow

1. Query `aphelion nodes export-schema`.
2. Generate an `.apgraph` or `.aptutorial` file using actual node and port names.
3. Run validation with `--json` and repair stable error codes such as `UNKNOWN_INPUT` or `INVALID_CONNECTION_TYPE`.
4. Render the validated graph or tutorial into PNG and Markdown.

The sample `examples/floor-tracking.aptutorial` demonstrates a multi-step,
operation-based tutorial that builds a floor tracker and corner-pin setup.
