"use client";

import { Heart, MessageCircle, SkipForward } from "lucide-react";

import { useLanguage } from "@/lib/i18n";

type ReactionButtonsProps = {
  onLike: () => void;
  onUnlike: () => void;
  onSkip: () => void;
  liked?: boolean;
  likeCount?: number;
  commentCount?: number;
  disabled?: boolean;
};

export default function ReactionButtons({
  onLike,
  onUnlike,
  onSkip,
  liked = false,
  likeCount = 0,
  commentCount = 0,
  disabled = false,
}: ReactionButtonsProps) {
  const { t } = useLanguage();

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={liked ? onUnlike : onLike}
          disabled={disabled}
          title={liked ? t("post.unlikeTitle") : t("post.likeTitle")}
          className={`focus-ring inline-flex min-h-10 items-center gap-2 rounded-md border px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-70 ${
            liked
              ? "border-rose-300 bg-rose-100 text-rose-900"
              : "border-rose-200 bg-rose-50 text-rose-800 hover:bg-rose-100"
          }`}
        >
          <Heart
            className={`h-4 w-4 ${liked ? "fill-current" : ""}`}
            aria-hidden="true"
          />
          {liked ? t("post.liked") : t("post.like")}
          <span className="tabular-nums">{likeCount}</span>
        </button>
        <button
          type="button"
          onClick={onSkip}
          disabled={disabled}
          title={t("post.skipTitle")}
          className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <SkipForward className="h-4 w-4" aria-hidden="true" />
          {t("post.skip")}
        </button>
      </div>
      <span className="inline-flex min-h-10 items-center gap-2 text-sm text-stone-500">
        <MessageCircle className="h-4 w-4" aria-hidden="true" />
        <span className="tabular-nums">{commentCount}</span>
      </span>
    </div>
  );
}
