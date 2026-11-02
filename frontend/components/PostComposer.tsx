"use client";
import {SocialAvatar} from "./social/SocialIdentity";

import { FormEvent, useId, useState } from "react";
import { Send } from "lucide-react";

import { useLanguage } from "@/lib/i18n";

type PostComposerProps = {
  nickname: string;
  disabled?: boolean;
  onSubmit: (content: string) => Promise<void> | void;
};

export default function PostComposer({
  nickname,
  disabled = false,
  onSubmit,
}: PostComposerProps) {
  const { t } = useLanguage();
  const inputId = useId();
  const [content, setContent] = useState("");
  const [isPublishing, setIsPublishing] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = content.trim();
    if (!trimmed) return;

    setIsPublishing(true);
    try {
      await onSubmit(trimmed);
      setContent("");
    } catch {
      // The parent displays the localized request error and keeps the draft intact.
    } finally {
      setIsPublishing(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-stone-200 bg-white p-4 shadow-sm"
    >
      <div className="flex gap-3">
        <SocialAvatar agentId={0} name={nickname}/>
        <div className="min-w-0 flex-1">
          <label htmlFor={inputId} className="text-sm font-semibold text-stone-900">
            {t("composer.title")}
          </label>
          <textarea
            id={inputId}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={disabled || isPublishing}
            rows={3}
            maxLength={800}
            placeholder={t("composer.placeholder")}
            className="focus-ring mt-2 min-h-24 w-full resize-none rounded-md border border-stone-300 bg-white px-3 py-2 text-sm leading-6 text-stone-900 placeholder:text-stone-400 disabled:cursor-not-allowed disabled:bg-stone-100"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="text-xs tabular-nums text-stone-500">
              {content.length}/800
            </span>
            <button
              type="submit"
              disabled={disabled || isPublishing || !content.trim()}
              className="focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-stone-300"
            >
              <Send className="h-4 w-4" aria-hidden="true" />
              {isPublishing ? t("composer.publishing") : t("composer.publish")}
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}
