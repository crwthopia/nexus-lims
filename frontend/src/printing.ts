/**
 * Getting a rendered PDF from the API to a printer.
 *
 * A hidden iframe rather than `window.open`, and the choice is not
 * cosmetic: a pop-up opened from inside an async mutation callback has lost
 * the browser's "user gesture" association by the time it runs, so it is
 * blocked by default in every major browser. The failure is silent -- the
 * mutation succeeds, the print event is recorded server-side, and no
 * dialogue ever appears. Someone at a receiving bench would conclude the
 * printer is broken and print again, which is a duplicate identity on a
 * second container and the exact thing ISO/IEC 17025:2017 7.4.2 is about.
 *
 * An iframe is same-document, needs no gesture, and puts the viewer's own
 * print dialogue in front of them with the label already loaded.
 */

/** How long to leave the iframe in the document after print() returns. */
const CLEANUP_DELAY_MS = 60_000;

export function printPdfBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const frame = document.createElement("iframe");

  // Off-screen rather than display:none: a frame that is not rendered has
  // no layout, and some engines will not give an unrendered frame's
  // contentWindow a working print().
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "1px";
  frame.style.height = "1px";
  frame.style.opacity = "0";
  frame.style.border = "0";
  frame.setAttribute("aria-hidden", "true");
  frame.src = url;

  frame.onload = () => {
    try {
      frame.contentWindow?.focus();
      frame.contentWindow?.print();
    } catch {
      // A browser that refuses to drive the embedded viewer still leaves
      // the operator somewhere to go: the blob opens in a tab, where their
      // own print button works. Silent failure is the one outcome that is
      // not acceptable here.
      window.open(url, "_blank", "noopener");
    }
    // Revoking immediately would pull the document out from under a print
    // dialogue that is still open, so the cleanup waits. A minute is far
    // longer than anyone spends choosing a printer, and the blob is a few
    // kilobytes.
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
      frame.remove();
    }, CLEANUP_DELAY_MS);
  };

  document.body.appendChild(frame);
}
