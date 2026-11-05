"""Spec 0010 AC-10: let a Moderator publish or unpublish a certificate after the learner has left.

LMS runs its enrollment and progress checks on every save of a certificate, so once spec 0009 removes
the learner's enrollment, ticking "Publish on Participant Page" fails. This subclass keeps those
checks for a new certificate and for a saved one that is moved (member, course or batch changed),
and skips them for any other save of a saved certificate.
"""

from lms.lms.doctype.lms_certificate.lms_certificate import LMSCertificate

__all__ = ["NileLMSCertificate"]

IDENTITY_FIELDS = ("member", "course", "batch_name")


class NileLMSCertificate(LMSCertificate):
	def validate_criteria(self):
		self.validate_role_of_owner()
		if self.is_new() or any(self.has_value_changed(field) for field in IDENTITY_FIELDS):
			if self.batch_name:
				self.validate_batch_enrollment()
			elif self.course:
				self.validate_course_enrollment()
