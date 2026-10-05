"""
A renderer for the endpoints that answer with a PDF.

DRF negotiates content *before* it dispatches to the view, against the
renderers the view declares. The label and job-order endpoints return a
plain `HttpResponse` carrying PDF bytes, which bypasses rendering entirely
-- but only once the request has got that far. A client that politely said
`Accept: application/pdf` was answered 406 Not Acceptable by the
negotiation step, because no declared renderer claimed that media type:
the endpoint refused to serve exactly what it produces.

Declaring this renderer is what makes the Accept header true. It is
deliberately listed first on those actions, so the default `*/*` from a
browser also resolves here rather than to JSON -- the answer is the same
either way, since the view returns its own response object.

The interesting half is the error path. A refused reprint or a barcode too
wide for the stock is raised *after* negotiation, so DRF renders the error
dict through whichever renderer won -- this one. A client that asked for a
PDF and did not get one still has to be able to read why, so a non-bytes
payload is encoded as JSON and the response's content type is corrected on
the way out. Without that, an error would arrive labelled as a PDF and the
front end would show "something went wrong" instead of the reason.
"""

import json

from django.core.serializers.json import DjangoJSONEncoder
from rest_framework.renderers import BaseRenderer


class PdfRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    # None, not the default "utf-8": a PDF is bytes, and letting DRF append
    # "; charset=utf-8" to the content type is how a viewer decides it has
    # been handed text and shows the raw stream.
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, bytes):
            return data

        # See the module docstring: an error raised after negotiation.
        response = (renderer_context or {}).get("response")
        if response is not None:
            response["Content-Type"] = "application/json"
        return json.dumps(data, cls=DjangoJSONEncoder).encode("utf-8")
