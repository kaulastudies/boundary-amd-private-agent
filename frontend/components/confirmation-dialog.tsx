import { useEffect, useRef } from "react";

interface ConfirmationDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  tone?: "default" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  tone = "default",
  onConfirm,
  onCancel,
}: ConfirmationDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <section
        aria-describedby="confirmation-description"
        aria-labelledby="confirmation-title"
        aria-modal="true"
        className="dialog-card"
        onKeyDown={(event) => { if (event.key === "Escape") onCancel(); }}
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <p className="eyebrow">Explicit confirmation</p>
        <h2 id="confirmation-title">{title}</h2>
        <p id="confirmation-description">{description}</p>
        <div className="dialog-actions">
          <button className="button button-ghost" onClick={onCancel} type="button">Cancel</button>
          <button
            className={`button ${tone === "danger" ? "button-danger" : "button-primary"}`}
            onClick={onConfirm}
            ref={confirmRef}
            type="button"
          >
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
