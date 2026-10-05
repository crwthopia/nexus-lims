import { useState } from "react";
import { usePrintLabels } from "../api/queries";
import { describeApiError } from "../api/client";

/**
 * A button that prints a label or sheet and puts the PDF in front of the
 * browser's print dialogue.
 *
 * One component for all four print endpoints because they share the thing
 * that is easy to get wrong: the server refuses a second print of the same
 * kind for the same item unless a reason is given (ISO/IEC 17025:2017
 * 7.4.2, apps/samples/labels.record_print). Showing that refusal as a plain
 * error would leave a clerk holding a bottle with no label and no obvious
 * way forward, so the refusal is turned into the question it actually is —
 * asked once, answered, and sent straight back.
 *
 * The retry is keyed on the message carrying "7.4.2" rather than on the
 * status code, because a barcode too wide for the label stock is a 400 too
 * and asking "why are you reprinting?" about it would be nonsense.
 */
export function PrintButton({
  path,
  label,
  sampleId,
  className = "btn",
  reprintPrompt = "This has already been printed. Why is it being printed again?",
}: {
  path: string;
  label: string;
  sampleId?: number;
  className?: string;
  reprintPrompt?: string;
}) {
  const print = usePrintLabels(sampleId);
  const [error, setError] = useState<string | null>(null);

  function run(reason?: string) {
    setError(null);
    print.mutate(
      { path, body: reason ? { reason } : undefined },
      {
        onError: (failure) => {
          const message = describeApiError(failure);
          if (message.includes("7.4.2")) {
            const given = window.prompt(reprintPrompt);
            if (given?.trim()) {
              run(given.trim());
              return;
            }
            setError("Reprint cancelled — no reason given.");
            return;
          }
          setError(message);
        },
      },
    );
  }

  return (
    <>
      <button type="button" className={className} disabled={print.isPending} onClick={() => run()}>
        {print.isPending ? "Printing…" : label}
      </button>
      {error && (
        <p style={{ color: "var(--color-danger)", fontSize: "0.85rem", marginTop: 8 }}>{error}</p>
      )}
    </>
  );
}
