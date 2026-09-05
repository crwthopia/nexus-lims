from rest_framework.routers import SimpleRouter

from apps.catalogue.views import OfferingPriceViewSet, ServiceOfferingViewSet

router = SimpleRouter()
router.register("service-offerings", ServiceOfferingViewSet, basename="serviceoffering")
router.register("offering-prices", OfferingPriceViewSet, basename="offeringprice")

urlpatterns = router.urls
