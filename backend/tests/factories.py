"""
factory_boy factories for every model exercised by the test suite.

Deliberately not one factory per model in the schema -- only what the tests
under backend/tests/ actually need. Models with non-trivial creation logic
(StaffUser/CustomerUser password handling) override _create() rather than
relying on the default manager, since AbstractBaseUser.objects.create()
doesn't hash passwords.
"""

import datetime

import factory
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from apps.accounts.models import CustomerUser, Role, StaffUser
from apps.billing.models import Invoice, Payment
from apps.catalogue.models import OfferingPrice, ServiceOffering
from apps.documents.models import Document, DocumentVersion
from apps.equipment.models import CalibrationRecord, Instrument, StandardReagent
from apps.investigations.models import Investigation
from apps.samples.models import Order, Sample, ServiceLine
from apps.testing.models import TestMethod, TestRequest, TestResult
from apps.training.models import CreditNote, Enrollment, TrainingCourse, TrainingSession

# Known raw password for every CustomerUserFactory-created account, since
# login tests need the plaintext to POST against /auth/customer/login.
CUSTOMER_RAW_PASSWORD = "Str0ngPassw0rd!1"


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = Role.RoleName.ANALYST


def get_role(name):
    """Roles are seeded by accounts/migrations/0003_seed_roles.py; fetch rather than recreate."""
    return Role.objects.get(name=name)


class StaffUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StaffUser
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"staff{n}@nasatlabs.test")
    entra_oid = factory.Sequence(lambda n: f"oid-{n}")
    display_name = factory.Sequence(lambda n: f"Staff User {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        roles = kwargs.pop("roles", None) or []
        certifications = kwargs.pop("instrument_certifications", None) or []
        manager = cls._get_manager(model_class)
        user = manager.create_user(*args, **kwargs)
        if roles:
            user.roles.set([get_role(name) for name in roles])
        if certifications:
            user.instrument_certifications.set(certifications)
        return user


class CustomerUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomerUser

    email = factory.Sequence(lambda n: f"customer{n}@example.test")
    password_hash = factory.LazyFunction(lambda: make_password(CUSTOMER_RAW_PASSWORD))
    is_email_verified = True


class TestMethodFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TestMethod

    name = factory.Sequence(lambda n: f"Test Method {n}")
    method_reference = factory.Sequence(lambda n: f"SOP-{n:04d}")
    specification_limits = factory.LazyFunction(dict)


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    customer = factory.SubFactory(CustomerUserFactory)
    service_line = ServiceLine.WATER_ENVIRONMENTAL


class SampleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Sample

    order = factory.SubFactory(OrderFactory)
    service_line = factory.LazyAttribute(lambda o: o.order.service_line if o.order else ServiceLine.WATER_ENVIRONMENTAL)
    unique_sample_code = factory.Sequence(lambda n: f"NASAT-{n:06d}")


class TestRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TestRequest

    sample = factory.SubFactory(SampleFactory)
    test_method = factory.SubFactory(TestMethodFactory)


class TestResultFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TestResult

    test_request = factory.SubFactory(TestRequestFactory)
    data_type = TestResult.DataType.FLOAT
    value = "1.0"
    entered_by = factory.SubFactory(StaffUserFactory)


class DocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Document

    title = factory.Sequence(lambda n: f"Document {n}")
    type = Document.DocumentType.SOP


class DocumentVersionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DocumentVersion

    document = factory.SubFactory(DocumentFactory)
    version_number = factory.Sequence(lambda n: n + 1)
    file_id = factory.Sequence(lambda n: f"oss://documents/doc-{n}.pdf")


class StandardReagentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StandardReagent

    name = factory.Sequence(lambda n: f"Reagent {n}")
    lot_number = factory.Sequence(lambda n: f"LOT-{n:04d}")
    crm_traceability_reference = factory.Sequence(lambda n: f"CRM-{n:04d}")
    expiry_date = factory.LazyFunction(lambda: timezone.localdate() + datetime.timedelta(days=365))
    status = StandardReagent.Status.ACTIVE


class InstrumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Instrument

    name = factory.Sequence(lambda n: f"Instrument {n}")
    model = Instrument.InstrumentModel.XRF
    status = Instrument.Status.IN_SERVICE


class CalibrationRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CalibrationRecord

    instrument = factory.SubFactory(InstrumentFactory)
    performed_by = factory.SubFactory(StaffUserFactory)
    performed_at = factory.LazyFunction(timezone.now)
    result = "pass"
    next_due_date = factory.LazyFunction(lambda: timezone.localdate() + datetime.timedelta(days=180))


class InvestigationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Investigation

    related_sample = factory.SubFactory(SampleFactory)
    type = Investigation.InvestigationType.OOS
    opened_by = factory.SubFactory(StaffUserFactory)


class TrainingCourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrainingCourse

    title = factory.Sequence(lambda n: f"Course {n}")
    cpd_units = "4.00"
    price = "5000.00"
    student_discount_pct = "20.00"


class TrainingSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TrainingSession

    course = factory.SubFactory(TrainingCourseFactory)
    start_date = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(days=30))
    end_date = factory.LazyFunction(lambda: timezone.now() + datetime.timedelta(days=31))
    capacity = 20
    min_capacity = 5
    cancellation_threshold_days = 7


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    session = factory.SubFactory(TrainingSessionFactory)
    customer = factory.SubFactory(CustomerUserFactory)


class CreditNoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CreditNote

    customer = factory.SubFactory(CustomerUserFactory)
    source_enrollment = factory.SubFactory(EnrollmentFactory)
    amount = "1000.00"


class InvoiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invoice

    order = factory.SubFactory(OrderFactory)
    amount = "1000.00"


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    invoice = factory.SubFactory(InvoiceFactory)
    method = Payment.Method.BANK_TRANSFER
    recorded_by = factory.SubFactory(StaffUserFactory)
    status = Payment.Status.PENDING_CONFIRMATION


class ServiceOfferingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ServiceOffering

    code = factory.Sequence(lambda n: f"WQ-{n:04d}")
    name = factory.Sequence(lambda n: f"Offering {n}")
    service_line = ServiceLine.WATER_ENVIRONMENTAL
    turnaround_days = 5


class OfferingPriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OfferingPrice

    offering = factory.SubFactory(ServiceOfferingFactory)
    amount = "1000.00"
    vat_treatment = OfferingPrice.VatTreatment.EXCLUSIVE
    effective_from = factory.LazyFunction(lambda: timezone.localdate())
