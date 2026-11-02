"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

type Props = {
  open: boolean;
  title: string;
  closeLabel: string;
  onClose: () => void;
  children: ReactNode;
};

export function GameMenuDrawer({ open, title, closeLabel, onClose, children }: Props) {
  const closeRef = useRef(onClose);
  useEffect(() => {closeRef.current = onClose;}, [onClose]);
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const dialog = dialogRef.current;
    getFocusable(dialog)[0]?.focus({preventScroll: true});
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = getFocusable(dialog);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus({preventScroll: true});
    };
  }, [open]);

  if (!open) return null;
  return (
    <div data-testid="game-menu-drawer" className="game-overlay-enter fixed inset-0 z-[60]">
      <button
        type="button"
        aria-label={closeLabel}
        onClick={onClose}
        className="absolute inset-0 bg-stone-950/55 backdrop-blur-[2px]"
      />
      <aside
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="game-menu-title"
        className="absolute left-1/2 top-1/2 max-h-[85dvh] w-[calc(100%-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-3xl border border-stone-200 bg-stone-100 shadow-2xl"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between gap-4 border-b border-stone-200 bg-white/95 px-4 py-4 backdrop-blur sm:px-6">
          <h2 id="game-menu-title" className="text-lg font-black text-stone-950">{title}</h2>
          <button
            data-testid="game-menu-close"
            type="button"
            onClick={onClose}
            className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 text-sm font-bold text-stone-800 hover:bg-stone-50"
          >
            <X className="h-4 w-4" aria-hidden="true" />
            {closeLabel}
          </button>
        </header>
        <div className="break-words p-4 pb-[max(1rem,env(safe-area-inset-bottom))] [overflow-wrap:anywhere] sm:p-6 sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]">{children}</div>
      </aside>
    </div>
  );
}

function getFocusable(root: HTMLElement | null) {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>(
    'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
  )).filter((item) => !item.hasAttribute("aria-hidden"));
}
