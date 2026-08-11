from typing import Any

from PyQt6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from core.node import Node
from core.node_registry import global_node_registry
from core.events import ObserverEvent
from core.project import Project
from gui.node_context_menu import NodeContextMenu
from gui.theme import CONTEXT_MENU_STYLE


class NodeItem(QGraphicsRectItem):
    """Visual representation of a node in the graph with modern, compact styling"""

    SOCKET_SIZE = 10
    SOCKET_SPACING = 16
    CORNER_RADIUS = 6
    PADDING = 8

    def __init__(self, node: Node, node_id: str) -> None:
        # Make nodes larger to accommodate bigger text
        node.width = 160
        node.height = 100

        super().__init__(0, 0, node.width, node.height)
        self.node = node
        self.node_id = node_id
        self.graph_view = None  # Will be set by NodeGraphView

        self.setPos(node.x, node.y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresParentOpacity, True)
        self.setAcceptHoverEvents(True)

        r, g, b = node.node_color
        self.node_color = QColor(r, g, b, 230)
        self.base_color = QColor(r, g, b, 230)
        self.hover_color = QColor(r + 20, g + 20, b + 20, 240)

        self.setBrush(QBrush(self.node_color))
        self.setPen(QPen(QColor(255, 255, 255), 1.5))

        self.input_sockets: dict[str, QRect] = {}
        self.output_sockets: dict[str, QRect] = {}
        self._calculate_socket_positions()

        # Add drop shadow effect with lower quality for performance
        self.shadow = QGraphicsDropShadowEffect()
        self.shadow.setBlurRadius(8)
        self.shadow.setColor(QColor(0, 0, 0, 120))
        self.shadow.setOffset(1, 1)
        self.setGraphicsEffect(self.shadow)

        self.is_hovered = False
        self.is_moving = False
        self.last_pos = self.pos()

    def _calculate_socket_positions(self) -> None:
        """Calculate pixel positions of all sockets on this node"""
        socket_y = self.SOCKET_SPACING
        for input_name in self.node.inputs:
            self.input_sockets[input_name] = QRect(
                -self.SOCKET_SIZE - 3,
                socket_y - self.SOCKET_SIZE // 2,
                self.SOCKET_SIZE,
                self.SOCKET_SIZE,
            )
            socket_y += self.SOCKET_SPACING
            
        socket_y = self.SOCKET_SPACING
        for output_name in self.node.outputs:
            self.output_sockets[output_name] = QRect(
                self.node.width + 3,
                socket_y - self.SOCKET_SIZE // 2,
                self.SOCKET_SIZE,
                self.SOCKET_SIZE,
            )
            socket_y += self.SOCKET_SPACING

    def paint(
        self,
        painter: QPainter | None,
        option: QStyleOptionGraphicsItem | None,
        widget: QWidget | None,
    ) -> None:
        """Paint node with modern, compact design"""
        if painter is None:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()

        # Determine colors based on state
        if self.isSelected():
            body_color = QColor(0, 120, 215, 240)
            border_color = QColor(0, 150, 255, 255)
            border_width = 2
        else:
            body_color = self.hover_color if self.is_hovered else self.base_color
            border_color = QColor(180, 180, 180, 200)
            border_width = 1.5

        # Draw main body
        painter.setBrush(QBrush(body_color))
        painter.setPen(QPen(border_color, border_width))
        painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        # Draw subtle top accent line
        accent_rect = QRect(
            int(rect.x()) + 1, int(rect.y()) + 1, int(rect.width()) - 2, 2
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 40)))
        painter.drawRect(accent_rect)

        # Draw node name with bigger font
        name_rect = QRect(
            int(rect.x()) + 4,
            int(rect.y()) + 6,
            int(rect.width()) - 8,
            int(rect.height()) - 12,
        )

        font = QFont("Segoe UI", 11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.node.name,
        )

        # Draw input sockets (black with blue center)
        painter.setBrush(QBrush(QColor(66, 135, 245)))
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        for input_name, rect in self.input_sockets.items():
            painter.drawEllipse(rect)

        # Draw output sockets (black with orange center)
        painter.setBrush(QBrush(QColor(245, 140, 70)))
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        for output_name, rect in self.output_sockets.items():
            painter.drawEllipse(rect)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """Handle mouse move with optimized updates"""
        if event is None:
            return

        self.is_moving = True
        super().mouseMoveEvent(event)

        # Only update node position if moved significantly
        new_pos = self.pos()
        if new_pos != self.last_pos:
            self.node.x = new_pos.x()
            self.node.y = new_pos.y()
            self.last_pos = new_pos

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """Handle mouse release"""
        if event is None:
            return

        self.is_moving = False
        super().mouseReleaseEvent(event)

        # Update position once on release
        self.node.x = self.pos().x()
        self.node.y = self.pos().y()

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """Handle mouse press - select node and show context menu on right click"""
        if event is None:
            return

        # Handle right-click
        if event.button() == Qt.MouseButton.RightButton:
            # Select this node if not already selected
            if not self.isSelected():
                self.setSelected(True)
            self.show_context_menu(event)
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton:
            # Handle Ctrl+Click for multi-select
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                # Toggle selection
                self.setSelected(not self.isSelected())
                event.accept()
            else:
                # Normal selection
                if not self.isSelected():
                    self.setSelected(True)
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def show_context_menu(self, event: QGraphicsSceneMouseEvent) -> None:
        """Show context menu for node operations"""
        menu = QMenu()
        menu.setStyleSheet(CONTEXT_MENU_STYLE)

        # Check if multiple nodes are selected
        selected_nodes = self.graph_view.scene.selectedItems() if self.graph_view else []
        is_multi_select = len(selected_nodes) > 1

        # Delete action
        delete_text = f"Delete {len(selected_nodes)} Nodes" if is_multi_select else "Delete Node"
        delete_action = menu.addAction(delete_text)
        delete_action.triggered.connect(self.delete_selected_nodes)

        # Duplicate action (only for single node)
        if not is_multi_select:
            duplicate_action = menu.addAction("Duplicate Node")
            duplicate_action.triggered.connect(self.duplicate_node)

        # Show menu at cursor
        global_pos = event.screenPos()
        menu.exec(global_pos)

    def delete_selected_nodes(self) -> None:
        """Delete selected nodes"""
        if self.graph_view:
            selected_items = self.graph_view.scene.selectedItems()
            for item in selected_items:
                if isinstance(item, NodeItem):
                    self.graph_view.delete_node(item.node_id)

    def delete_node(self) -> None:
        """Delete this node"""
        if self.graph_view:
            self.graph_view.delete_node(self.node_id)

    def duplicate_node(self) -> None:
        """Duplicate this node"""
        if self.graph_view:
            self.graph_view.duplicate_node(self.node_id, self.node.x + 20, self.node.y + 20)

    def hoverEnterEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """Handle hover enter"""
        self.is_hovered = True
        self.shadow.setBlurRadius(12)
        self.shadow.setColor(QColor(0, 120, 215, 160))
        self.update()

    def hoverLeaveEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """Handle hover leave"""
        self.is_hovered = False
        self.shadow.setBlurRadius(8)
        self.shadow.setColor(QColor(0, 0, 0, 120))
        self.update()

    def get_socket_position(self, socket_name: str, is_input: bool) -> QPointF:
        """Get the scene position of a socket"""
        if is_input:
            rect = self.input_sockets.get(socket_name)
        else:
            rect = self.output_sockets.get(socket_name)

        if rect:
            center = QPoint(rect.center().x(), rect.center().y())
            return self.mapToScene(center)
        return self.pos()


