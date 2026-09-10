"""Tests for reusable custom (subgraph) nodes."""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from app_io.node_loader import NodeLoader
from core.custom_node_store import CustomNodeStore, global_custom_node_store
from core.history import HistoryStack
from core.nodes.base import NodeSocketType
from core.nodes.color_effects import ExposureContrastNode
from core.nodes.custom_nodes import (CUSTOM_NODE_CATEGORY, PORT_SLOT,
                                     SUBGRAPH_INPUT_TYPE, SUBGRAPH_OUTPUT_TYPE,
                                     CustomNode, CustomNodeDefinition,
                                     CustomPort, SubgraphInputNode,
                                     SubgraphOutputNode,
                                     definition_from_project,
                                     make_custom_node_class,
                                     sanitize_port_name, unique_port_name)
from core.nodes.filter_effects import GaussianBlurNode
from core.nodes.generator_nodes import SolidColorNode
from core.nodes.registry import global_node_registry
from core.nodes.viewer import ViewerNode
from core.project import Project
from PyQt6.QtCore import QPointF


class FakeView:
    """Minimal stand-in for ``NodeGraphView`` (no Qt widgets needed)."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.history = HistoryStack(project)
        self.node_items: dict[str, object] = {}
        self.scene = types.SimpleNamespace(clearSelection=lambda: None)

    def view_center_scene_pos(self) -> QPointF:
        return QPointF(0.0, 0.0)


class CustomNodeTestCase(unittest.TestCase):
    """Shared setup: isolated store + registered built-ins."""

    def setUp(self) -> None:
        NodeLoader.load_defaults()
        self._original_path = global_custom_node_store._path
        self._tmp_dir = Path(tempfile.mkdtemp())
        global_custom_node_store._path = self._tmp_dir / "custom_nodes.json"
        global_custom_node_store.load()

    def tearDown(self) -> None:
        # Drop any types this test registered so other tests start clean.
        for name in global_custom_node_store.names():
            global_custom_node_store.remove(name, persist=False)
        for name in list(global_node_registry.get_nodes_in_category("Custom")):
            global_node_registry.unregister("Custom", name)
        global_custom_node_store._path = self._original_path

    # -- helpers -----------------------------------------------------------

    def _make_chain(self) -> tuple[Project, FakeView]:
        project = Project("Host")
        project.add_node(SolidColorNode(), node_id="s1")
        project.add_node(ExposureContrastNode(), node_id="e1")
        project.add_node(GaussianBlurNode(), node_id="b1")
        project.add_node(ViewerNode(), node_id="v1")
        self.assertTrue(project.connect_nodes("s1", "frame", "e1", "frame"))
        self.assertTrue(project.connect_nodes("e1", "frame", "b1", "frame"))
        self.assertTrue(project.connect_nodes("b1", "frame", "v1", "frame"))
        project.set_preview_width_override(64)
        return project, FakeView(project)


class DefinitionTests(CustomNodeTestCase):
    """Definition model + project snapshotting."""

    def test_definition_round_trips_through_dict(self) -> None:
        definition = CustomNodeDefinition(
            name="Test",
            description="desc",
            color=(10, 20, 30),
            inputs=[CustomPort("A", NodeSocketType.Number, "tin")],
            outputs=[CustomPort("B", NodeSocketType.Frame, "tout")],
            nodes={"tin": {"node_type": SUBGRAPH_INPUT_TYPE, "socket_type": "Number"}},
            connections=[
                {
                    "output_node_id": "tin",
                    "output_slot": PORT_SLOT,
                    "input_node_id": "tout",
                    "input_slot": PORT_SLOT,
                }
            ],
        )
        restored = CustomNodeDefinition.from_dict(definition.to_dict())
        self.assertEqual(restored.name, "Test")
        self.assertEqual(restored.color, (10, 20, 30))
        self.assertEqual(restored.inputs[0].socket_type, NodeSocketType.Number)
        self.assertEqual(restored.outputs[0].terminal_id, "tout")
        self.assertEqual(len(restored.connections), 1)

    def test_definition_from_project_detects_terminal_ports(self) -> None:
        project = Project("Scratch")
        project.add_node(SubgraphInputNode("Source"), node_id="in1")
        project.add_node(ExposureContrastNode(), node_id="ex")
        project.add_node(SubgraphOutputNode("Out"), node_id="out1")
        project.connect_nodes("in1", PORT_SLOT, "ex", "frame")
        project.connect_nodes("ex", "frame", "out1", PORT_SLOT)

        definition = definition_from_project(project, "Derived")
        self.assertEqual([p.name for p in definition.inputs], ["Source"])
        self.assertEqual([p.name for p in definition.outputs], ["Out"])
        self.assertEqual(definition.inputs[0].terminal_id, "in1")

    def test_port_name_helpers(self) -> None:
        self.assertEqual(sanitize_port_name("Exposure & Contrast"), "Exposure Contrast")
        self.assertEqual(sanitize_port_name("   "), "Port")
        self.assertEqual(unique_port_name("A", {"A", "A 2"}), "A 3")

    def test_preview_width_override_forces_resolution(self) -> None:
        project = Project("Res")
        project.add_node(SolidColorNode(), node_id="s")
        project.set_preview_width_override(32)
        result = project.evaluate_node("s", 0, "frame")
        self.assertEqual(result.shape, (18, 32, 3))
        project.set_preview_width_override(None)
        project.clear_cache()
        full = project.evaluate_node("s", 0, "frame")
        self.assertNotEqual(full.shape[1], 32)


class EvaluationTests(CustomNodeTestCase):
    """Embedded subgraph evaluation."""

    def _register(self, definition: CustomNodeDefinition) -> None:
        global_custom_node_store.upsert(definition)

    def test_custom_node_evaluates_embedded_graph(self) -> None:
        scratch = Project("Scratch")
        scratch.add_node(SubgraphInputNode("In"), node_id="in1")
        scratch.add_node(ExposureContrastNode(), node_id="ex")
        scratch.add_node(SubgraphOutputNode("Out"), node_id="out1")
        scratch.connect_nodes("in1", PORT_SLOT, "ex", "frame")
        scratch.connect_nodes("ex", "frame", "out1", PORT_SLOT)
        definition = definition_from_project(scratch, "Eval Custom")
        self._register(definition)

        project = Project("Host")
        project.add_node(SolidColorNode(), node_id="s1")
        project.add_node(ViewerNode(), node_id="v1")
        node = global_node_registry.create_node("Eval Custom", category=CUSTOM_NODE_CATEGORY)
        self.assertIsInstance(node, CustomNode)
        project.add_node(node, node_id="c1")
        self.assertTrue(project.connect_nodes("s1", "frame", "c1", "In"))
        self.assertTrue(project.connect_nodes("c1", "Out", "v1", "frame"))

        project.set_preview_width_override(64)
        result = project.evaluate_node("v1", 0, "frame")
        self.assertIsNotNone(result)
        self.assertEqual(result.shape, (36, 64, 3))

    def test_project_document_keeps_embedded_definition(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import collapse_to_custom_node

        custom_id = collapse_to_custom_node(
            view, ["e1", "b1"], name="Portable Custom"
        )
        self.assertIsNotNone(custom_id)

        document = project.to_dict()

        # Simulate a machine that has never seen this definition.
        global_custom_node_store.remove("Portable Custom", persist=False)

        reloaded = Project.from_dict(document)
        self.assertIn(custom_id, reloaded.nodes)
        node = reloaded.nodes[custom_id]
        self.assertIsInstance(node, CustomNode)
        self.assertEqual(node.definition_name, "Portable Custom")
        reloaded.set_preview_width_override(64)
        result = reloaded.evaluate_node("v1", 0, "frame")
        self.assertEqual(result.shape, (36, 64, 3))


class CollapseExpandTests(CustomNodeTestCase):
    """Collapse selection -> chip, expand chip -> nodes."""

    def test_collapse_builds_ports_and_rewires(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import collapse_to_custom_node

        custom_id = collapse_to_custom_node(
            view, ["e1", "b1"], name="Glow", description="demo"
        )
        self.assertIsNotNone(custom_id)
        self.assertNotIn("e1", project.nodes)
        self.assertNotIn("b1", project.nodes)

        node = project.nodes[custom_id]
        self.assertEqual(list(node.inputs), ["Exposure Contrast"])
        self.assertEqual(list(node.outputs), ["Gaussian Blur"])

        conns = {
            (c.output_node_id, c.output_slot, c.input_node_id, c.input_slot)
            for c in project.connections
        }
        self.assertIn(("s1", "frame", custom_id, "Exposure Contrast"), conns)
        self.assertIn((custom_id, "Gaussian Blur", "v1", "frame"), conns)

        result = project.evaluate_node("v1", 0, "frame")
        self.assertEqual(result.shape, (36, 64, 3))

    def test_collapse_is_a_single_undo_step(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import collapse_to_custom_node

        custom_id = collapse_to_custom_node(view, ["e1", "b1"], name="Undo Custom")
        self.assertIsNotNone(custom_id)

        self.assertTrue(view.history.undo())
        self.assertIn("e1", project.nodes)
        self.assertIn("b1", project.nodes)
        self.assertNotIn(custom_id, project.nodes)

        self.assertTrue(view.history.redo())
        self.assertIn(custom_id, project.nodes)
        self.assertNotIn("e1", project.nodes)
        # Recreated instance still evaluates (snapshot restored the definition).
        result = project.evaluate_node("v1", 0, "frame")
        self.assertEqual(result.shape, (36, 64, 3))

    def test_expand_restores_nodes_and_wiring(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import (collapse_to_custom_node,
                                                   expand_custom_node)

        custom_id = collapse_to_custom_node(view, ["e1", "b1"], name="Expand Me")
        self.assertIsNotNone(custom_id)

        self.assertTrue(expand_custom_node(view, custom_id))
        self.assertNotIn(custom_id, project.nodes)
        restored = [
            node_id
            for node_id, node in project.nodes.items()
            if node.node_type in ("Exposure & Contrast", "Gaussian Blur")
        ]
        self.assertEqual(len(restored), 2)

        result = project.evaluate_node("v1", 0, "frame")
        self.assertEqual(result.shape, (36, 64, 3))

    def test_viewer_links_become_exposed_outputs(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import collapse_to_custom_node

        # Selecting the source + viewer: the viewer is not collapsible, so the
        # wire into it becomes an output port.
        custom_id = collapse_to_custom_node(view, ["s1", "v1"], name="With Viewer")
        self.assertIsNotNone(custom_id)
        node = project.nodes[custom_id]
        self.assertIn("s1", node.definition.nodes)
        self.assertNotIn("v1", node.definition.nodes)


class EditPropagationTests(CustomNodeTestCase):
    """Editing a definition updates existing instances."""

    def test_apply_definition_updates_instance_ports(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import (apply_definition_to_project,
                                                   collapse_to_custom_node)

        custom_id = collapse_to_custom_node(view, ["e1", "b1"], name="Editable")
        self.assertIsNotNone(custom_id)
        node = project.nodes[custom_id]
        original_inputs = list(node.inputs)

        definition = node.definition.copy()
        definition.inputs = []
        definition.outputs = []
        apply_definition_to_project(view, definition, previous_name="Editable")

        node = project.nodes[custom_id]
        self.assertEqual(list(node.inputs), [])
        self.assertEqual(list(node.outputs), [])
        self.assertNotEqual(original_inputs, list(node.inputs))

    def test_store_persists_and_registers_definitions(self) -> None:
        store = CustomNodeStore(path=self._tmp_dir / "store.json")
        definition = CustomNodeDefinition(
            name="Stored Custom",
            description="persisted",
            nodes={"a": {"node_type": "Solid Color", "node_category": "Generators"}},
        )
        store.upsert(definition)
        self.assertTrue(store.path.is_file())

        fresh = CustomNodeStore(path=store.path)
        fresh.load()
        loaded = fresh.get("Stored Custom")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.description, "persisted")
        self.assertIn("Stored Custom", global_node_registry.get_nodes_in_category("Custom"))

    def test_instance_duplication_preserves_definition(self) -> None:
        project, view = self._make_chain()
        from ui.node_graph.custom_node_ops import collapse_to_custom_node

        custom_id = collapse_to_custom_node(view, ["e1", "b1"], name="Duplicate Me")
        source = project.nodes[custom_id]
        snapshot = source.snapshot_data()
        self.assertIn("custom_definition", snapshot)

        clone = make_custom_node_class(
            CustomNodeDefinition.from_dict(snapshot["custom_definition"])
        )()
        clone.restore_snapshot_data(snapshot)
        self.assertEqual(
            list(clone.inputs),
            list(source.inputs),
        )
        self.assertEqual(
            list(clone.definition.nodes),
            list(source.definition.nodes),
        )


if __name__ == "__main__":
    unittest.main()
