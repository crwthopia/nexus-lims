from rest_framework import serializers

from apps.training.models import CreditNote, Enrollment, TrainingCourse, TrainingSession


class TrainingCourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingCourse
        fields = [
            "id", "title", "description", "cpd_units", "price",
            "early_bird_discount_pct", "student_discount_pct",
        ]
        read_only_fields = ["id"]


class TrainingSessionSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    instructor_display_name = serializers.CharField(source="instructor.display_name", read_only=True, default=None)
    confirmed_enrollment_count = serializers.SerializerMethodField()

    class Meta:
        model = TrainingSession
        fields = [
            "id", "course", "course_title", "start_date", "end_date", "capacity",
            "min_capacity", "cancellation_threshold_days", "instructor", "instructor_display_name", "status",
            "confirmed_enrollment_count",
        ]
        read_only_fields = ["id", "status"]  # status only changes via the FSM (django-fsm-2 @transition methods)

    def get_confirmed_enrollment_count(self, obj):
        return obj.enrollments.filter(status=Enrollment.Status.CONFIRMED).count()


class EnrollmentSerializer(serializers.ModelSerializer):
    """Staff-facing: full write access, e.g. registering a walk-in or correcting a discount."""

    customer_email = serializers.CharField(source="customer.email", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id", "session", "customer", "customer_email", "payment_status",
            "discount_applied", "discount_override", "certificate_issued",
            "status", "created_at",
        ]
        read_only_fields = ["id", "status", "certificate_issued", "created_at"]


class CustomerEnrollmentSerializer(serializers.ModelSerializer):
    """
    Customer-facing (apps/training/views.py CustomerEnrollmentViewSet):
    customer is always the logged-in customer (set server-side, never
    client-supplied), discount_applied is computed server-side per the
    non-stacking rule (Blueprint Section 3.6), not accepted as input.
    """

    class Meta:
        model = Enrollment
        fields = [
            "id", "session", "customer", "payment_status", "discount_applied",
            "discount_override", "certificate_issued", "status", "created_at",
        ]
        read_only_fields = [
            "id", "customer", "payment_status", "discount_applied",
            "discount_override", "certificate_issued", "status", "created_at",
        ]

    def validate_session(self, session):
        if session.status != TrainingSession.Status.SCHEDULED:
            raise serializers.ValidationError("This session is not open for enrollment.")
        confirmed_count = session.enrollments.filter(status=Enrollment.Status.CONFIRMED).count()
        if confirmed_count >= session.capacity:
            raise serializers.ValidationError("This session is at full capacity.")
        return session


class CreditNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditNote
        fields = ["id", "customer", "source_enrollment", "amount", "status", "applied_to_enrollment", "created_at"]
        # All read-only: a CreditNote is only ever created by the training
        # capacity Celery task (apps/training/tasks.py) and only ever
        # transitions via the apply action (apps/training/views.py), never
        # a direct field edit.
        read_only_fields = fields
