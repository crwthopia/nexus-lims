from rest_framework.routers import SimpleRouter

from apps.review.views import ApprovalActionViewSet, ReviewActionViewSet

router = SimpleRouter()
router.register("review-actions", ReviewActionViewSet, basename="reviewaction")
router.register("approval-actions", ApprovalActionViewSet, basename="approvalaction")

urlpatterns = router.urls
