"""
Report HTML rendering (Blueprint Section 2.1a).

Jinja2 with a FileSystemLoader rooted at this app's templates/reports/
directory, deliberately *not* wired into Django's TEMPLATES setting. The
Blueprint calls for report templates to live outside application code so
NASAT QA can author and revise them without a code change; keeping the
environment local to this module means adding a template is dropping a file
in a directory, and means report rendering can't accidentally pick up (or be
picked up by) the Django template machinery serving the admin site.

`autoescape` is on. A COA interpolates customer-supplied strings -- client
reference, sampling point, an analyst's free-text comment -- and while the
output is a PDF rather than a web page, an unescaped `<` still corrupts the
document it lands in.
"""

import datetime

from django.conf import settings
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

TEMPLATE_DIR = settings.BASE_DIR / "apps" / "reporting" / "templates" / "reports"

# StrictUndefined so a template referencing a field the context doesn't supply
# fails loudly at render time. The alternative silently prints an empty string,
# which on a regulatory document means shipping a COA with a blank result
# column and no indication anything went wrong.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,
    undefined=StrictUndefined,
)


def _format_datetime(value):
    if value is None:
        return "—"
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d %b %Y, %H:%M") if isinstance(value, datetime.datetime) else value.strftime("%d %b %Y")
    return str(value)


_env.filters["nasat_datetime"] = _format_datetime


class ReportTemplateMissing(Exception):
    """Raised when report_type has no corresponding template file."""


def template_name_for(report_type):
    return f"{report_type}.html"


def render_report_html(report, context):
    """
    Renders the template selected by `report.report_type` against `context`.

    Raises ReportTemplateMissing rather than falling back to a generic layout:
    quietly substituting a different template would produce a document that
    looks official and says the wrong thing.
    """
    name = template_name_for(report.report_type)
    try:
        template = _env.get_template(name)
    except TemplateNotFound as exc:
        raise ReportTemplateMissing(
            f"No template '{name}' in {TEMPLATE_DIR} for report_type '{report.report_type}'."
        ) from exc
    return template.render(**context)
