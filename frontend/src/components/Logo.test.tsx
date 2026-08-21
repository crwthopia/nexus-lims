/**
 * The lockup.
 *
 * Worth a test for one reason that is not obvious: the wordmark used to be
 * a plain string, and when it was replaced by this component the whole
 * suite still passed, because nothing had ever asserted on the product
 * name. A logo is the one piece of UI a person identifies the product by,
 * and it was the least covered thing in the app.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Logo } from "./Logo";

describe("Logo", () => {
  it("reads as one product name, not two words", () => {
    // "Nexus" and "LIMS" are separate spans so each can take its own
    // colour, which is exactly the arrangement that would let them drift
    // apart visually or be read apart by a screen reader.
    const { container } = render(<Logo />);
    expect(container.textContent).toBe("NexusLIMS");
  });

  it("colours the product half with the brand token, not a literal", () => {
    // The cyan has to differ per theme -- #06B6D4 measures 2.16:1 on the
    // light canvas, under even the 3:1 WCAG allows large text -- so a
    // hardcoded hex here would be unreadable in one of the two themes.
    render(<Logo />);
    const lims = screen.getByText("LIMS");
    expect(lims).toHaveStyle({ color: "var(--color-brand)" });
  });

  it("hides the mark from assistive tech, since the wordmark says the name", () => {
    // Otherwise the name is announced twice, or the SVG is announced as an
    // unlabelled graphic.
    const { container } = render(<Logo />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("renders a smaller mark when compact", () => {
    const { container } = render(<Logo compact />);
    expect(container.querySelector("svg")).toHaveAttribute("width", "24");
  });
});
