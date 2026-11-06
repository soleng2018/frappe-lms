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
	],	formatter(value, row, column, data, default_formatter) {
		let html = default_formatter(value, row, column, data);
		// Show the email, not the title Frappe picks for a User link, and link to the User.
		if (column.fieldname === "learner" && data) {
			const email = frappe.utils.escape_html(data.learner);
			html = `<a href="/app/user/${encodeURIComponent(data.learner)}">${email}</a>`;
		}
		return html;
	},
};
