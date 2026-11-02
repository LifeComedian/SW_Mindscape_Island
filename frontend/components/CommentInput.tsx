"use client";

import { FormEvent, useId, useState } from "react";
import { Send } from "lucide-react";

import { useLanguage } from "@/lib/i18n";

type CommentInputProps = {
  onSubmit: (content: string) => Promise<void> | void;
  disabled?: boolean;
  placeholder?: string;
  submitLabel?: string;
};

export default function CommentInput({
  onSubmit,
  disabled = false,
  placeholder,
  submitLabel,
}: CommentInputProps) {
  const { t } = useLanguage();
  const inputId = useId();
  const [content, setContent] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = content.trim();
    if (!trimmed) return;

    setIsSaving(true);
    try {
      await onSubmit(trimmed);
      setContent("");
    } catch {
      // Parent displays the failure; keep the draft available for explicit retry.
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row">
      <label className="sr-only" htmlFor={inputId}>
        {t("post.commentLabel")}
      </label>
      <textarea
        id={inputId}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        disabled={disabled || isSaving}
        rows={2}
        maxLength={500}
        placeholder={placeholder ?? t("post.commentPlaceholder")}
        className="focus-ring min-h-20 flex-1 resize-none rounded-md border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 disabled:cursor-not-allowed disabled:bg-stone-100"
      />
      <button
        type="submit"
        disabled={disabled || isSaving || !content.trim()}
        title={t("post.sendTitle")}
        className="focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-teal-700 px-4 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-stone-300"
      >
        <Send className="h-4 w-4" aria-hidden="true" />
        {isSaving ? t("post.saving") : (submitLabel ?? t("post.comment"))}
      </button>
    </form>
  );
}
