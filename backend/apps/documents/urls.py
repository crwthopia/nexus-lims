from rest_framework.routers import SimpleRouter

from apps.documents.views import DocumentVersionViewSet, DocumentViewSet

router = SimpleRouter()
router.register("documents", DocumentViewSet, basename="document")
router.register("document-versions", DocumentVersionViewSet, basename="documentversion")

urlpatterns = router.urls
