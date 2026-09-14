"""A point-driven shape matte with editable polygon outlines."""
from __future__ import annotations

import json

import cv2
import numpy as np
from core.nodes.base import NodeSocketType
from core.nodes.enums import TrackerShape
from core.nodes.property_factory import (choice_property, number_property,
                                         text_property)
from core.nodes.tracking_nodes import TrackerNode


class ShapeTrackerNode(TrackerNode):
    node_type = "Shape Tracker"
    node_description = "Track a point and translate an ellipse, rectangle, or custom polygon mask with it"

    def _setup_sockets(self):
        super()._setup_sockets()
        self.add_output("mask", NodeSocketType.Mask)
        self.set_property("shape", choice_property(TrackerShape.Ellipse, priority=20,
            group="Shape", label="Shape", description="Mask outline following the tracked point. Polygon vertices can be drawn in the viewport."))
        for key, value, low, high in (("width",20,0.1,200),("height",20,0.1,200),("feather",0,0,100)):
            self.set_property(key, number_property(value,low,high,priority=21+len(self.properties),
                group="Shape",label=key.title(),description=("Soft edge radius in preview pixels." if key == "feather" else "Shape size as a percentage of the frame."),
                suffix=" px" if key == "feather" else "%"))
        self.set_property("vertices",text_property("[]",priority=30,group="Shape",label="Polygon vertices",
            description="JSON list of [x,y] offsets from the tracked point in frame percent. Use Draw polygon above the preview to place vertices."))

    def polygon_vertices(self):
        try:
            values = json.loads(self.string_value("vertices","[]"))
            if not isinstance(values,list):
                return []
            points = []
            for point in values[:512]:
                if not isinstance(point,(list,tuple)) or len(point) != 2:
                    return []
                x,y = float(point[0]),float(point[1])
                if not np.isfinite([x,y]).all():
                    return []
                points.append((float(np.clip(x,-200,200)),float(np.clip(y,-200,200))))
            return points
        except (ValueError,TypeError):
            return []

    def outline(self, frame_num):
        position = super().evaluate(frame_num)
        if position["x"] is None or position["y"] is None:
            return np.empty((0,2),np.float32)
        center = np.array([position["x"],position["y"]],dtype=np.float32)
        shape = self.enum_value("shape",TrackerShape,TrackerShape.Ellipse)
        if shape == TrackerShape.Polygon:
            offsets = np.asarray(self.polygon_vertices(),dtype=np.float32).reshape(-1,2)
        elif shape == TrackerShape.Rectangle:
            offsets = np.float32([[-1,-1],[1,-1],[1,1],[-1,1]])
            offsets *= [self.float_value("width",20)/2,self.float_value("height",20)/2]
        else:
            angles = np.linspace(0,2*np.pi,64,endpoint=False)
            offsets = np.column_stack((np.cos(angles)*self.float_value("width",20)/2,
                                       np.sin(angles)*self.float_value("height",20)/2))
        return (offsets+center)/100

    def evaluate(self, frame_num):
        result = super().evaluate(frame_num)
        # The shape only needs the frame's *dimensions*, which always match the
        # evaluation size. Inheriting ``TrackerNode.input_required`` keeps the
        # connected plate from being decoded for this node alone (the tracking
        # worker samples the source explicitly), so a Shape Tracker in the
        # graph cannot force a source evaluation on every playback frame.
        width,height = self.evaluation_frame_size()
        mask = np.zeros((height,width),np.float32)
        points = self.outline(frame_num)
        if len(points) >= 3:
            pixels = np.rint(points*[max(1,width-1),max(1,height-1)]).astype(np.int32)
            radius = max(0,min(100,round(self.float_value("feather",0))))
            if radius:
                self._rasterize_feathered(mask,pixels,radius)
            else:
                cv2.fillPoly(mask,[pixels],1.0)
        result["mask"] = mask
        return result

    @staticmethod
    def _rasterize_feathered(mask,pixels,radius):
        """Rasterize and feather only the polygon's neighbourhood.

        A Gaussian blur of an all-zero region can only produce zeros, so
        blurring the whole frame is pure waste for the usual small shape. The
        polygon's bounding box padded by the kernel half-width is the only area
        that can become non-zero, and blurring that crop with a constant zero
        border matches the full-frame blur to float32 precision.
        """
        height,width = mask.shape
        pad = radius+1
        x0 = max(0,int(pixels[:,0].min())-pad)
        y0 = max(0,int(pixels[:,1].min())-pad)
        x1 = min(width,int(pixels[:,0].max())+pad+1)
        y1 = min(height,int(pixels[:,1].max())+pad+1)
        if x1 <= x0 or y1 <= y0:
            return
        local = np.zeros((y1-y0,x1-x0),np.float32)
        cv2.fillPoly(local,[pixels-np.array([x0,y0],np.int32)],1.0)
        local = cv2.GaussianBlur(local,(radius*2+1,radius*2+1),0,borderType=cv2.BORDER_CONSTANT)
        mask[y0:y1,x0:x1] = local
