from rest_framework.routers import SimpleRouter

from apps.training.views import (
    CreditNoteViewSet,
    CustomerCreditNoteViewSet,
    CustomerEnrollmentViewSet,
    EnrollmentViewSet,
    TrainingCourseViewSet,
    TrainingSessionViewSet,
)

router = SimpleRouter()
router.register("training-courses", TrainingCourseViewSet, basename="trainingcourse")
router.register("training-sessions", TrainingSessionViewSet, basename="trainingsession")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")
router.register("credit-notes", CreditNoteViewSet, basename="creditnote")
router.register("my/enrollments", CustomerEnrollmentViewSet, basename="my-enrollment")
router.register("my/credit-notes", CustomerCreditNoteViewSet, basename="my-creditnote")

urlpatterns = router.urls
