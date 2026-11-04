"""The checks on the MCP user's account (spec 0007). Pure Python, so the tools tests can run them."""

__all__ = ["MCP_ROLES", "mcp_user_problems"]

# Desk User makes Frappe keep the account a System User; the four are the LMS roles of LMS_ROLES.
MCP_ROLES = ("Desk User", "LMS Student", "Course Creator", "Moderator", "Batch Evaluator")


def mcp_user_problems(user_type: str, roles: set[str], missing_roles: list[str]) -> list[str]:
	"""Return what is wrong with the MCP user, or an empty list when it is safe to use.

	`missing_roles` are the wanted roles that do not exist as Role records on the site.
	"""
	problems = []
	if user_type != "System User":
		problems.append(f"user_type is {user_type}, not System User")
	if "Desk User" not in roles:
		problems.append("the Desk User role is missing")
	for role in missing_roles:
		problems.append(f"the role {role} does not exist on this site")
	if "System Manager" in roles:
		problems.append("the user holds System Manager, which the MCP user must never have")
	return problems
