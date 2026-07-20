import type { RiskLevel } from "@/lib/types";

const riskPresentation: Record<RiskLevel, { icon: string; label: string; className: string }> = {
  safe: { icon: "✓", label: "Safe · local/read-only", className: "risk-safe" },
  review: { icon: "◌", label: "Review · local change", className: "risk-review" },
  sensitive: { icon: "!", label: "Sensitive · approval required", className: "risk-sensitive" },
  destructive: { icon: "▲", label: "Destructive · explicit approval", className: "risk-destructive" },
  blocked: { icon: "×", label: "Blocked · cannot execute", className: "risk-blocked" },
};

export function RiskBadge({ risk }: { risk: RiskLevel }) {
  const presentation = riskPresentation[risk];
  return (
    <span className={`risk-badge ${presentation.className}`}>
      <span aria-hidden="true">{presentation.icon}</span>
      {presentation.label}
    </span>
  );
}