class NodeGraphView(QGraphicsView):
    """Node graph editor view with massive performance optimizations"""

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Maximum performance optimizations
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)
        self.setOptimizationFlags(
            QGraphicsView.OptimizationFlag.DontSavePainterState
            | QGraphicsView.OptimizationFlag.DontAdjustForAntialiasing
        )

        self.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        self.setDragMode(self.DragMode.ScrollHandDrag)

        # Performance settings
        self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.scene.setSceneRect(-10000, -10000, 20000, 20000)

        self.node_items: dict[str, NodeItem] = {}
        self.project.subscribe(self.on_project_changed)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        # Box selection
        self.selection_rect = None
        self.selection_start = None

        # Add existing nodes if any
        for node_id in self.project.nodes:
            self.add_node_to_view(node_id)

        # High-performance update timer
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(False)
        self.update_timer.timeout.connect(self.on_update_timer)
        self.update_timer.start(32)  # ~30fps for viewport updates

        # Initial zoom to fit
        QTimer.singleShot(100, self.fit_all_nodes)

    def fit_all_nodes(self) -> None:
        """Fit all nodes in the viewport"""
        if self.scene.items():
            # Calculate bounding rect of all nodes
            bounding_rect = self.scene.itemsBoundingRect()
            if bounding_rect.isValid():
                # Add padding around the nodes
                padding = 120
                padded_rect = bounding_rect.adjusted(-padding, -padding, padding, padding)
                
                # Fit the view with some margin
                self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
                
                # Don't zoom too far out
                current_scale = self.transform().m11()
                if current_scale < 0.3:
                    self.scale(0.3 / current_scale, 0.3 / current_scale)
        else:
            # Default zoom if no nodes
            self.scale(1.0, 1.0)

    def on_update_timer(self) -> None:
        """Optimized update timer"""
        self.viewport().update()

    def on_project_changed(self, event: ObserverEvent, data: Any) -> None:
        """Handle project events"""
        if event == ObserverEvent.NodeAdded:
            self.add_node_to_view(data)
            # Fit view when new node added
            QTimer.singleShot(50, self.fit_all_nodes)
        elif event == ObserverEvent.NodeRemoved:
            self.remove_node_from_view(data)

    def add_node_to_view(self, node_id: str) -> None:
        """Add a node item to the graph view"""
        if node_id in self.node_items:
            return

        node = self.project.nodes.get(node_id)
        if not node:
            return

        item = NodeItem(node, node_id)
        item.graph_view = self
        self.scene.addItem(item)
        self.node_items[node_id] = item

    def remove_node_from_view(self, node_id: str) -> None:
        """Remove a node item from the graph view"""
        if node_id in self.node_items:
            item = self.node_items[node_id]
            self.scene.removeItem(item)
            del self.node_items[node_id]

    def delete_node(self, node_id: str) -> None:
        """Delete a node from the project"""
        self.project.remove_node(node_id)

    def duplicate_node(self, node_id: str, offset_x: float = 20, offset_y: float = 20) -> None:
        """Duplicate a node at a new position"""
        node = self.project.nodes.get(node_id)
        if not node:
            return

        # Create a new node of the same type
        new_node = global_node_registry.create_node(node.node_type, category=node.node_category)
        if not new_node:
            return

        # Copy properties from original node
        for prop_name, prop in node.properties.items():
            if prop_name.startswith("_input_"):
                continue
            new_node.set_property(prop_name, prop.value)

        # Position offset
        new_node.x = node.x + offset_x
        new_node.y = node.y + offset_y

        # Add to project
        self.project.add_node(new_node)

    def show_context_menu(self, position: QPoint) -> None:
        """Show context menu for adding nodes on empty space"""
        scene_pos = self.mapToScene(position)
        menu = NodeContextMenu(self.project, scene_pos, self)
        menu.node_selected.connect(self.on_node_selected)
        menu.exec(self.mapToGlobal(position))

    def on_node_selected(self, name: str, category: str, position: QPointF) -> None:
        """Handle node selection from context menu"""
        node = global_node_registry.create_node(name, category=category)
        if node:
            node.x = position.x()
            node.y = position.y()
            _ = self.project.add_node(node)

    def mousePressEvent(self, event) -> None:
        """Handle mouse press for box selection"""
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if clicking on empty space (not on a node)
            item = self.itemAt(event.pos())
            if item is None or not isinstance(item, NodeItem):
                # Start box selection
                self.selection_start = event.pos()
                self.selection_rect = QRect(self.selection_start, self.selection_start)
                
                # Clear selection unless Ctrl is held
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.scene.clearSelection()
                event.accept()
                return

        super().mousePressEvent(event)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        """Handle mouse move for box selection"""
        if self.selection_start is not None:
            # Update selection rectangle
            self.selection_rect = QRect(self.selection_start, event.pos()).normalized()
            
            # Select items in rectangle
            path = self.mapToScene(self.selection_rect)
            self.scene.setSelectionArea(path)
            self.viewport().update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Handle mouse release for box selection"""
        if self.selection_start is not None:
            self.selection_start = None
            self.selection_rect = None
            self.viewport().update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """Zoom with mouse wheel"""
        if not event:
            return

        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        
        # Limit zoom range
        current_scale = self.transform().m11()
        new_scale = current_scale * factor
        
        # Clamp between 0.2x and 3x zoom
        if 0.2 <= new_scale <= 3.0:
            self.scale(factor, factor)

    def resizeEvent(self, event) -> None:
        """Handle resize events"""
        super().resizeEvent(event)
        # Maintain zoom level on resize, don't auto-fitje