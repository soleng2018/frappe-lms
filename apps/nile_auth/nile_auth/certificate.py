"""Spec 0010 AC-10: let a Moderator publish or unpublish a certificate after the learner has left.

LMS runs its enrollment and progress checks on every save of a certificate, so once spec 0009 removes
the learner's enrollment, ticking "Publish on Participant Page" fails. This subclass keeps those
checks for a new certificate and for a saved one that is moved (member, course or batch changed),
and skips them for any other save of a saved certificate.
"""

import base64

import frappe
from lms.lms.doctype.lms_certificate.lms_certificate import LMSCertificate

from nile_auth.branding import IMAGE_FILES

__all__ = ["NileLMSCertificate", "logo_data_uri"]

IDENTITY_FIELDS = ("member", "course", "batch_name")


class NileLMSCertificate(LMSCertificate):
	def validate_criteria(self):
		self.validate_role_of_owner()
		if self.is_new() or any(self.has_value_changed(field) for field in IDENTITY_FIELDS):
			if self.batch_name:
				self.validate_batch_enrollment()
			elif self.course:
				self.validate_course_enrollment()


def logo_data_uri(file_name: str) -> str:
	"""Spec 0012 AC-4: return a brand image of the app as a base64 data URI, so a render fetches nothing.

	Only the files the image build copies from brand/ are allowed, so a template cannot read other files.
	"""
	if file_name not in IMAGE_FILES:
		frappe.throw(f"logo_data_uri: {file_name} is not one of {', '.join(IMAGE_FILES)}")
	path = frappe.get_app_path("nile_auth", "public", "images", file_name)
	try:
		with open(path, "rb") as f:
			data = base64.b64encode(f.read()).decode()
	except OSError:
		frappe.throw(f"logo_data_uri: the brand file {path} is missing from the image")
	return f"data:image/png;base64,{data}"
