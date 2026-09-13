# Smoother preview playback

Open Preferences > Performance and click **Use low-lag preset**, then Apply.
This enables a 640 px playback proxy, automatic preview reduction, frame dropping,
and the performance overlay, with prefetch limited to one future frame.

Automatic preview reduction is enabled by default. When a frame takes longer than
125% of the timeline frame budget, preview width decreases by 25% at most once
every two seconds, down to 320 px. Quality stays at that level during the current
playback run. Pausing restores the normal Viewer preview width; exports retain
their configured resolution. Disable the option for fixed preview quality.

The overlay reports actual displayed FPS, dimensions, and cache memory usage.
Heavy graphs can still render below the timeline frame rate at minimum preview
size; bypass expensive effects while editing if needed. Frame dropping keeps the
preview updating but cannot make an expensive effect render in real time.

The renderer now publishes completed playback frames even when another request
is waiting. Scrubbing still keeps only the latest requested result. Background
prefetch is skipped when the foreground render already exceeds its frame budget.
Audio look-ahead uses ready cached frames and never runs video effects on the UI
thread. Uncached audio is not rendered synchronously to fill gaps, so heavily
overloaded graphs may still have audio interruptions.

The frame-cache budget now includes arrays inside audio/video payloads, preventing
these entries from silently bypassing its memory limit. Cache accounting is
conservative when several entries reference the same buffers.

Hover over property labels or controls for descriptions, numeric ranges, and
keyframe help. Preferences and Project Settings controls and labels also provide
hover help, including performance tradeoffs.
