"use client";
import {SocialAvatar,useSocialIdentity} from "./social/SocialIdentity";

import { useState } from "react";
import { Heart, MessageCircle, Reply } from "lucide-react";

import type { CommunityActivity, PhoneInvitationCard, SimulationPost } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import CommentInput from "./CommentInput";
import ReactionButtons from "./ReactionButtons";

export type CommentTarget = {
  targetAgentId: number;
  targetAgentName: string;
  parentCommunityActivityId?: number;
};

type PostCardProps = {
  post: SimulationPost;
  currentDay: number;
  liked?: boolean;
  comments?: CommentThread[];
  onLike: (postId: number) => Promise<void> | void;
  onUnlike: (postId: number) => Promise<void> | void;
  onSkip: (postId: number) => Promise<void> | void;
  onComment: (
    postId: number,
    content: string,
    target: CommentTarget,
  ) => Promise<void> | void;
  onThreadReply: (
    postId: number,
    threadId: string,
    targetAgentId: number,
    parentInteractionId: number,
    content: string,
  ) => Promise<void> | void;
  disabled?: boolean;
  invitation?: PhoneInvitationCard;
  onInvitationResponse?: (
    response: "accept" | "reject" | "defer" | "withdraw",
  ) => Promise<void> | void;
};

export type CommentExchange = {
  id: string;
  userComment: string;
  userInteractionId?: number;
  agentReply?: string;
  agentReplyInteractionId?: number;
  isLoading?: boolean;
  error?: string;
  generationMode?: string | null;
  safetyFlag?: boolean;
};

export type CommentThread = {
  id: string;
  targetAgentId: number;
  targetAgentName: string;
  parentCommunityActivityId?: number;
  exchanges: CommentExchange[];
};

