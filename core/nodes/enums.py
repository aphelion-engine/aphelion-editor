"""Stable enum values shared by built-in frame nodes."""

from __future__ import annotations

from enum import IntEnum, auto


class BlendMode(IntEnum):
    """Pixel combination used by compositing nodes."""

    Normal = auto()
    Add = auto()
    Subtract = auto()
    Multiply = auto()
    Screen = auto()
    Overlay = auto()
    Difference = auto()
    Darken = auto()
    Lighten = auto()


class GradientMode(IntEnum):
    """Direction / shape of a generated gradient."""

    Horizontal = auto()
    Vertical = auto()
    Diagonal = auto()
    Radial = auto()


class TransformBorderMode(IntEnum):
    """Pixels synthesized beyond a transformed frame's bounds."""

    Black = auto()
    Hold = auto()
    Reflect = auto()


class SwitchInput(IntEnum):
    """Selected source for a two-input switch."""

    A = auto()
    B = auto()


class EdgeDisplayMode(IntEnum):
    """Presentation mode for detected edges."""

    Grayscale = auto()
    WhiteOnBlack = auto()
    BlackOnWhite = auto()


class MaskChannel(IntEnum):
    """Source channel used to generate a mask."""

    Luma = auto()
    Red = auto()
    Green = auto()
    Blue = auto()


class MirrorAxis(IntEnum):
    """Axis used by the mirror creative effect."""

    Horizontal = auto()
    Vertical = auto()


class CombineMaskMode(IntEnum):
    """Pixel operation used to combine two masks."""

    Add = auto()
    Subtract = auto()
    Intersect = auto()
    Max = auto()


class MathOperation(IntEnum):
    """Binary arithmetic operation for ``MathNode``."""

    Add = auto()
    Subtract = auto()
    Multiply = auto()
    Divide = auto()
    Power = auto()
    Minimum = auto()
    Maximum = auto()
    Average = auto()
    Modulo = auto()


class MathFunction(IntEnum):
    """Unary function for ``MathFunctionNode``."""

    Sine = auto()
    Cosine = auto()
    AbsoluteValue = auto()
    SquareRoot = auto()
    Negate = auto()
    Reciprocal = auto()


class ImageFitMode(IntEnum):
    """How a loaded still image is sized within its output frame."""

    Fit = auto()
    Fill = auto()
    Stretch = auto()
    Native = auto()
