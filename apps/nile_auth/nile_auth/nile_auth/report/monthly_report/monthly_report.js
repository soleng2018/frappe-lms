// The Month list is the current month and the 24 before it. The server checks the value again.
function monthOptions() {
	const [year, month] = frappe.datetime.now_date().split("-").map(Number);
	const options = [];
	for (let back = 0; back <= 24; back++) {
		const d = new Date(year, month - 1 - back, 1);
		options.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
	}
	return options;
}

frappe.query_reports["Monthly Report"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: monthOptions(),
			// The last full month, which is the second entry.
			default: monthOptions()[1],
		},
		{
			fieldname: "course",
			label: __("Course"),
			fieldtype: "Link",
			options: "LMS Course",
			get_query: () => ({ filters: { nile_key: ["is", "set"] } }),
		},
		{ fieldname: "result", label: __("Result"), fieldtype: "Select", options: ["", "Done", "Behind"] },
		{ fieldname: "learner", label: __("Learner"), fieldtype: "Data" },
		{ fieldname: "enrolled_only", label: __("Currently enrolled only"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		let html = default_formatter(value, row, column, data);
		// Show the email, not the title Frappe picks for a User link, and link to the User.
		if (column.fieldname === "learner" && data) {
			const email = frappe.utils.escape_html(data.learner);
			html = `<a href="/app/user/${encodeURIComponent(data.learner)}">${email}</a>`;
		}
		return html;
	},
};
