frappe.query_reports["Learner Progress"] = {
	filters: [
		{
			fieldname: "course",
			label: __("Course"),
			fieldtype: "Link",
			options: "LMS Course",
			get_query: () => ({ filters: { nile_key: ["is", "set"] } }),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Not started", "In progress", "Ready for certificate", "Certified"],
		},
		{ fieldname: "learner", label: __("Learner"), fieldtype: "Data" },
		{ fieldname: "enrolled_only", label: __("Currently enrolled only"), fieldtype: "Check", default: 0 },
	],
};
