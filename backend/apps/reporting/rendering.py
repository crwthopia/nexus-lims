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

# Labels are authored in the same way and for the same reason -- QA revises
# what a container label says without a code change -- but in their own
# directory, because they are not reports and must never be selectable as
# one. A Report.report_type that resolved to a 50mm label template would
# produce a "certificate of analysis" the size of a sticker.
LABEL_TEMPLATE_DIR = settings.BASE_DIR / "apps" / "reporting" / "templates" / "labels"

# StrictUndefined so a template referencing a field the context doesn't supply
# fails loudly at render time. The alternative silently prints an empty string,
# which on a regulatory document means shipping a COA with a blank result
# column and no indication anything went wrong.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,
    undefined=StrictUndefined,
)

# A second environment rather than a shared loader over both directories:
# `render_report_html` and `render_label_html` each resolve names only
# within their own set, so neither can reach the other's templates even by
# name collision. Same settings otherwise, and for the same reasons --
# see the module docstring on autoescape and StrictUndefined.
_label_env = Environment(
    loader=FileSystemLoader(str(LABEL_TEMPLATE_DIR)),
    autoescape=True,
    undefined=StrictUndefined,
)


def _format_datetime(value):
    if value is None:
        return "—"
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d %b %Y, %H:%M") if isinstance(value, datetime.datetime) else value.strftime("%d %b %Y")
    return str(value)


def _format_label_datetime(value):
    """
    A datetime with the year dropped: "29 Sep 10:03".

    Labels only. On 25mm stock the analyse-by line is the tightest thing on
    the label and the year is the least informative part of it -- the
    longest holding time in any of the methods here is 28 days, so a
    printed deadline can never be ambiguous about which year it means. A
    report says the year; a sticker on a bottle does not have room to.
    """
    if value is None:
        return "—"
    if isinstance(value, datetime.datetime):
        return value.strftime("%d %b %H:%M")
    if isinstance(value, datetime.date):
        return value.strftime("%d %b")
    return str(value)


_env.filters["nasat_datetime"] = _format_datetime
_label_env.filters["nasat_datetime"] = _format_datetime
_label_env.filters["nasat_label_datetime"] = _format_label_datetime


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


class LabelTemplateMissing(Exception):
    """Raised when a label kind has no corresponding template file."""


def render_label_html(template_name, context):
    """
    Renders a label template against `context`.

    Refuses a missing template rather than falling back, for the same reason
    render_report_html does -- but the consequence here is physical. A label
    is stuck to a container and outlives the screen that produced it, so a
    quietly substituted layout is a bottle in a fridge carrying the wrong
    fields with nothing to say so.
    """
    try:
        template = _label_env.get_template(template_name)
    except TemplateNotFound as exc:
        raise LabelTemplateMissing(
            f"No template '{template_name}' in {LABEL_TEMPLATE_DIR}."
        ) from exc
    return template.render(**context)
