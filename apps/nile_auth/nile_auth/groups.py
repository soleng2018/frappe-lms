"""Classify the Authentik groups of one login into a decision (spec 0006). Pure: no Frappe, no I/O."""

import re
from dataclasses import dataclass
from typing import Any

from nile_auth.constants import ADMIN_ROLES, STUDENT_ROLES

__all__ = ["Decision", "decide"]

KIND_MEMBER = "member"
KIND_NO_GROUP = "no_group"
KIND_NO_CLAIM = "no_claim"


@dataclass(frozen=True)
class Decision:
	"""What one login's groups mean."""

	kind: str  # member, no_group or no_claim
	reason: str = ""  # for no_claim: "claim" (bad groups value) or "settings" (empty group setting)
	workshop_groups: tuple[str, ...] = ()  # sorted by number
	matched_groups: tuple[str, ...] = ()  # workshop groups, then the admin group
	is_admin: bool = False
	desired_roles: tuple[str, ...] = ()


def decide(groups: Any, admin_group: Any, prefix: Any, suffix: Any) -> Decision:
	"""Classify a userinfo groups value against the three site settings. Never raises."""
	if not all(isinstance(s, str) and s for s in (admin_group, prefix, suffix)):
		return Decision(KIND_NO_CLAIM, reason="settings")
	if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
		return Decision(KIND_NO_CLAIM, reason="claim")

	pattern = re.compile(rf"{re.escape(prefix)}([1-9][0-9]*){re.escape(suffix)}")
	numbered: dict[str, int] = {}
	for name in groups:
		found = pattern.fullmatch(name)
		if found:
			numbered[name] = int(found.group(1))
	workshop = tuple(sorted(numbered, key=lambda n: numbered[n]))
	is_admin = admin_group in groups
	matched = workshop + ((admin_group,) if is_admin else ())
	if not matched:
		return Decision(KIND_NO_GROUP)

	roles = (ADMIN_ROLES if is_admin else ()) + (STUDENT_ROLES if workshop else ())
	return Decision(KIND_MEMBER, "", workshop, matched, is_admin, roles)