export default function PostCard({
  post,
  currentDay,
  liked = false,
  comments = [],
  onLike,
  onUnlike,
  onSkip,
  onComment,
  onThreadReply,
  disabled = false,
  invitation,
  onInvitationResponse,
}: PostCardProps) {
  const { language, t } = useLanguage();
  const identity=useSocialIdentity();
  const authorName=identity.name(post.agent_id,post.agent_name);
  const localizedPost = post.translations?.[language];
  const agentRole = post.is_user_post
    ? t("post.yourPost")
    : localizedPost?.agent_role ?? post.agent_role;
  const postContent = localizedPost?.content ?? post.content;
  const userCommentCount = comments.reduce(
    (total, thread) => total + thread.exchanges.length,
    0,
  );
  const totalCommentCount = post.community_comments.length + userCommentCount;
  const originalPostThreads = comments.filter(
    (thread) => !thread.parentCommunityActivityId,
  );
  const timeLabel =
    post.day === currentDay
      ? t("post.todayAt", { time: post.time })
      : post.day === currentDay - 1
        ? t("post.yesterdayAt", { time: post.time })
        : t("post.dayAt", { day: post.day, time: post.time });

  return (
    <article
      id={`post-${post.id}`}
      className="scroll-mt-24 rounded-lg border border-stone-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-start gap-3">
        <SocialAvatar agentId={post.agent_id} name={authorName} size={44}/>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 className="text-base font-semibold text-stone-950">{authorName}</h2>
            {!post.is_user_post && !identity.enabled ? (
              <span className="text-xs text-stone-500">
                @{post.agent_name.toLowerCase()}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 text-xs text-stone-500">
            {agentRole} · {timeLabel}
          </p>
        </div>
      </div>

      <p className="mt-4 whitespace-pre-wrap text-base leading-7 text-stone-800">
        {postContent}
      </p>

      {invitation ? (
        <InvitationDetails
          invitation={invitation}
          disabled={disabled}
          onResponse={onInvitationResponse}
        />
      ) : null}

      {!invitation ? <div className="mt-5 flex flex-col gap-3">
        {post.is_user_post ? (
          <div className="flex min-h-10 items-center gap-5 border-y border-stone-200 py-2 text-sm text-stone-600">
            <span className="inline-flex items-center gap-2">
              <Heart className="h-4 w-4" aria-hidden="true" />
              {t("post.likeCount", { count: post.community_like_count })}
            </span>
            <span className="inline-flex items-center gap-2">
              <MessageCircle className="h-4 w-4" aria-hidden="true" />
              {t("post.commentCount", { count: totalCommentCount })}
            </span>
          </div>
        ) : (
          <ReactionButtons
            onLike={() => onLike(post.id)}
            onUnlike={() => onUnlike(post.id)}
            onSkip={() => onSkip(post.id)}
            liked={liked}
            likeCount={post.community_like_count + (liked ? 1 : 0)}
            commentCount={totalCommentCount}
            disabled={disabled}
          />
        )}

        <CommunityDiscussion
          activities={post.community_comments}
          comments={comments}
          postId={post.id}
          disabled={disabled}
          onComment={onComment}
          onThreadReply={onThreadReply}
        />

        {!post.is_user_post && post.allow_comments ? (
          <CommentInput
            onSubmit={(content) =>
              onComment(post.id, content, {
                targetAgentId: post.agent_id,
                targetAgentName: authorName,
              })
            }
            disabled={disabled}
            placeholder={t("post.replyToOriginal", { name: authorName })}
          />
        ) : null}

        {originalPostThreads.length > 0 ? (
          <section className="border-t border-stone-200 pt-4">
            <h3 className="text-sm font-semibold text-stone-950">
              {t("post.commentsTitle")}
            </h3>
            <div className="mt-3 space-y-4">
              {originalPostThreads.map((thread) => (
                <ConversationThread
                  key={thread.id}
                  thread={thread}
                  postId={post.id}
                  disabled={disabled}
                  onThreadReply={onThreadReply}
                />
              ))}
            </div>
          </section>
        ) : null}
      </div> : null}
    </article>
  );
}

function InvitationDetails({
  invitation,
  disabled,
  onResponse,
}: {
  invitation: PhoneInvitationCard;
  disabled: boolean;
  onResponse?: (
    response: "accept" | "reject" | "defer" | "withdraw",
  ) => Promise<void> | void;
}) {
  const { language } = useLanguage();
  const isChinese = language === "zh-CN";
  const time = `${String(Math.floor(invitation.scheduled_time_minutes / 60)).padStart(2, "0")}:${String(invitation.scheduled_time_minutes % 60).padStart(2, "0")}`;
  const label = invitation.label[language] ?? invitation.label.en ?? invitation.recipe_id;
  const canAccept =
    invitation.status === "proposed" || invitation.status === "accepted" || (invitation.status === "in_progress" && invitation.open_admission_until_end)
      ? invitation.viewer_response === null ||
        invitation.viewer_response === undefined ||
        invitation.viewer_response === "proposed" ||
        invitation.viewer_response === "deferred"
      : false;
  const canDecline = (invitation.status === "proposed" || invitation.status === "accepted") && (invitation.viewer_response === "proposed" || invitation.viewer_response === "deferred");
  const canWithdraw =
    (invitation.status === "proposed" || invitation.status === "accepted") && invitation.viewer_response === "accepted" && invitation.author.actor_type !== "participant";

  return (
    <section
      className="mt-4 rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-950"
      data-testid={`phone-invitation-${invitation.post_id}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong>{label}</strong>
        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold">
          {isChinese ? "活动邀约" : "Invitation"}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <div><dt className="font-semibold">{isChinese ? "时间" : "Time"}</dt><dd>{isChinese ? `第 ${invitation.scheduled_day} 天` : `Day ${invitation.scheduled_day}`} · {time} · {invitation.duration_minutes} min</dd></div>
        <div><dt className="font-semibold">{isChinese ? "地点" : "Location"}</dt><dd>{invitation.location_label?.[language] ?? invitation.location_label?.en ?? invitation.location_id}</dd></div>
        <div><dt className="font-semibold">{isChinese ? "报名人数" : "Formation"}</dt><dd>{invitation.accepted_count}/{invitation.min_participants}–{invitation.max_participants}</dd></div>
        <div><dt className="font-semibold">{isChinese ? "已经到场" : "Attendance"}</dt><dd>{invitation.actual_attendance_count} {isChinese ? "人" : "people"}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-teal-800">
        {isChinese ? ({proposed: "正在等待回应", accepted: "已约好，记得按时赴约", in_progress: "活动正在进行", completed: "活动已结束", cancelled: "活动已取消", failed: "这次活动未能完成", expired: "邀请已过期"} as Record<string, string>)[invitation.status] ?? "安排已更新" : invitation.status}。{invitation.open_admission_until_end ? (isChinese ? "晚会结束前都可以加入，也可以旁观或提前离开。" : "You can join before the party ends or leave early.") : (isChinese ? `大家会在约定时间等待 ${invitation.wait_minutes} 分钟。` : `Arrival wait: ${invitation.wait_minutes} minutes.`)}
      </p>
      {invitation.response_feedback?.map(r=><p key={r.agent_id} className="mt-2 rounded-lg bg-white p-3 text-sm" role="status">{r.name}：{r.text}</p>)}
      {onResponse && invitation.can_respond && (canAccept || canDecline || canWithdraw) ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {canAccept ? <button type="button" disabled={disabled} onClick={() => onResponse("accept")} className="focus-ring min-h-10 rounded-md bg-teal-800 px-3 font-semibold text-white disabled:opacity-50">{isChinese ? "接受" : "Accept"}</button> : null}
          {canDecline ? <button type="button" disabled={disabled} onClick={() => onResponse("defer")} className="focus-ring min-h-10 rounded-md border border-teal-300 bg-white px-3 font-semibold disabled:opacity-50">{isChinese ? "稍后决定" : "Decide later"}</button> : null}
          {canDecline ? <button type="button" disabled={disabled} onClick={() => onResponse("reject")} className="focus-ring min-h-10 rounded-md border border-rose-300 bg-white px-3 font-semibold text-rose-800 disabled:opacity-50">{isChinese ? "拒绝" : "Decline"}</button> : null}
          {canWithdraw ? <button type="button" disabled={disabled} onClick={() => onResponse("withdraw")} className="focus-ring min-h-10 rounded-md border border-rose-300 bg-white px-3 font-semibold text-rose-800 disabled:opacity-50">{isChinese ? "退出" : "Withdraw"}</button> : null}
        </div>
      ) : null}
    </section>
  );
}

function CommunityDiscussion({
  activities,
  comments,
  postId,
  disabled,
  onComment,
  onThreadReply,
}: {
  activities: CommunityActivity[];
  comments: CommentThread[];
  postId: number;
  disabled: boolean;
  onComment: (
    postId: number,
    content: string,
    target: CommentTarget,
  ) => Promise<void> | void;
  onThreadReply: PostCardProps["onThreadReply"];
}) {
  const { language, t } = useLanguage();
  const [replyingToId, setReplyingToId] = useState<number | null>(null);
  const rootComments = activities.filter((activity) => !activity.parent_activity_id);

  if (rootComments.length === 0) return null;

  function renderActivity(activity: CommunityActivity, isReply = false) {
    const attachedThreads = comments.filter(
      (thread) => thread.parentCommunityActivityId === activity.activity_id,
    );
    return (
      <div key={activity.activity_id} className="space-y-3">
        <CommunityComment
          activity={activity}
          content={activity.translations?.[language]?.content ?? activity.content}
          isReply={isReply}
          onReply={() =>
            setReplyingToId((current) =>
              current === activity.activity_id ? null : activity.activity_id,
            )
          }
        />
        {replyingToId === activity.activity_id ? (
          <div className="ml-10">
            <CommentInput
              onSubmit={async (content) => {
                await onComment(postId, content, {
                  targetAgentId: activity.actor.agent_id,
                  targetAgentName: activity.actor.name,
                  parentCommunityActivityId: activity.activity_id,
                });
                setReplyingToId(null);
              }}
              disabled={disabled}
              placeholder={t("post.replyTo", { name: activity.actor.name })}
              submitLabel={t("post.reply")}
            />
          </div>
        ) : null}
        {attachedThreads.length > 0 ? (
          <div className="ml-10 space-y-4">
            {attachedThreads.map((thread) => (
              <ConversationThread
                key={thread.id}
                thread={thread}
                postId={postId}
                disabled={disabled}
                onThreadReply={onThreadReply}
              />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <section className="border-t border-stone-200 pt-4">
      <h3 className="text-sm font-semibold text-stone-950">
        {t("post.communityDiscussion")}
      </h3>
      <div className="mt-3 space-y-4">
        {rootComments.map((comment) => {
          const replies = activities.filter(
            (activity) => activity.parent_activity_id === comment.activity_id,
          );
          return (
            <div key={comment.activity_id} className="space-y-3">
              {renderActivity(comment)}
              {replies.map((reply) => (
                <div
                  key={reply.activity_id}
                  className="ml-5 border-l-2 border-stone-200 pl-3"
                >
                  {renderActivity(reply, true)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function CommunityComment({
  activity,
  content,
  isReply = false,
  onReply,
}: {
  activity: CommunityActivity;
  content: string;
  isReply?: boolean;
  onReply: () => void;
}) {
  const { t } = useLanguage();
  return (
    <div className="flex gap-2">
      <SocialAvatar agentId={activity.actor.agent_id} name={activity.actor.name} size={32}/>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <p className="text-xs font-semibold text-stone-900">{activity.actor.name}</p>
          <span className="text-xs text-stone-500">
            {isReply && activity.target
              ? t("post.replyingTo", {
                  name: activity.actor.name,
                  target: activity.target.name,
                })
              : activity.time}
          </span>
          {activity.generation_mode ? (
            <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-600">
              {activity.generation_mode === "llm"
                ? t("post.llmReply")
                : t("post.ruleReply")}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 text-sm leading-6 text-stone-700">{content}</p>
        <button
          type="button"
          onClick={onReply}
          className="focus-ring mt-1 inline-flex min-h-8 items-center gap-1.5 rounded-md px-2 text-xs font-semibold text-stone-600 transition hover:bg-stone-100 hover:text-teal-800"
        >
          <Reply className="h-3.5 w-3.5" aria-hidden="true" />
          {t("post.reply")}
        </button>
      </div>
    </div>
  );
}

function ConversationThread({
  thread,
  postId,
  disabled,
  onThreadReply,
}: {
  thread: CommentThread;
  postId: number;
  disabled: boolean;
  onThreadReply: PostCardProps["onThreadReply"];
}) {
  const { t } = useLanguage();
  const identity=useSocialIdentity();
  const name=identity.name(thread.targetAgentId,thread.targetAgentName);
  return (
    <div className="space-y-3 border-l-2 border-teal-200 pl-3">
      {thread.exchanges.map((exchange) => (
        <div key={exchange.id} className="space-y-3">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold text-teal-700"><SocialAvatar agentId={0} name={identity.name(0,t("post.you"))} size={28}/>{identity.name(0,t("post.you"))}</p>
            <p className="mt-1 text-sm leading-6 text-stone-800">
              {exchange.userComment}
            </p>
          </div>
          {exchange.isLoading ? (
            <p className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-600">
              {t("post.replying", { name: thread.targetAgentName })}
            </p>
          ) : null}
          {exchange.agentReply ? (
            <div className="rounded-md border border-teal-100 bg-teal-50 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2"><SocialAvatar agentId={thread.targetAgentId} name={name} size={28}/>
                <p className="text-xs font-semibold text-teal-800">
                  {name}
                </p>
                {process.env.NODE_ENV === "development" && exchange.generationMode ? (
                  <span className="rounded-sm bg-white px-1.5 py-0.5 text-[11px] font-medium text-stone-500">
                    {exchange.generationMode === "llm"
                      ? t("post.llmReply")
                      : t("post.ruleReply")}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-sm leading-6 text-stone-800">
                {exchange.agentReply}
              </p>
            </div>
          ) : null}
          {exchange.error ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {exchange.error}
            </p>
          ) : null}
        </div>
      ))}
      <ThreadReplyInput
        thread={thread}
        postId={postId}
        disabled={disabled}
        onThreadReply={onThreadReply}
      />
    </div>
  );
}

function ThreadReplyInput({
  thread,
  postId,
  disabled,
  onThreadReply,
}: {
  thread: CommentThread;
  postId: number;
  disabled: boolean;
  onThreadReply: PostCardProps["onThreadReply"];
}) {
  const { t } = useLanguage();
  const latestAgentReplyId = [...thread.exchanges]
    .reverse()
    .find((exchange) => exchange.agentReplyInteractionId)?.agentReplyInteractionId;
  const isWaiting = thread.exchanges.some((exchange) => exchange.isLoading);

  if (!latestAgentReplyId) return null;

  return (
    <div className="border-t border-stone-200 pt-3">
      <CommentInput
        onSubmit={(content) =>
          onThreadReply(
            postId,
            thread.id,
            thread.targetAgentId,
            latestAgentReplyId,
            content,
          )
        }
        disabled={disabled || isWaiting}
        placeholder={t("post.replyTo", { name: thread.targetAgentName })}
        submitLabel={t("post.reply")}
      />
    </div>
  );
}
