"""Professional workflow knowledge: concepts first, registry second.

The assistant must not invent a graph by wiring whatever node names happen to
look plausible. Real compositing work is done a certain way, and this module
records that knowledge in a form that is independent of Aphelion's node names.

The split is deliberate and is the core design rule of the module:

* A :class:`WorkflowRecipe` describes **how professionals solve a problem** —
  the ordered conceptual stages ("track the surface", "warp the replacement
  media", "composite"), with no Aphelion node names anywhere.
* :func:`resolve` maps each stage onto the **live node registry** by searching
  real node metadata (category, description, ports) and ranking the results.

External research is explicitly advisory: Aphelion's registry is the only
authority on what can actually be built. If a stage has no matching node, the
stage is reported as *unsupported* rather than being filled with an invention,
so the agent can tell the user the capability does not exist.

Everything here is offline. No network access is required or attempted, so the
agent keeps working with no connectivity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Words that carry no discriminating power when matching a request.
_STOPWORDS: frozenset[str] = frozenset(
    """
    a an the this that these those it its is are was were be been being do does
    did doing have has had and or but if then than so to of in on at for with
    from into onto over under about as by please can could would should i me my
    we you your make made making add added create created put set get give
    want need like more most very some any all just also new
    """.split()
)


@dataclass(frozen=True)
class WorkflowStage:
    """One conceptual step of a professional workflow.

    The stage deliberately says nothing about which Aphelion node implements
    it. :func:`resolve` performs that translation against the live registry.
    """

    key: str
    title: str
    #: The professional concept, e.g. ``"planar tracking"``. Shown to the user
    #: because it explains *why* the stage exists.
    concept: str
    #: Registry search phrase used to find candidate nodes for this stage.
    capability: str
    #: What this stage contributes to the finished result.
    purpose: str
    optional: bool = False
    #: Registry categories that are strongly preferred for this stage.
    prefer_categories: tuple[str, ...] = ()
    #: Substrings that make a node name a better fit for this stage.
    prefer_keywords: tuple[str, ...] = ()
    #: Substrings that make a node name a *worse* fit. This is how a planar
    #: tracking stage avoids being satisfied by a point tracker: it excludes
    #: the concept, not a specific product's node.
    avoid_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowRecipe:
    """A recognized professional workflow, independent of node names."""

    key: str
    title: str
    #: Lowercase phrases that identify this workflow in a user request.
    aliases: tuple[str, ...]
    summary: str
    stages: tuple[WorkflowStage, ...]
    #: User-facing explanation of why this approach is the professional one.
    rationale: str
    #: Category of request: ``graph`` builds nodes, ``color`` grades, etc.
    kind: str = "graph"
    #: What a professional would research to refine this workflow. Advisory
    #: only; the registry still decides what is implementable.
    research_hint: str = ""


@dataclass(frozen=True)
class StageMatch:
    """A workflow stage resolved against the live registry."""

    stage: WorkflowStage
    #: Ranked real node types that can satisfy the stage (best first).
    node_types: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return bool(self.node_types)

    @property
    def primary(self) -> str:
        return self.node_types[0] if self.node_types else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.key,
            "title": self.stage.title,
            "concept": self.stage.concept,
            "purpose": self.stage.purpose,
            "optional": self.stage.optional,
            "node_types": list(self.node_types),
            "supported": self.supported,
            "primary": self.primary,
        }


@dataclass(frozen=True)
class WorkflowPlan:
    """An ordered workflow mapped onto nodes that actually exist."""

    recipe: WorkflowRecipe
    matches: tuple[StageMatch, ...]
    score: int = 0
    #: Set when the request matched but no workflow was confident enough.
    loose: bool = False

    @property
    def unsupported(self) -> tuple[StageMatch, ...]:
        """Required stages the registry cannot satisfy."""
        return tuple(
            match for match in self.matches
            if not match.supported and not match.stage.optional
        )

    @property
    def required_nodes(self) -> tuple[str, ...]:
        """Distinct node types the required stages resolved to (build order)."""
        seen: list[str] = []
        for match in self.matches:
            if match.supported and match.primary not in seen:
                seen.append(match.primary)
        return tuple(seen)

    def stage_order(self) -> tuple[str, ...]:
        return tuple(match.stage.key for match in self.matches)

    def to_dict(self, *, detail: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "workflow": self.recipe.key,
            "title": self.recipe.title,
            "summary": self.recipe.summary,
            "rationale": self.recipe.rationale,
            "kind": self.recipe.kind,
            "because": self.recipe.rationale,
            "planned_node_types": list(self.required_nodes),
            "unsupported_stages": [m.stage.key for m in self.unsupported],
            "note": (
                "Node types come from Aphelion's live registry and are the only "
                "implementations of these concepts that exist. Do not substitute "
                "a node that is not in this list."
            ),
        }
        if detail:
            payload["stages"] = [match.to_dict() for match in self.matches]
        if self.recipe.research_hint:
            payload["research_hint"] = self.recipe.research_hint
        return payload

    def describe(self) -> str:
        """A compact checklist the model can follow while building."""
        lines = [f"{self.recipe.title}: {self.recipe.summary}"]
        for index, match in enumerate(self.matches, 1):
            if match.supported:
                options = ", ".join(match.node_types)
                lines.append(
                    f"{index}. {match.stage.title} ({match.stage.concept}) "
                    f"-> use one of: {options}"
                )
            else:
                lines.append(
                    f"{index}. {match.stage.title} ({match.stage.concept}) "
                    "-> NO NODE EXISTS in Aphelion"
                )
        if self.unsupported:
            lines.append(
                "Aphelion cannot implement every stage of this workflow; say so "
                "instead of inventing a node."
            )
        return "\n".join(lines)


# ======================================================================
# The recipes
# ======================================================================

#: The workflow vocabulary. Stage concepts are professional practice; the
#: capability strings are what gets matched against the registry.
RECIPES: tuple[WorkflowRecipe, ...] = (
    WorkflowRecipe(
        key="cinematic_grade",
        title="Cinematic grade",
        aliases=(
            "cinematic", "film look", "filmic", "movie look", "color grade",
            "colour grade", "grading", "grade the shot", "grade this", "teal and orange",
            "moody look", "moodier", "flat log", "look more like film",
        ),
        summary=(
            "Ordered grading stages: exposure and contrast first, then colour "
            "balance, then saturation, with an optional look on top."
        ),
        rationale=(
            "Grading works as an ordered chain — contrast and exposure decide the "
            "tonal range, balance and saturation then shape the colour — so the "
            "stages stay separately adjustable instead of being piled into one effect."
        ),
        kind="color",
        research_hint=(
            "Conventional node-compositor grading chains (primary correction, "
            "balance, saturation, optional film emulation)."
        ),
        stages=(
            WorkflowStage(
                key="tone",
                title="Set exposure and contrast",
                concept="primary tonal correction",
                capability="exposure contrast levels tone black point",
                purpose="Places the shot's tonal range before any colour decisions.",
                prefer_categories=("Color",),
                prefer_keywords=("exposure", "levels", "contrast", "shadows"),
            ),
            WorkflowStage(
                key="balance",
                title="Balance the colour",
                concept="colour balance / white balance",
                capability="colour balance white balance temperature tint",
                purpose="Neutralises or deliberately shifts the colour cast.",
                prefer_categories=("Color",),
                prefer_keywords=("balance", "white", "temperature"),
            ),
            WorkflowStage(
                key="saturation",
                title="Shape saturation",
                concept="saturation / vibrance control",
                capability="saturation vibrance hue intensity",
                purpose="Controls how vivid the result reads without clipping.",
                prefer_categories=("Color",),
                prefer_keywords=("saturation", "vibrance", "hue"),
            ),
            WorkflowStage(
                key="look",
                title="Add the look (optional)",
                concept="film emulation / optical character",
                capability="film grain glow bloom halation vignette",
                purpose="Adds the optical character that sells the cinematic look.",
                optional=True,
                prefer_categories=("Effects", "Creative", "Filter"),
                prefer_keywords=("grain", "glow", "bloom", "vignette"),
            ),
        ),
    ),
    WorkflowRecipe(
        key="planar_attach",
        title="Attach a graphic to a flat moving surface",
        aliases=(
            "onto the wall", "on the wall", "onto this wall", "on this wall",
            "onto the floor", "on the floor", "floor graphic", "wall graphic",
            "onto the side of", "planar surface", "stays there while the camera moves",
            "put this graphic onto", "put a graphic onto", "attach this graphic",
            "stick this graphic", "graphic onto", "stays on the",
        ),
        summary=(
            "Planar/surface tracking drives a perspective warp so the graphic "
            "travels with the surface instead of merely following X and Y."
        ),
        rationale=(
            "The surface changes perspective as the camera moves, so a planar or "
            "surface track feeding a perspective (corner-pin) warp is used. A "
            "position-only point tracker would slide off as the perspective changes."
        ),
        research_hint=(
            "Planar tracking plus corner-pin replacement is the standard "
            "screen/wall replacement chain in node compositors."
        ),
        stages=(
            WorkflowStage(
                key="track",
                title="Track the surface",
                concept="planar / surface tracking",
                capability="planar surface track homography perspective recovery",
                purpose="Recovers the surface's motion and perspective over time.",
                prefer_categories=("Tracking",),
                prefer_keywords=("planar", "surface", "homography", "wall", "floor"),
                avoid_keywords=("point", "deep", "face", "shape", "motion path"),
            ),
            WorkflowStage(
                key="warp",
                title="Warp the replacement media",
                concept="perspective transform / corner pin",
                capability="corner pin perspective warp transform",
                purpose="Places the graphic onto the tracked plane with matching perspective.",
                prefer_categories=("Transform",),
                prefer_keywords=("corner", "perspective"),
                avoid_keywords=("swirl", "polar", "spherical", "3d"),
            ),
            WorkflowStage(
                key="occlusion",
                title="Handle occlusion (optional)",
                concept="foreground matte / roto",
                capability="mask roto foreground occlusion shape",
                purpose="Lets foreground objects pass in front of the attached graphic.",
                optional=True,
                prefer_categories=("Roto", "Keying"),
                prefer_keywords=("roto", "mask"),
            ),
            WorkflowStage(
                key="match",
                title="Match the appearance (optional)",
                concept="lighting and colour integration",
                capability="light wrap colour match grade integration",
                purpose="Blends the graphic's colour and lighting into the plate.",
                optional=True,
                prefer_categories=("Color", "Creative", "Compositing"),
                prefer_keywords=("light wrap", "match", "grade"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite the result",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Produces the final image combining plate and graphic.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge", "composite"),
                avoid_keywords=("under",),
            ),
        ),
    ),
    WorkflowRecipe(
        key="screen_replacement",
        title="Screen replacement",
        aliases=(
            "replace the screen", "screen replacement", "swap the screen",
            "phone screen", "screen content", "replace this screen",
            "monitor screen", "new screen",
        ),
        summary=(
            "Track the screen, warp the new content onto it, then composite over "
            "the original with optional occlusion."
        ),
        rationale=(
            "A screen is a flat surface that generally remains in shot, so it is "
            "tracked as a plane and the new content is corner-pinned onto it; "
            "tracking only position would not hold the perspective."
        ),
        research_hint="Planar track -> corner pin -> composite is the standard screen-swap chain.",
        stages=(
            WorkflowStage(
                key="track",
                title="Track the screen",
                concept="planar / surface tracking",
                capability="planar surface track homography perspective",
                purpose="Locks onto the screen's four corners over time.",
                prefer_categories=("Tracking",),
                prefer_keywords=("planar", "surface", "homography"),
                avoid_keywords=("point", "deep", "face", "shape"),
            ),
            WorkflowStage(
                key="source",
                title="Bring in the replacement content",
                concept="replacement source media",
                capability="image input source media still",
                purpose="Supplies the new screen content.",
                prefer_categories=("Input/Output",),
                prefer_keywords=("image", "video", "input"),
            ),
            WorkflowStage(
                key="warp",
                title="Corner-pin the content onto the screen",
                concept="perspective transform / corner pin",
                capability="corner pin perspective warp transform",
                purpose="Matches the content's perspective to the tracked screen.",
                prefer_categories=("Transform",),
                prefer_keywords=("corner", "perspective"),
                avoid_keywords=("swirl", "polar", "spherical"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite over the plate",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Puts the replacement content into the shot.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
                avoid_keywords=("under",),
            ),
        ),
    ),
    WorkflowRecipe(
        key="chroma_key",
        title="Green/blue screen key",
        aliases=(
            "green screen", "greenscreen", "chroma key", "chroma-key", "blue screen",
            "key out", "key the background", "keying",
        ),
        summary=(
            "Pull the matte, clean the edge and spill, then composite over a new "
            "background."
        ),
        rationale=(
            "A decent key is a matte stage followed by edge tidy-up and despill; "
            "skipping the clean-up stages is what makes keys look cut out."
        ),
        research_hint="Key -> matte edge/spill suppression -> composite is the standard chain.",
        stages=(
            WorkflowStage(
                key="key",
                title="Pull the matte",
                concept="chroma keying",
                capability="chroma key green screen matte extraction",
                purpose="Separates the subject from the coloured background.",
                prefer_categories=("Keying",),
                prefer_keywords=("chroma", "key"),
            ),
            WorkflowStage(
                key="edge",
                title="Clean the edge and spill (optional)",
                concept="matte edge refinement / despill",
                capability="despill matte edge clean refinement",
                purpose="Removes colour spill and hard edges.",
                optional=True,
                prefer_categories=("Keying",),
                prefer_keywords=("despill", "spill", "edge", "matte"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite over the background",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Combines the keyed subject with the new background.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
                avoid_keywords=("under",),
            ),
        ),
    ),
    WorkflowRecipe(
        key="stabilise",
        title="Camera stabilisation",
        aliases=(
            "remove camera shake", "camera shake", "shaky footage", "shaky",
            "stabilise", "stabilize", "stabilisation", "stabilization",
            "smooth the camera", "smooth the motion", "handheld",
        ),
        summary="Analyse the camera motion, apply the stabilising transform, then reframe the border.",
        rationale=(
            "Stabilisation is a motion-analysis stage feeding a correcting "
            "transform, usually followed by a small reframe to remove the "
            "newly exposed border."
        ),
        research_hint="Motion analysis -> stabilising transform -> border reframe.",
        stages=(
            WorkflowStage(
                key="analyse",
                title="Analyse and correct the camera motion",
                concept="camera motion analysis / stabilisation",
                capability="stabilizer stabilize steady shake smooth camera motion",
                purpose="Measures the camera move and counteracts it.",
                prefer_categories=("Tracking",),
                prefer_keywords=("stabil", "steady", "smooth"),
                # A tracker measures motion but does not counteract it, so this
                # stage must not be satisfied by one.
                avoid_keywords=("depth", "noise", "random", "tracker"),
            ),
            WorkflowStage(
                key="reframe",
                title="Reframe the border (optional)",
                concept="border reframing",
                capability="crop transform scale border reframe",
                purpose="Hides the edge the correction exposes.",
                optional=True,
                prefer_categories=("Transform",),
                prefer_keywords=("transform", "crop", "scale"),
            ),
        ),
    ),
    WorkflowRecipe(
        key="object_removal",
        title="Object removal",
        aliases=(
            "remove the object", "remove this object", "object removal", "paint out",
            "clean the plate", "clean up the shot", "get rid of", "remove the person",
            "remove the logo", "take out the",
        ),
        summary="Track the object, source clean plate material, then patch the region back in.",
        rationale=(
            "Removal needs a tracked region plus replacement material from "
            "somewhere else in the shot; the patch stage is what actually hides "
            "the object."
        ),
        research_hint="Tracked region + clean plate/patch is the standard removal approach.",
        stages=(
            WorkflowStage(
                key="track",
                title="Track the region to remove",
                concept="object/region tracking",
                capability="object track region mask follow",
                purpose="Keeps the repair locked to the object as it moves.",
                prefer_categories=("Tracking",),
                prefer_keywords=("object", "mask", "track"),
                avoid_keywords=("depth",),
            ),
            WorkflowStage(
                key="plate",
                title="Source clean material",
                concept="clean plate / patch",
                capability="clean plate patch source region",
                purpose="Provides pixels to paint over the object.",
                prefer_categories=("Keying", "Compositing", "Transform"),
                prefer_keywords=("clean", "plate", "patch", "offset", "merge"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite the repair (optional)",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Blends the repair into the plate.",
                optional=True,
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
            ),
        ),
    ),
    WorkflowRecipe(
        key="tracked_blur",
        title="Tracked blur / censor",
        aliases=(
            "face blur", "blur the face", "blur his face", "blur her face",
            "censor", "anonymise", "anonymize", "blur the licence plate",
            "blur the license plate", "blur the plate", "hide the face",
            "tracked blur", "blur this region",
        ),
        summary="Track the region, build a matte for it, blur the footage, then apply the matte.",
        rationale=(
            "The blur must follow the subject, so a tracked matte limits the "
            "blur to that region only; blurring the whole frame would be wrong."
        ),
        research_hint="Tracked matte limiting a blur is the standard censor approach.",
        stages=(
            WorkflowStage(
                key="track",
                title="Track the subject",
                concept="face/region tracking",
                capability="face tracker mask region track region of interest",
                purpose="Follows the subject through the shot.",
                prefer_categories=("Tracking",),
                prefer_keywords=("face", "mask", "shape", "object"),
                avoid_keywords=("depth", "planar", "homography"),
            ),
            WorkflowStage(
                key="matte",
                title="Build the matte (optional)",
                concept="matte from the track",
                capability="mask channel matte combine invert",
                purpose="Turns the track into a usable matte.",
                optional=True,
                prefer_categories=("Keying", "Roto"),
                prefer_keywords=("mask", "matte", "combine"),
            ),
            WorkflowStage(
                key="blur",
                title="Blur the footage",
                concept="blur / pixelate",
                capability="gaussian blur pixelate soften",
                purpose="Destroys the identifying detail.",
                prefer_categories=("Filter", "Effects", "VFX"),
                prefer_keywords=("blur", "pixelate"),
            ),
        ),
    ),
    WorkflowRecipe(
        key="picture_in_picture",
        title="Picture in picture",
        aliases=(
            "picture in picture", "picture-in-picture", "pip", "inset video",
            "corner video", "overlay this video", "small video on top",
            "video in the corner",
        ),
        summary="Bring in the second source, scale and position it, then composite it over.",
        rationale=(
            "A picture-in-picture insert is a separate source placed by a "
            "transform and combined with the main plate."
        ),
        stages=(
            WorkflowStage(
                key="source",
                title="Bring in the inset source",
                concept="secondary source media",
                capability="video input image input source media",
                purpose="Supplies the inset footage.",
                prefer_categories=("Input/Output",),
                prefer_keywords=("video input", "image input", "input"),
            ),
            WorkflowStage(
                key="place",
                title="Scale and position the inset",
                concept="2D transformation",
                capability="transform scale position translate 2d",
                purpose="Places the inset where it belongs.",
                prefer_categories=("Transform",),
                prefer_keywords=("transform", "corner", "crop"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite it over the shot",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Combines the inset with the main image.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
                avoid_keywords=("under",),
            ),
        ),
    ),
    WorkflowRecipe(
        key="background_replacement",
        title="Background replacement",
        aliases=(
            "replace the background", "background replacement", "change the background",
            "remove the background", "new background", "different background",
            "swap the background",
        ),
        summary="Isolate the subject, bring in the new background, then composite them together.",
        rationale=(
            "The subject has to be isolated before a new background is added, so "
            "the mask stage comes first and the composite stage last."
        ),
        research_hint="Subject isolation -> new background -> composite.",
        stages=(
            WorkflowStage(
                key="isolate",
                title="Isolate the subject",
                concept="subject matte",
                capability="mask matte segmentation isolate subject",
                purpose="Separates the subject from the existing background.",
                prefer_categories=("Keying", "Tracking", "Roto"),
                prefer_keywords=("mask", "segmentation", "matte", "chroma"),
            ),
            WorkflowStage(
                key="source",
                title="Bring in the new background",
                concept="replacement background media",
                capability="image input video input background source",
                purpose="Supplies the new background.",
                prefer_categories=("Input/Output", "Generator"),
                prefer_keywords=("input", "gradient", "solid"),
            ),
            WorkflowStage(
                key="composite",
                title="Composite subject over background",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Produces the final combined frame.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
                avoid_keywords=("under",),
            ),
        ),
    ),
    WorkflowRecipe(
        key="motion_graphics_attach",
        title="Attach motion graphics to a moving subject",
        aliases=(
            "attach the text", "attach this text", "attach to the moving",
            "graphic follow", "follow the object", "follow his", "follow her",
            "track graphics onto", "stick this to", "stick to the",
            "label follows", "text follows", "graphic tracks",
        ),
        summary="Track the subject, place the graphic with a transform, then composite it on top.",
        rationale=(
            "The graphic needs the subject's motion, so a track drives a "
            "transform and the result is composited over the plate."
        ),
        research_hint="Track -> transform -> composite for attached graphics.",
        stages=(
            WorkflowStage(
                key="track",
                title="Track the subject",
                concept="motion/object tracking",
                capability="motion object point tracking follow",
                purpose="Drives the graphic with the subject's motion.",
                prefer_categories=("Tracking",),
                prefer_keywords=("tracker", "match move", "object", "point"),
                avoid_keywords=("depth", "stabil"),
            ),
            WorkflowStage(
                key="place",
                title="Place the graphic",
                concept="2D transformation",
                capability="transform scale position translate 2d",
                purpose="Positions and scales the graphic on the subject.",
                prefer_categories=("Transform",),
                prefer_keywords=("transform",),
            ),
            WorkflowStage(
                key="composite",
                title="Composite the graphic",
                concept="compositing / merge",
                capability="composite over merge layer",
                purpose="Lays the graphic over the footage.",
                prefer_categories=("Compositing",),
                prefer_keywords=("over", "merge"),
                avoid_keywords=("under",),
            ),
        ),
    ),
)

_RECIPES_BY_KEY: dict[str, WorkflowRecipe] = {recipe.key: recipe for recipe in RECIPES}


# ======================================================================
# Matching
# ======================================================================


def recipes() -> tuple[WorkflowRecipe, ...]:
    """Every recipe, in display order."""
    return RECIPES


def recipe(key: str) -> WorkflowRecipe | None:
    """Look up a recipe by key."""
    return _RECIPES_BY_KEY.get((key or "").strip().lower())


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().replace("_", " ").split())


def _tokens(text: str) -> list[str]:
    cleaned = "".join(
        character if character.isalnum() or character in " -" else " "
        for character in _normalise(text)
    )
    return [token for token in cleaned.split() if token and token not in _STOPWORDS]


#: Node type names, longest first, so overlaps resolve predictably.
_NODE_NAMES: tuple[str, ...] | None = None


def known_node_names() -> tuple[str, ...]:
    """Every registered node type name, longest first."""
    global _NODE_NAMES
    if _NODE_NAMES is None:
        try:
            names = {entry.type for entry in _catalog(None).entries().values()}
        except Exception:  # noqa: BLE001 - matching degrades, it must not fail
            names = set()
        _NODE_NAMES = tuple(sorted(names, key=len, reverse=True))
    return _NODE_NAMES


def reset_node_names() -> None:
    """Drop the cached node-name list (tests, plugin reloads)."""
    global _NODE_NAMES
    _NODE_NAMES = None


def _node_name_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of ``text`` that are registered node names."""
    spans: list[tuple[int, int]] = []
    for name in known_node_names():
        lowered = name.lower()
        start = text.find(lowered)
        while start != -1:
            spans.append((start, start + len(lowered)))
            start = text.find(lowered, start + 1)
    return spans


