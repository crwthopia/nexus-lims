from rest_framework.routers import SimpleRouter

from apps.samples.views import (
    ChainOfCustodyEventViewSet,
    CustomerOrderViewSet,
    CustomerSampleViewSet,
    OrderViewSet,
    SampleViewSet,
)

router = SimpleRouter()
router.register("orders", OrderViewSet, basename="order")
router.register("samples", SampleViewSet, basename="sample")
router.register("chain-of-custody-events", ChainOfCustodyEventViewSet, basename="chainofcustodyevent")

# Customer-portal-facing, distinct prefix from the staff /orders//samples/
# resources above so the two identity domains never share a URL, even one
# that happens to be permission-gated the same way (Blueprint Section 2.1 item 7).
router.register("my/orders", CustomerOrderViewSet, basename="my-order")
router.register("my/samples", CustomerSampleViewSet, basename="my-sample")

urlpatterns = router.urls
