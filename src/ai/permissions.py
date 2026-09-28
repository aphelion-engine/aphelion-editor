"""Agent permission policy.

Permissions are intentionally coarse. A tool declares the single capability
it needs; the policy answers yes or no. When a tool is refused, the refusal is
reported back to the model as a structured result so it can explain the
limitation to the user rather than silently doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai.types import (ALL_PERMISSIONS, DEFAULT_PERMISSIONS, PERMISSION_LABELS,
                      READ_ONLY_PERMISSIONS, Permission, permission_mask,
                      permission_names)


@dataclass(frozen=True)
class PermissionPolicy:
    """The set of capabilities the user has granted the assistant."""

    granted: Permission = DEFAULT_PERMISSIONS

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def allows(self, permission: Permission) -> bool:
        """Return whether every bit in ``permission`` is granted."""
        if permission is Permission.NONE:
            return True
        return (self.granted & permission) == permission

    def missing(self, permission: Permission) -> Permission:
        """Return the subset of ``permission`` that is not granted."""
        return permission & ~self.granted

    def describe(self, permission: Permission) -> str:
        """Human description of a capability refusal."""
        missing = self.missing(permission)
        names = [
            PERMISSION_LABELS.get(member, member.name)
            for member in ALL_PERMISSIONS
            if member in missing
        ]
        if not names:
            return "Allowed."
        return "The user has not granted: " + ", ".join(names) + "."

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def with_permission(self, permission: Permission, enabled: bool) -> PermissionPolicy:
        """Return a copy with one capability toggled."""
        if enabled:
            return PermissionPolicy(self.granted | permission)
        return PermissionPolicy(self.granted & ~permission)

    def without_all_edits(self) -> PermissionPolicy:
        """Return a read-only copy (used by Ask mode)."""
        editable = (
            Permission.EDIT_GRAPH
            | Permission.EDIT_PROPERTIES
            | Permission.EDIT_TIMELINE
            | Permission.EDIT_PROJECT
        )
        return PermissionPolicy(self.granted & ~editable)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"granted": permission_names(self.granted)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PermissionPolicy:
        if not data:
            return cls()
        raw = data.get("granted")
        if not isinstance(raw, list):
            return cls()
        return cls(permission_mask([str(item) for item in raw]))

    def capability_rows(self) -> list[tuple[Permission, str, bool]]:
        """Return ``(permission, label, enabled)`` rows for the settings UI."""
        return [
            (member, PERMISSION_LABELS[member], self.allows(member))
            for member in ALL_PERMISSIONS
        ]


#: Policy handed to a freshly enabled assistant in Ask mode.
READ_ONLY_POLICY: PermissionPolicy = PermissionPolicy(READ_ONLY_PERMISSIONS)
