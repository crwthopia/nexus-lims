from rest_framework.routers import SimpleRouter

from apps.investigations.views import InvestigationViewSet

router = SimpleRouter()
router.register("investigations", InvestigationViewSet, basename="investigation")

urlpatterns = router.urls