def _inside(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(span_start <= start and end <= span_end for span_start, span_end in spans)


def _matches_outside_node_names(text: str, alias: str, spans: list[tuple[int, int]]) -> bool:
    """Whether ``alias`` appears in ``text`` outside a node-name mention.

    This is what stops "add a Color Grading node" from being mistaken for a
    grading workflow request: the phrase only matched because it is part of a
    node type name, and mentioning a node is not the same as asking for the
    professional workflow that node might serve.
    """
    if not spans:
        return alias in text
    start = text.find(alias)
    while start != -1:
        end = start + len(alias)
        if not _inside(spans, start, end):
            return True
        start = text.find(alias, start + 1)
    return False


def score_recipe(text: str, candidate: WorkflowRecipe) -> int:
    """Score how strongly ``text`` asks for ``candidate``.

    Alias matches dominate because a phrase like "green screen" is a much
    stronger signal than a coincidental shared word. Alias occurrences that sit
    entirely inside a registered node type name are ignored, so naming a node
    never masquerades as naming a workflow.
    """
    normalised = _normalise(text)
    if not normalised:
        return 0
    words = set(_tokens(normalised))
    spans = _node_name_spans(normalised)
    score = 0
    for alias in candidate.aliases:
        alias = alias.strip().lower()
        if not alias:
            continue
        if _matches_outside_node_names(normalised, alias, spans):
            # Multi-word aliases are far more specific than single words.
            score += 6 + 2 * len(alias.split())
    for token in _tokens(candidate.title):
        if token in words:
            score += 2
    for stage in candidate.stages:
        for token in _tokens(stage.concept):
            if token in words:
                score += 1
    return score


def match_request(text: str, *, limit: int = 3) -> list[tuple[int, WorkflowRecipe]]:
    """Return ``(score, recipe)`` pairs for ``text``, best first."""
    scored = [
        (score, candidate)
        for candidate in RECIPES
        if (score := score_recipe(text, candidate)) > 0
    ]
    scored.sort(key=lambda item: (-item[0], item[1].key))
    return scored[:limit]


#: A request must score at least this much before the agent commits to a
#: named professional workflow.
CONFIDENCE_THRESHOLD: int = 6


def best_request(text: str) -> tuple[int, WorkflowRecipe] | None:
    """The single most likely workflow for ``text``, or ``None``."""
    matches = match_request(text, limit=1)
    return matches[0] if matches else None


# ======================================================================
# Registry mapping
# ======================================================================


def _catalog(catalog: Any | None) -> Any:
    if catalog is not None:
        return catalog
    # Imported lazily: the catalogue pulls in the node registry, which we do
    # not want to import for pure prompt construction.
    from ai.source.nodes import node_catalog

    return node_catalog()


def _rank_stage(stage: WorkflowStage, catalog: Any, *, per_stage: int) -> tuple[str, ...]:
    """Rank real node types for one stage. Never returns an invented name."""
    queries = [stage.capability, stage.title, stage.concept]
    seen: list[Any] = []
    for query in queries:
        for entry in catalog.search(query, limit=per_stage * 6):
            if entry not in seen:
                seen.append(entry)
        if len(seen) >= per_stage * 6:
            break

    scored: list[tuple[int, str]] = []
    for index, entry in enumerate(seen):
        name = str(getattr(entry, "type", ""))
        category = str(getattr(entry, "category", ""))
        if not name:
            continue
        score = 60 - index * 4
        preferred = [kw.lower() for kw in stage.prefer_keywords]
        avoided = [kw.lower() for kw in stage.avoid_keywords]
        lowered = name.lower()
        if stage.prefer_categories and category in stage.prefer_categories:
            score += 22
        for keyword in preferred:
            if keyword in lowered:
                score += 20
        for keyword in avoided:
            if keyword in lowered:
                score -= 45
        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda item: (-item[0], item[1]))
    ordered: list[str] = []
    for _score, name in scored:
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered[:per_stage])


