// Klaser portfolio product registry.
//
// Every product in the suite that renders the switcher must list every peer
// product here — keep this file identical across product frontends so the
// switcher is symmetrical. See docs/portfolio-integration.md.

export type ProductId = "takanon" | "meetings";

export type Product = {
  id: ProductId;
  label: string; // Hebrew, shown in the switcher
  url: string;   // absolute — cross-subdomain navigation
};

export const PRODUCTS: Product[] = [
  { id: "takanon", label: "תקנון", url: "https://takanon.klaser.co.il" },
  { id: "meetings", label: "ישיבות", url: "https://meetings.klaser.co.il" },
];

// The product this frontend is. Used to mark the current row in the switcher.
export const CURRENT_PRODUCT_ID: ProductId = "takanon";
