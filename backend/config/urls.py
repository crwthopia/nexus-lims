"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from apps.accounts.views import StaffLoginCompleteView
from apps.common.health import healthz, readyz

# Versioned under /api/v1/ per Blueprint Section 6. Each app owns its own
# urls.py (a SimpleRouter of ModelViewSets/ReadOnlyModelViewSets) so the
# resource groups stay aligned with the ASTM function-map app split in
# Blueprint Section 10, rather than one flat router here.
api_v1_patterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.samples.urls")),
    path("", include("apps.testing.urls")),
    path("", include("apps.review.urls")),
    path("", include("apps.reporting.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.equipment.urls")),
    path("", include("apps.billing.urls")),
    path("", include("apps.investigations.urls")),
    path("", include("apps.training.urls")),
]

urlpatterns = [
    # Probes first, and outside /api/v1/: they are infrastructure, not part
    # of the versioned API contract, and an operator or load balancer
    # should never have to know the API's version to ask whether the
    # process is alive. See apps/common/health.py for why there are two.
    path('healthz', healthz),
    path('readyz', readyz),
    # Django serves no frontend itself: both React SPAs (Blueprint Section
    # 2.1 item 1 -- ../../frontend Staff Console on :5174, ../../customer-portal
    # Customer Portal on :5173) are separate apps with their own dev servers,
    # proxying /api here rather than being served from it. Bare '/' redirects
    # to the admin site rather than 404ing, since that's the only browsable
    # entry point this backend has of its own.
    path('', RedirectView.as_view(url='/admin/', permanent=False)),
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_v1_patterns)),
    # DRF browsable-API login/logout (Log in link in the top-right of every
    # browsable API page), separate from admin/ so you don't need the admin
    # site just to authenticate a session for testing the API in a browser.
    path('api-auth/', include('rest_framework.urls')),
    # Entra ID staff SSO (Blueprint Section 2.1 item 7). Exposes
    # /oauth2/login (redirect to Microsoft), /oauth2/callback (matches the
    # redirect URI registered on the App Registration), /oauth2/logout, and
    # SSO-bypass variants. Importing this triggers django_auth_adfs to
    # validate AUTH_ADFS at startup -- see config/settings.py.
    path('oauth2/', include('django_auth_adfs.urls')),
    # Bounces the browser from this dev server's port back to the Staff
    # Console SPA's port once Entra ID SSO finishes -- see
    # apps.accounts.views.StaffLoginCompleteView and config/settings.py
    # STAFF_CONSOLE_BASE_URL for why this can't just be django-auth-adfs's
    # own "next" redirect.
    path('staff/login-complete/', StaffLoginCompleteView.as_view(), name='staff-login-complete'),
]
