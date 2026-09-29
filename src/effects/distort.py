"""Spatial distortion frame effects."""

from __future__ import annotations

import math

import cv2
import numpy as np
from core.nodes.enums import BendAxis
from effects.frame_ops import ensure_rgb_f32, resize_like


def twirl(frame: np.ndarray, *, angle_degrees: float, radius: float, strength: float,
          center_x: float, center_y: float) -> np.ndarray:
    """Rotate pixels around a center within a radial falloff."""
    from effects.native_fx import geometry_effect
    params = (float(angle_degrees), float(np.clip(radius, 0.0, 1.0)), float(strength),
              float(center_x), float(center_y))
    return geometry_effect("twirl", frame, params,
        lambda: _twirl_python(frame, angle_degrees=angle_degrees, radius=radius,
                              strength=strength, center_x=center_x, center_y=center_y))


def _twirl_python(frame: np.ndarray, *, angle_degrees: float, radius: float, strength: float,
                  center_x: float, center_y: float) -> np.ndarray:
    """OpenCV reference implementation of twirl."""
    source = ensure_rgb_f32(frame)
    height, width = source.shape[:2]
    if strength <= 1e-6: return source
    cx, cy = center_x*width, center_y*height
    max_radius = max(8.0, radius*min(width, height)*0.5)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx, dy = xx-cx, yy-cy
    distance = np.sqrt(dx*dx+dy*dy)
    falloff = np.clip(1.0-distance/max_radius, 0.0, 1.0)
    twist = np.deg2rad(angle_degrees)*falloff*strength
    cos_t, sin_t = np.cos(twist), np.sin(twist)
    map_x = np.where(falloff > 0.0, dx*cos_t-dy*sin_t+cx, xx).astype(np.float32)
    map_y = np.where(falloff > 0.0, dx*sin_t+dy*cos_t+cy, yy).astype(np.float32)
    return cv2.remap(source, map_x, map_y, interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT_101)


def bulge(frame: np.ndarray, *, strength: float, radius: float,
          center_x: float, center_y: float) -> np.ndarray:
    """Magnify or pinch pixels around a radial center."""
    from effects.native_fx import geometry_effect
    params = (float(strength), float(np.clip(radius, 0.0, 1.0)), float(center_x), float(center_y))
    return geometry_effect("bulge", frame, params,
        lambda: _bulge_python(frame, strength=strength, radius=radius,
                              center_x=center_x, center_y=center_y))


def _bulge_python(frame: np.ndarray, *, strength: float, radius: float,
                  center_x: float, center_y: float) -> np.ndarray:
    """OpenCV reference implementation of bulge/pinch."""
    source = ensure_rgb_f32(frame); height, width = source.shape[:2]
    if abs(strength) <= 1e-6: return source
    cx, cy = center_x*width, center_y*height
    max_radius = max(8.0, radius*min(width, height)*0.5)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    dx, dy = xx-cx, yy-cy
    distance = np.sqrt(dx*dx+dy*dy)
    normalized = np.clip(distance/max_radius, 0.0, 1.0)
    scale = 1.0+strength*(1.0-normalized*normalized)
    safe_scale = np.where(distance > 1e-3, scale, 1.0)
    return cv2.remap(source, (cx+dx/safe_scale).astype(np.float32),
                     (cy+dy/safe_scale).astype(np.float32), interpolation=cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT_101)


def wave_warp(frame: np.ndarray, *, amplitude: float, frequency: float, phase: float,
              direction: float, frame_num: int) -> np.ndarray:
    """Apply directional sinusoidal displacement."""
    from effects.native_fx import geometry_effect
    params = (float(amplitude), float(frequency), float(phase), float(direction), float(frame_num))
    return geometry_effect("wave_warp", frame, params,
        lambda: _wave_warp_python(frame, amplitude=amplitude, frequency=frequency,
                                  phase=phase, direction=direction, frame_num=frame_num))


def _wave_warp_python(frame: np.ndarray, *, amplitude: float, frequency: float, phase: float,
                      direction: float, frame_num: int) -> np.ndarray:
    """OpenCV reference implementation of directional sinusoidal displacement."""
    source=ensure_rgb_f32(frame);height,width=source.shape[:2]
    yy,xx=np.mgrid[0:height,0:width].astype(np.float32)
    radians=math.radians(direction);axis_x,axis_y=math.cos(radians),math.sin(radians)
    projection=xx*axis_x+yy*axis_y
    wave=np.sin(projection/max(1.0,min(width,height))*frequency*math.tau+math.radians(phase)+frame_num*.12)
    offset=wave*amplitude*min(width,height)*.04
    return cv2.remap(source,(xx-offset*axis_y).astype(np.float32),(yy+offset*axis_x).astype(np.float32),
                     interpolation=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)


def tile(frame: np.ndarray, *, columns: int, rows: int, mirror: bool) -> np.ndarray:
    """Repeat the frame into a grid, optionally mirroring alternating tiles."""
    from effects.native_fx import geometry_effect
    params=(float(max(1,min(64,columns))),float(max(1,min(64,rows))),1.0 if mirror else 0.0)
    return geometry_effect("tile",frame,params,
        lambda: _tile_python(frame,columns=columns,rows=rows,mirror=mirror))


