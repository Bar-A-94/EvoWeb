export const NAVY = "#1f3a5f";
export const INK = "#2b3a4a";
export const MUTED = "#6b7a8c";
export const PAPER = "#f7f9fc";
export const LINE = "#d7dee8";
export const KIND: Record<string, { color: string; label: string }> = {
  feature: { color: "#2f5f8f", label: "functional" },
  "exact-value": { color: "#2f5f8f", label: "functional" },
  integration: { color: "#3f8f5f", label: "integration" },
  regression: { color: "#c08a2f", label: "backward" },
  backward: { color: "#c08a2f", label: "backward" },
};
export const VERDICT: Record<string, { color: string; glyph: string }> = {
  yes: { color: "#2e8b57", glyph: "✓" },
  partial: { color: "#d99a2b", glyph: "½" },
  no: { color: "#c0392b", glyph: "✗" },
};
export const NODE_FILL = ["#dbe8f7", "#f9dede", "#dff0e3", "#e9e2f5", "#fbe9c9"];
export const NODE_EDGE = ["#2f5f8f", "#c05a5a", "#3f8f5f", "#7a5fa8", "#c08a2f"];
export const SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif";
export const MONO = "'SF Mono', Menlo, Consolas, monospace";
