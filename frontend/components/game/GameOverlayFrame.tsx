"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function GameOverlayFrame({
  label,
  position = "center",
  escapeHint,
  children,
}: {
  label: string;
  position?: "center" | "bottom";
  escapeHint: string;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = getFocusable(dialog);
    focusable[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dialog.querySelector<HTMLElement>("[data-overlay-primary]")?.focus();
        return;
      }
      if (event.key !== "Tab") return;
      const items = getFocusable(dialog);
      if (!items.length) return;
      const first = items[0];
      const last = items.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className={`game-overlay-enter fixed inset-0 sm:absolute z-50 flex bg-stone-950/45 p-2 pb-[max(.5rem,env(safe-area-inset-bottom))] backdrop-blur-[2px] sm:p-4 sm:pb-[max(1rem,env(safe-area-inset-bottom))] ${position === "bottom" ? "items-end" : "items-center justify-center"}`}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        data-testid="game-overlay"
        className={position === "bottom"
          ? "game-panel-enter w-full break-words rounded-2xl border border-white/80 bg-stone-50 shadow-2xl [overflow-wrap:anywhere]"
          : "game-panel-enter max-h-full w-full max-w-2xl overflow-y-auto break-words rounded-2xl border border-white/80 bg-stone-50 shadow-2xl [overflow-wrap:anywhere]"}
      >
        {children}
        <p className="sr-only">{escapeHint}</p>
      </div>
    </div>
  );
}

function getFocusable(root: HTMLElement) {
  return Array.from(root.querySelectorAll<HTMLElement>(
    'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
  )).filter((item) => !item.hasAttribute("aria-hidden"));
}
