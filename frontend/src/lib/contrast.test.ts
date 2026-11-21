import { describe, expect, it } from "vitest";

import { contrastRatio, relativeLuminance } from "@/lib/contrast";

describe("contraste WCAG", () => {
  it("noir sur blanc = 21:1, couleur sur elle-même = 1:1", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrastRatio("#FF6B57", "#FF6B57")).toBeCloseTo(1, 5);
  });

  it("est symétrique", () => {
    expect(contrastRatio("#ECEAE4", "#0D0E13")).toBeCloseTo(contrastRatio("#0D0E13", "#ECEAE4"));
  });

  it("retrouve les ratios calculés pour DESIGN.md (à 0,01 près)", () => {
    expect(contrastRatio("#ECEAE4", "#0D0E13")).toBeCloseTo(16.02, 2);
    expect(contrastRatio("#14142B", "#FF6B57")).toBeCloseTo(6.43, 2);
    expect(contrastRatio("#6A6C7B", "#1C1D26")).toBeCloseTo(3.23, 2);
  });

  it("luminance relative bornée entre 0 et 1, et refuse une couleur invalide", () => {
    expect(relativeLuminance("#000000")).toBe(0);
    expect(relativeLuminance("#FFFFFF")).toBe(1);
    expect(() => relativeLuminance("rouge")).toThrow();
  });
});
