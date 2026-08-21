from rest_framework.routers import SimpleRouter

from apps.reporting.views import CustomerReportViewSet, ReportViewSet

router = SimpleRouter()
router.register("reports", ReportViewSet, basename="report")
# Customer-facing counterpart, same naming convention as my/orders,
# my/samples, my/invoices, my/enrollments and my/credit-notes.
router.register("my/reports", CustomerReportViewSet, basename="my-report")

urlpatterns = router.urls
