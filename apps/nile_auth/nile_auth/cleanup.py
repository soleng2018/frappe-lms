"""One time cleanup for the dev site after spec 0009 (run by `bench execute`, never by the login)."""

import frappe

__all__ = ["clear_batch_courses"]


def clear_batch_courses(dry_run: bool = True) -> list[dict]:
	"""List, and with `dry_run=False` remove, the Batch Course rows of batches that carry `nile_group`.

	The old login made those batches and filled them with every published course. Nothing else is
	touched: the batches, their Batch Enrollments and the enrollments stay. Read the list first.
	"""
	batches = frappe.get_all("LMS Batch", filters={"nile_group": ["is", "set"]}, pluck="name")
	rows = (
		frappe.get_all(
			"Batch Course",
			filters={"parent": ["in", batches], "parenttype": "LMS Batch"},
			fields=["name", "parent", "course"],
		)
		if batches
		else []
	)
	for row in rows:
		print(f"{'would remove' if dry_run else 'removing'} course {row.course} from batch {row.parent}")
	if not dry_run:
		for row in rows:
			frappe.delete_doc("Batch Course", row.name, ignore_permissions=True, force=True)
		frappe.db.commit()
	print(f"{len(rows)} Batch Course row(s) in {len(batches)} batch(es)")
	return rows