def _tile_python(frame: np.ndarray, *, columns: int, rows: int, mirror: bool) -> np.ndarray:
    """OpenCV reference implementation of tiled imagery."""
    source: np.ndarray = ensure_rgb_f32(frame)
    cols: int = max(1, columns); row_count: int = max(1, rows)
    tiles: list[np.ndarray] = []
    for row_index in range(row_count):
        row_tiles: list[np.ndarray] = []
        for col_index in range(cols):
            tile: np.ndarray = source
            if mirror and (row_index + col_index) % 2 == 1: tile = cv2.flip(tile, 1)
            row_tiles.append(tile)
        tiles.append(np.hstack(row_tiles))
    output: np.ndarray = np.vstack(tiles)
    height, width = source.shape[:2]
    return cv2.resize(output, (width, height), interpolation=cv2.INTER_LINEAR)


def bend(frame: np.ndarray, *, amount: float, axis: BendAxis) -> np.ndarray:
    """Bow the frame along its axis with a parabolic curve."""
    from effects.native_fx import geometry_effect
    axis_id = 0 if axis == BendAxis.Horizontal else 1
    return geometry_effect("bend", frame, (float(amount), float(axis_id)),
        lambda: _bend_python(frame, amount=amount, axis=axis))


def _bend_python(frame: np.ndarray, *, amount: float, axis: BendAxis) -> np.ndarray:
    """OpenCV reference implementation of the parabolic bend."""
    source=ensure_rgb_f32(frame);height,width=source.shape[:2]
    if abs(amount)<=1e-6:return source
    yy,xx=np.mgrid[0:height,0:width].astype(np.float32)
    if axis==BendAxis.Horizontal:
        normalized=_unit_ramp(height).reshape(height,1);curve=1.0-normalized*normalized
        map_x=xx-curve*float(amount)*width;map_y=yy
    else:
        normalized=_unit_ramp(width).reshape(1,width);curve=1.0-normalized*normalized
        map_x=xx;map_y=yy-curve*float(amount)*height
    return cv2.remap(source,map_x.astype(np.float32),map_y.astype(np.float32),
                     interpolation=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)


def _unit_ramp(size: int) -> np.ndarray:
    """Return ``[-1, 1]`` coordinates along an axis of ``size`` samples."""
    if size <= 1: return np.zeros(max(1, size), dtype=np.float32)
    return np.linspace(-1.0, 1.0, size, dtype=np.float32)


def bump_map(frame: np.ndarray, height_map: np.ndarray, *, intensity: float,
             light_x: float, light_y: float, blur: float) -> np.ndarray:
    """Emboss the frame with a height map using OpenCV's native Sobel kernels."""
    source: np.ndarray = ensure_rgb_f32(frame)
    bump: np.ndarray = resize_like(ensure_rgb_f32(height_map), source)
    heights: np.ndarray = cv2.cvtColor(bump, cv2.COLOR_RGB2GRAY)
    if blur > 0.0: heights = cv2.GaussianBlur(heights, (0, 0), float(blur))
    from effects.native_fx import reference_mode, extended
    if not reference_mode():
        gx = cv2.Sobel(heights, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(heights, cv2.CV_32F, 0, 1, ksize=3)
        lx = float(np.clip(light_x, -1, 1)); ly = float(np.clip(light_y, -1, 1))
        lz = float(np.sqrt(max(.05, 1-lx*lx-ly*ly)))
        return extended(6, source, gx, (float(intensity), lx, ly, lz, 1.0), gy)
    gradient_x = cv2.Sobel(heights, cv2.CV_32F, 1, 0, ksize=3) * float(intensity)
    gradient_y = cv2.Sobel(heights, cv2.CV_32F, 0, 1, ksize=3) * float(intensity)
    normal = np.dstack([-gradient_x, -gradient_y, np.ones_like(heights)])
    norm = np.linalg.norm(normal, axis=2, keepdims=True)
    normal = normal / (norm + 1e-6)
    horizontal=float(np.clip(light_x,-1,1));vertical=float(np.clip(light_y,-1,1))
    light_z=float(np.sqrt(max(.05,1.0-horizontal*horizontal-vertical*vertical)))
    light=np.array([horizontal,vertical,light_z],dtype=np.float32)
    lambert=np.clip(np.tensordot(normal,light,axes=([2],[0])),0.0,1.0)
    return source*(1.0+(lambert-light_z))[:, :, None].astype(np.float32)


def offset(frame: np.ndarray, *, offset_x: float, offset_y: float, wrap: bool) -> np.ndarray:
    """Shift the frame by a fraction of its size, wrapping or filling edges."""
    from effects.native_fx import geometry_effect
    return geometry_effect("offset", frame, (float(offset_x),float(offset_y),1.0 if wrap else 0.0),
                           lambda: _offset_python(frame,offset_x=offset_x,offset_y=offset_y,wrap=wrap))


def _offset_python(frame: np.ndarray, *, offset_x: float, offset_y: float, wrap: bool) -> np.ndarray:
    """NumPy/OpenCV reference implementation of offset."""
    source=ensure_rgb_f32(frame);height,width=source.shape[:2]
    shift_x=int(round(float(offset_x)*width));shift_y=int(round(float(offset_y)*height))
    if shift_x==0 and shift_y==0:return source
    if wrap:return np.roll(np.roll(source,shift_y,axis=0),shift_x,axis=1)
    matrix=np.array([[1,0,float(shift_x)],[0,1,float(shift_y)]],dtype=np.float32)
    return cv2.warpAffine(source,matrix,(width,height),flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,borderValue=(0.0,0.0,0.0))
