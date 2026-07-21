from rest_framework.routers import SimpleRouter

from apps.testing.views import TestMethodViewSet, TestRequestViewSet, TestResultViewSet

router = SimpleRouter()
router.register("test-methods", TestMethodViewSet, basename="testmethod")
router.register("test-requests", TestRequestViewSet, basename="testrequest")
router.register("test-results", TestResultViewSet, basename="testresult")

urlpatterns = router.urls