def resolve(
    candidate: WorkflowRecipe,
    *,
    catalog: Any | None = None,
    per_stage: int = 3,
) -> WorkflowPlan:
    """Map ``candidate``'s conceptual stages onto real registered node types."""
    live = _catalog(catalog)
    matches = tuple(
        StageMatch(stage=stage, node_types=_rank_stage(stage, live, per_stage=per_stage))
        for stage in candidate.stages
    )
    return WorkflowPlan(recipe=candidate, matches=matches)


def resolve_request(
    text: str,
    *,
    catalog: Any | None = None,
    per_stage: int = 3,
    threshold: int = CONFIDENCE_THRESHOLD,
) -> WorkflowPlan | None:
    """Resolve the professional workflow a request is asking for.

    Returns ``None`` when no workflow is a confident match, in which case the
    request is a direct edit and needs no workflow research at all.
    """
    best = best_request(text)
    if best is None:
        return None
    score, candidate = best
    if score < threshold:
        return None
    plan = resolve(candidate, catalog=catalog, per_stage=per_stage)
    return WorkflowPlan(
        recipe=plan.recipe,
        matches=plan.matches,
        score=score,
        loose=score < threshold + 4,
    )


def is_workflow_request(text: str, *, threshold: int = CONFIDENCE_THRESHOLD) -> bool:
    """Whether ``text`` warrants the workflow-understanding stage."""
    best = best_request(text)
    return bool(best and best[0] >= threshold)


def vocabulary() -> list[dict[str, Any]]:
    """The workflow vocabulary, for the system prompt."""
    return [
        {
            "workflow": candidate.key,
            "title": candidate.title,
            "summary": candidate.summary,
            "stages": [stage.concept for stage in candidate.stages],
        }
        for candidate in RECIPES
    ]


__all__ = [
    "CONFIDENCE_THRESHOLD",
    "RECIPES",
    "StageMatch",
    "WorkflowPlan",
    "WorkflowRecipe",
    "WorkflowStage",
    "best_request",
    "is_workflow_request",
    "known_node_names",
    "match_request",
    "recipe",
    "recipes",
    "reset_node_names",
    "resolve",
    "resolve_request",
    "score_recipe",
    "vocabulary",
]
