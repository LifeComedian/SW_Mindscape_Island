import type { ReactNode } from "react";

export function WorldStage({ children, illustrated = false }: { children: ReactNode; illustrated?: boolean }) {
  return (
    <div
      data-testid="world-stage"
      className={`relative mt-4 overflow-hidden rounded-2xl border border-stone-300 bg-sky-50 shadow-xl lg:h-[72vh] lg:max-h-[820px] lg:min-h-[580px] ${illustrated ? "" : "min-h-[480px]"}`}
    >
      {children}
    </div>
  );
}
