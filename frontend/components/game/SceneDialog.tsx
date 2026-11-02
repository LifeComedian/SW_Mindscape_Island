"use client";
import {useEffect, useRef, useSyncExternalStore, type ReactNode} from "react";

import {createPortal} from 'react-dom';
const subscribe=()=>()=>{};
const layers:HTMLElement[]=[];
const originalInert=new Map<HTMLElement,boolean>();
function syncLayers(){
  const top=layers.at(-1);
  for(const child of Array.from(document.body.children)){
    if(!(child instanceof HTMLElement)||child.tagName==='SCRIPT')continue;
    if(top){if(!originalInert.has(child))originalInert.set(child,child.inert);child.inert=child!==top;}
  }
  if(!top){for(const [node,value] of Array.from(originalInert))node.inert=value;originalInert.clear();}
}
/** Modal surface for objects, menus, and activities. */
export function SceneDialog({title, children, onClose, wide = false, status = ""}: {title: string; children: ReactNode; onClose?: () => void; wide?: boolean; status?: string}) {
  const mounted=useSyncExternalStore(subscribe,()=>true,()=>false);
  const panel = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  useEffect(() => {close.current = onClose;}, [onClose]);
  useEffect(() => {
    if(!mounted||!panel.current?.parentElement)return;
    const previous=document.activeElement as HTMLElement|null;
    const layer=panel.current.parentElement;
    layers.push(layer);syncLayers();
    panel.current?.focus();
    function keys(e: KeyboardEvent) {
      if(layers.at(-1)!==layer)return;
      if (e.key === "Escape" && close.current) {e.preventDefault(); close.current();}
      if (e.key !== "Tab") return;
      const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),textarea:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href],[tabindex="0"]') ?? []).filter(el => el.getClientRects().length);
      if (!items.length) {e.preventDefault(); return;}
      if (e.shiftKey && (document.activeElement === items[0] || document.activeElement === panel.current)) {e.preventDefault(); items.at(-1)?.focus();}
      else if (!e.shiftKey && document.activeElement === items.at(-1)) {e.preventDefault(); items[0].focus();}
    }
    window.addEventListener("keydown", keys);
    return () => {layers.splice(layers.indexOf(layer),1);syncLayers();window.removeEventListener("keydown",keys);previous?.focus({preventScroll:true});};
  }, [mounted]);
  if(!mounted)return null;
  return createPortal(<div className="fixed inset-0 z-[110] flex items-center justify-center bg-stone-950/60 p-2 sm:p-4 backdrop-blur-sm">
    <section ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={`flex max-h-[94dvh] w-full flex-col overflow-hidden rounded-3xl bg-stone-50 shadow-2xl ${wide ? "max-w-5xl" : "max-w-2xl"}`}>
      <header className="flex shrink-0 items-center justify-between gap-3 border-b bg-white px-4 py-3 sm:px-6"><h1 className="text-lg font-bold text-stone-900">{title}</h1>{onClose ? <button type="button" onClick={onClose} className="focus-ring rounded-xl border bg-white px-4 py-2">关闭</button> : status ? <span className="text-xs text-teal-800">{status}</span> : null}</header>
      <div className="overflow-y-auto overscroll-contain p-3 sm:p-5">{children}</div>
    </section>
  </div>,document.body);
}
