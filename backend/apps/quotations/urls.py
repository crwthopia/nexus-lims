from rest_framework.routers import SimpleRouter

from apps.quotations.views import CustomerQuotationViewSet, QuotationViewSet

router = SimpleRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("my/quotations", CustomerQuotationViewSet, basename="my-quotation")

urlpatterns = router.urls
