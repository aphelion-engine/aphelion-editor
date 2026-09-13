"""Tracking utilities, perspective transforms, and image compositing tools."""
from __future__ import annotations

import cv2
import numpy as np

from core.nodes.base import NodeSocketType
from core.nodes.frame_base import FrameEffectNode, FrameNode
from core.nodes.property_factory import number_property


def control(node, key, default, low, high, *, suffix=""):
    node.set_property(key, number_property(
        default, low, high, priority=10 + len(node.properties), group=node.node_type,
        label=key.replace("_", " ").title(), description=f"Adjust {key.replace('_', ' ')}.",
        suffix=suffix))
    node.expose_modulation_input(key)


class TrackOffsetNode(FrameNode):
    node_type = "Track Offset"
    node_category = "Tracking"
    node_description = "Offset or invert tracked X/Y coordinates in frame percent"
    node_color = (206, 100, 130)

    def _setup_sockets(self):
        for key in ("x", "y"):
            self.add_input(key, NodeSocketType.Number)
            self.add_output(key, NodeSocketType.Number)
        control(self, "offset_x", 0, -200, 200, suffix="%")
        control(self, "offset_y", 0, -200, 200, suffix="%")
        control(self, "scale", 1, -10, 10)

    def evaluate(self, frame_num):
        scale = self.float_value("scale", 1)
        return {key: self.input_number(key, 50) * scale + self.float_value("offset_" + key, 0)
                for key in ("x", "y")}


class TrackDistanceNode(FrameNode):
    node_type = "Track Distance"
    node_category = "Tracking"
    node_description = "Measure distance, angle, and midpoint between two tracked points (percent coordinates)"
    node_color = (206, 100, 130)

    def _setup_sockets(self):
        for key in ("x1", "y1", "x2", "y2"):
            self.add_input(key, NodeSocketType.Number)
        for key in ("distance", "angle", "mid_x", "mid_y"):
            self.add_output(key, NodeSocketType.Number)

    def evaluate(self, frame_num):
        x1, y1, x2, y2 = (self.input_number(k) for k in ("x1", "y1", "x2", "y2"))
        return {"distance": float(np.hypot(x2-x1, y2-y1)),
                "angle": float(np.degrees(np.arctan2(y2-y1, x2-x1))),
                "mid_x": (x1+x2)/2, "mid_y": (y1+y2)/2}


class MatchMoveNode(FrameEffectNode):
    node_type = "Match Move"
    node_category = "Tracking"
    node_description = "Translate a plate by tracked X/Y relative to a reference point; negate amount to stabilize"
    node_color = (206, 100, 130)

    def setup_effect_properties(self):
        for key in ("x", "y", "reference_x", "reference_y"):
            control(self, key, 50, -200, 200, suffix="%")
        control(self, "amount", 1, -1, 1)

    def process_frame(self, frame, frame_num):
        h, w = frame.shape[:2]
        amount = self.float_value("amount", 1)
        dx = (self.float_value("x", 50)-self.float_value("reference_x", 50))*w/100*amount
        dy = (self.float_value("y", 50)-self.float_value("reference_y", 50))*h/100*amount
        return cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h))


class PerspectiveTiltNode(FrameEffectNode):
    node_type = "Perspective Tilt"
    node_category = "Transform"
    node_description = "Project a flat image card with horizontal and vertical perspective tilt"
    node_color = (88, 176, 168)

    def setup_effect_properties(self):
        control(self, "tilt_x", 0, -80, 80, suffix="?")
        control(self, "tilt_y", 0, -80, 80, suffix="?")
        control(self, "focal_length", 1.5, 1, 10)

    def process_frame(self, frame, frame_num):
        h, w = frame.shape[:2]
        if min(h, w) < 2:
            return frame.copy()
        ax, ay = np.radians([self.float_value("tilt_x", 0), self.float_value("tilt_y", 0)])
        rx = np.array([[1,0,0], [0,np.cos(ax),-np.sin(ax)], [0,np.sin(ax),np.cos(ax)]])
        ry = np.array([[np.cos(ay),0,np.sin(ay)], [0,1,0], [-np.sin(ay),0,np.cos(ay)]])
        src = np.float32([[0,0], [w-1,0], [w-1,h-1], [0,h-1]])
        center = np.array([(w-1)/2, (h-1)/2])
        points = np.column_stack((src-center, np.zeros(4))) @ (ry @ rx).T
        focal = max(1, self.float_value("focal_length", 1.5))*max(w,h)
        dst = np.float32(points[:,:2]*focal/(focal+points[:,2:3])+center)
        return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(src, dst), (w,h))


