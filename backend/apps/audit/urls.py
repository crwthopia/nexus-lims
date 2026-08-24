from rest_framework.routers import SimpleRouter

from apps.audit.views import SystemFailureViewSet

router = SimpleRouter()
router.register("system-failures", SystemFailureViewSet, basename="system-failure")

urlpatterns = router.urls
