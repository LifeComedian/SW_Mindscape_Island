"use client";

import { useEffect, useRef } from "react";

import SocialFeedPanel from "@/components/social/SocialFeedPanel";

type Props = {
  v5Enabled?: boolean;
  sessionId: number;
  initialFilter: "all" | "invitations";
  mutationsDisabled: boolean;
  language: "en" | "zh-CN";
  onClose: () => void;
  onWorldChanged: () => void;
  onUnreadCountChange: (count: number) => void;
};

export function SocialPhoneOverlay({
  sessionId, v5Enabled=false,
  initialFilter,
  mutationsDisabled,
  language,
  onClose,
  onWorldChanged,
  onUnreadCountChange,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {closeRef.current = onClose;}, [onClose]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const closeButton = dialogRef.current?.querySelector<HTMLElement>(
      '[data-testid="social-phone-close"]',
    );
    closeButton?.focus({ preventScroll: true });

    function handleKeyDown(event: KeyboardEvent) {
      if(dialogRef.current?.closest("[inert]"))return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter(el=>el.getClientRects().length);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus({ preventScroll: true });
    };
  }, []);

  return (
    <div className="fixed inset-0 z-[100] flex items-end justify-center bg-stone-950/65 p-0 backdrop-blur-sm sm:items-center sm:p-5">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={language === "zh-CN" ? "岛屿手机社交动态" : "Island phone social feed"}
        data-testid="social-phone-dialog"
        className="h-[94dvh] w-full overflow-hidden rounded-t-[2rem] border border-stone-300 bg-stone-50 shadow-2xl sm:h-[min(880px,90dvh)] sm:max-w-5xl sm:rounded-[2rem]"
      >
        <SocialFeedPanel
          key={`${sessionId}:${initialFilter}`}
          sessionId={sessionId}
          embedded v5Enabled={v5Enabled}
          initialFilter={initialFilter}
          mutationsDisabled={mutationsDisabled}
          onClose={onClose}
          onWorldChanged={onWorldChanged}
          onUnreadCountChange={onUnreadCountChange}
        />
      </div>
    </div>
  );
}