class KeystoneNode(FrameEffectNode):
    node_type = "Keystone"
    node_category = "Transform"
    node_description = "Correct horizontal and vertical trapezoid perspective"
    node_color = (88, 176, 168)

    def setup_effect_properties(self):
        control(self, "horizontal", 0, -90, 90, suffix="%")
        control(self, "vertical", 0, -90, 90, suffix="%")

    def process_frame(self, frame, frame_num):
        h, w = frame.shape[:2]
        if min(h,w) < 2:
            return frame.copy()
        src = np.float32([[0,0], [w-1,0], [w-1,h-1], [0,h-1]])
        dst = src.copy()
        hx = np.clip(self.float_value("horizontal",0),-90,90)*(w-1)/200
        vy = np.clip(self.float_value("vertical",0),-90,90)*(h-1)/200
        dst[:,0] += [hx,-hx,hx,-hx]
        dst[:,1] += [vy,-vy,vy,-vy]
        return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(src,dst), (w,h))


class ChromaticAberrationNode(FrameEffectNode):
    node_type = "Chromatic Aberration"
    node_category = "VFX"
    node_description = "Separate red and blue channels to simulate lens color fringing"
    node_color = (168, 112, 194)

    def setup_effect_properties(self):
        control(self, "offset_x", 0.2, -10, 10, suffix="%")
        control(self, "offset_y", 0, -10, 10, suffix="%")

    def process_frame(self, frame, frame_num):
        result = frame.copy()
        h,w = frame.shape[:2]
        dx = self.float_value("offset_x",0.2)*w/100
        dy = self.float_value("offset_y",0)*h/100
        if frame.ndim == 3 and frame.shape[2] >= 3:
            for channel, sign in ((0,1),(2,-1)):
                result[:,:,channel] = cv2.warpAffine(frame[:,:,channel],
                    np.float32([[1,0,sign*dx],[0,1,sign*dy]]), (w,h), borderMode=cv2.BORDER_REFLECT_101)
        return result


class DirectionalBlurNode(FrameEffectNode):
    node_type = "Directional Blur"
    node_category = "VFX"
    node_description = "Simulate directional motion streaks with length and angle controls"
    node_color = (168, 112, 194)

    def setup_effect_properties(self):
        control(self, "length", 10, 0, 100, suffix="px")
        control(self, "angle", 0, -180, 180, suffix="?")

    def process_frame(self, frame, frame_num):
        radius = int(np.clip(round(self.float_value("length",10)),0,100))
        if radius == 0:
            return frame.copy()
        angle = np.radians(self.float_value("angle",0))
        kernel = np.zeros((2*radius+1,2*radius+1),np.float32)
        dx,dy = round(radius*np.cos(angle)),round(radius*np.sin(angle))
        cv2.line(kernel,(radius-dx,radius-dy),(radius+dx,radius+dy),1,1)
        kernel /= kernel.sum()
        return cv2.filter2D(frame,-1,kernel,borderType=cv2.BORDER_REFLECT_101)


class ChannelShuffleNode(FrameEffectNode):
    node_type = "Channel Shuffle"
    node_category = "Color"
    node_description = "Reorder or replicate RGB channels for pass manipulation (0=R, 1=G, 2=B)"
    node_color = (168, 112, 194)

    def setup_effect_properties(self):
        for index, key in enumerate(("red", "green", "blue")):
            control(self,key,index,0,2)

    def process_frame(self, frame, frame_num):
        result = frame.copy()
        if frame.ndim == 3 and frame.shape[2] >= 3:
            for index,key in enumerate(("red","green","blue")):
                result[:,:,index] = frame[:,:,int(np.clip(round(self.float_value(key,index)),0,2))]
        return result


VFX_NODE_TYPES = (TrackOffsetNode, TrackDistanceNode, MatchMoveNode,
                  PerspectiveTiltNode, KeystoneNode, ChromaticAberrationNode,
                  DirectionalBlurNode, ChannelShuffleNode)
