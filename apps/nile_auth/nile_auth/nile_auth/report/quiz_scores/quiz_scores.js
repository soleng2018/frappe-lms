frappe.query_reports["Quiz Scores"] = {
	filters: [
		{
			fieldname: "course",
			label: __("Course"),
			fieldtype: "Link",
			options: "LMS Course",
			get_query: () => ({ filters: { nile_key: ["is", "set"] } }),
		},
		{
			fieldname: "state",
			label: __("State"),
			fieldtype: "Select",
			options: ["", "Not attempted", "In progress", "Passed", "Locked"],
		},
		{ fieldname: "learner", label: __("Learner"), fieldtype: "Data" },
	],
	formatter(value, row, column, data, default_formatter) {
		let html = default_formatter(value, row, column, data);
		// Show the email, not the title Frappe picks for a User link, and link to the User.
		if (column.fieldname === "learner" && data) {
			const email = frappe.utils.escape_html(data.learner);
			html = `<a href="/app/user/${encodeURIComponent(data.learner)}">${email}</a>`;
		}
		if (column.fieldname === "quiz" && data) {
			const title = frappe.utils.escape_html(data.quiz_title || data.quiz);
			html = `<a href="/app/lms-quiz/${encodeURIComponent(data.quiz)}">${title}</a>`;
		}
		// A Locked quiz links to the attempts of that learner, where an admin can reset them (spec 0004).
		if (column.fieldname === "state" && data && data.state === "Locked") {
			const url =
				"/app/lms-quiz-submission?member=" +
				encodeURIComponent(data.learner) +
				"&quiz=" +
				encodeURIComponent(data.quiz);
			html = `<a href="${url}">${html}</a>`;
		}
		return html;
	},
};
