"use client";
import {SocialIdentityProvider} from "./SocialIdentity";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  Bell,
  CalendarDays,
  ChevronRight,
  ClipboardCheck,
  Flag,
  RotateCw,
  X,
} from "lucide-react";

import PostCard, {
  CommentExchange,
  CommentTarget,
  CommentThread,
} from "@/components/PostCard";
import { PrivateMessages } from "./PrivateMessages";
import { PhoneActivityComposer } from "@/components/social/PhoneActivityComposer";
import PostComposer from "@/components/PostComposer";
import {
  advanceSessionDay,
  createAgentReply,
  finishSession as finishSessionApi,
  getSessionFeed,
  getWorldPhone,
  InteractionRecord,
  markNotificationRead,
  publishUserPost,
  saveInteraction,
  SimulationFeed,
  SimulationNotification,
  SimulationPost,
  PhoneInvitationCard,
  respondWorldPhoneInvitation,
  viewWorldPhonePost,
} from "@/lib/api";
import { TranslationKey, useLanguage } from "@/lib/i18n";

type LocalStats = {
  views: number;
  likes: number;
  skips: number;
  comments: number;
  agentReplies: number;
};

type PostFeedback = {
  liked: boolean;
  skipped: boolean;
  comments: CommentThread[];
};

type SavedNotice = {
  key: TranslationKey;
  values?: Record<string, string | number>;
};

const EMPTY_STATS: LocalStats = {
  views: 0,
  likes: 0,
  skips: 0,
  comments: 0,
  agentReplies: 0,
};

export type SocialFeedPanelProps = {
  v5Enabled?: boolean;
  sessionId?: number;
  embedded?: boolean;
  initialFilter?: "all" | "invitations";
  mutationsDisabled?: boolean;
  onClose?: () => void;
  onWorldChanged?: () => void;
  onUnreadCountChange?: (count: number) => void;
};

export default function SocialFeedPanel({
  sessionId: providedSessionId, v5Enabled=false,
  embedded = false,
  initialFilter = "all",
  mutationsDisabled = false,
  onClose,
  onWorldChanged,
  onUnreadCountChange,
}: SocialFeedPanelProps) {
  const router = useRouter();
  const { language, t } = useLanguage();
  const [feed, setFeed] = useState<SimulationFeed | null>(null);
  const [phoneInvitations, setPhoneInvitations] = useState<Record<number, PhoneInvitationCard>>({});
  const [postFeedback, setPostFeedback] = useState<Record<number, PostFeedback>>({});
  const sessionIdRef = useRef<number | null>(null);
  const scrollRef = useRef<HTMLElement>(null);
  const pendingViews=useRef<Set<number>>(new Set());
  const viewedPostIdsRef = useRef<Set<number>>(new Set());
  const postShownAtRef = useRef<Record<number, number>>({});
  const pendingCommentIdRef = useRef(0);
  const [stats, setStats] = useState<LocalStats>(EMPTY_STATS);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isAdvancing, setIsAdvancing] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [error, setError] = useState("");
  const [lastSaved, setLastSaved] = useState<SavedNotice | null>(null);
  const [announcedDay, setAnnouncedDay] = useState<number | null>(null);
  const [activeFilter, setActiveFilter] = useState<"all" | "invitations" | "messages">(initialFilter);
  const languageRef = useRef(language);
  const translationRef = useRef(t);

  useEffect(() => {
    languageRef.current = language;
    translationRef.current = t;
  }, [language, t]);

  const recordPostViews = useCallback(
    async (loadedPosts: SimulationPost[], sessionId: number) => {
      await Promise.all(
        loadedPosts.map(async (post) => {
          if (viewedPostIdsRef.current.has(post.id)||pendingViews.current.has(post.id)) return;
          pendingViews.current.add(post.id);
          try {
            await saveInteraction({
              session_id: sessionId,
              post_id: post.id,
              agent_id: post.agent_id,
              event_type: "post_view",
              response_latency_ms: 0,
              metadata: {
                source: "visible_in_viewport",
                simulation_day: post.day,
                language: languageRef.current,
              },
            });
            viewedPostIdsRef.current.add(post.id);
            setStats((current) => ({ ...current, views: current.views + 1 }));
          } catch {
            setError(translationRef.current("error.recordPostView"));
          } finally {pendingViews.current.delete(post.id);}
        }),
      );
    },
    [],
  );

  const applySnapshot = useCallback(
    (snapshot: SimulationFeed) => {
      const now = Date.now();
      snapshot.posts.forEach((post) => {
        postShownAtRef.current[post.id] = postShownAtRef.current[post.id] ?? now;
      });
      viewedPostIdsRef.current = new Set(
        snapshot.user_interactions
          .filter((item) => item.event_type === "post_view")
          .map((item) => item.post_id),
      );
      setFeed(snapshot);
      setPostFeedback(hydrateFeedback(snapshot.user_interactions, snapshot.posts));
      setStats(statsFromInteractions(snapshot.user_interactions));

    },
    [],
  );

  const loadFeed = useCallback(
    async (sessionId: number) => {
      const [snapshot, phone] = await Promise.all([
        getSessionFeed(sessionId),
        getWorldPhone(sessionId).catch(() => null),
      ]);
      applySnapshot(snapshot);
      if (phone) {
        const invitations = Object.fromEntries(
          phone.posts
            .filter((post): post is PhoneInvitationCard => post.post_type === "invitation")
            .map((post) => [post.post_id, post]),
        );
        setPhoneInvitations(invitations);

      } else {
        setPhoneInvitations({});
      }
      return snapshot;
    },
    [applySnapshot],
  );

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const urlSessionId = Number(urlParams.get("session_id"));
    const urlLanguage = urlParams.get("language");
    const storedSessionId = Number(localStorage.getItem("session_id"));
    const activeSessionId = providedSessionId || urlSessionId || storedSessionId;

    if (!activeSessionId && !embedded) {
      router.replace("/setup");
      return;
    }
    if (!activeSessionId) return;

    sessionIdRef.current = activeSessionId;
    localStorage.setItem("session_id", String(activeSessionId));

    if (urlSessionId && !embedded) {
      const cleanUrl =
        urlLanguage === "en" || urlLanguage === "zh-CN"
          ? `/feed?language=${encodeURIComponent(urlLanguage)}`
          : "/feed";
      window.history.replaceState(null, "", cleanUrl);
    }

    const loadTimer = window.setTimeout(() => {
      loadFeed(activeSessionId)
        .catch(() => setError(translationRef.current("error.loadFeed")))
        .finally(() => setIsLoading(false));
    }, 0);
    return () => window.clearTimeout(loadTimer);
  }, [embedded, loadFeed, providedSessionId, router]);

  useEffect(() => {
    if (!embedded || isSaving) return;
    const timer = window.setInterval(() => {
      const sid = sessionIdRef.current;
      if (!sid || document.visibilityState !== "visible") return;
      const position = scrollRef.current?.scrollTop ?? 0;
      void loadFeed(sid).then(() => window.requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = position;
      })).catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [embedded, isSaving, loadFeed]);

  const posts = useMemo(
    () =>
      (feed?.posts ?? []).filter(
        (post) =>
          !(postFeedback[post.id]?.skipped ?? false) &&
          (activeFilter === "invitations" ? Boolean(phoneInvitations[post.id]) : !phoneInvitations[post.id] && post.post_type !== "announcement"),
      ),
    [activeFilter, feed?.posts, postFeedback, phoneInvitations],
  );
  const timelineCurrentDay = feed?.timeline.current_day;
  useEffect(() => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const id = Number((entry.target as HTMLElement).dataset.feedPostId);
        const post = posts.find(p => p.id === id);
        if (post) {void recordPostViews([post], sid); if (phoneInvitations[id]) void viewWorldPhonePost(sid, id).catch(() => undefined);}
        observer.unobserve(entry.target);
      }
    }, {threshold: 0.25});
    document.querySelectorAll('[data-feed-post-id]').forEach(node => observer.observe(node));
    return () => observer.disconnect();
  }, [posts, phoneInvitations, recordPostViews]);
  const currentPosts = posts.filter((post) => activeFilter === "invitations" ? ["proposed","accepted","in_progress"].includes(phoneInvitations[post.id]?.status) : post.day === timelineCurrentDay);
  const earlierPosts = posts.filter((post) => activeFilter === "invitations" ? !["proposed","accepted","in_progress"].includes(phoneInvitations[post.id]?.status) : post.day !== timelineCurrentDay);
  // Opening the phone acknowledges notifications; pending RSVP is not unread.
  const unreadCount = 0;
  useEffect(() => {if (providedSessionId && feed) sessionStorage.setItem(`phone-seen:${providedSessionId}`, String(Math.max(0,...feed.posts.map(p=>p.id))));}, [providedSessionId,feed]);
  useEffect(() => {
    onUnreadCountChange?.(unreadCount);
  }, [onUnreadCountChange, unreadCount]);
  const totalInteractions = useMemo(
    () => stats.views + stats.likes + stats.skips + stats.comments + stats.agentReplies,
    [stats],
  );

  async function respondToInvitation(
    postId: number,
    response: "accept" | "reject" | "defer" | "withdraw",
  ) {
    const invitation = phoneInvitations[postId];
    const sessionId = sessionIdRef.current;
    if (!invitation || !sessionId || isSaving || mutationsDisabled) return;
    setIsSaving(true);
    setError("");
    try {
      await respondWorldPhoneInvitation(sessionId, postId, {
        response,
        expected_revision: invitation.revision,
        reason_code: `participant_phone_${response}`,
        idempotency_key: `phone-ui-${response}-${postId}-${invitation.revision}`,
      });
      await loadFeed(sessionId);
      onWorldChanged?.();
    } catch {
        await loadFeed(sessionId);
      setError(language === "zh-CN" ? "邀约状态已变化，请刷新后重试。" : "The invitation changed. Refresh and try again.");
    } finally {
      setIsSaving(false);
    }
  }

  async function recordInteraction(
    postId: number,
    actionType: "like" | "unlike" | "skip",
  ) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;

    const post = feed?.posts.find((item) => item.id === postId);
    if (!post) return;
    const wasLiked = postFeedback[postId]?.liked ?? false;
    if (actionType === "like" && wasLiked) return;
    if (actionType === "unlike" && !wasLiked) return;

    setIsSaving(true);
    setError("");
    setLastSaved(null);

    try {
      await saveInteraction({
        session_id: sessionId,
        post_id: postId,
        agent_id: post.agent_id,
        event_type: actionType,
        response_latency_ms: latencyForPost(postId),
        metadata: {
          language,
          simulation_day: feed?.timeline.current_day,
          post_day: post.day,
        },
      });

      setPostFeedback((current) => ({
        ...current,
        [postId]: {
          liked:
            actionType === "like"
              ? true
              : actionType === "unlike"
                ? false
                : current[postId]?.liked ?? false,
          skipped:
            actionType === "skip"
              ? true
              : current[postId]?.skipped ?? false,
          comments: current[postId]?.comments ?? [],
        },
      }));

      if (actionType === "like") {
        setLastSaved({ key: "feed.likeSaved" });
      } else if (actionType === "unlike") {
        setLastSaved({ key: "feed.likeRemoved" });
      } else {
        setLastSaved({
          key: "feed.skippedNamed",
          values: { name: post.agent_name },
        });
      }

      setStats((current) => ({
        ...current,
        likes: Math.max(
          current.likes +
            (actionType === "like" ? 1 : 0) -
            (actionType === "unlike" ? 1 : 0),
          0,
        ),
        skips: current.skips + (actionType === "skip" ? 1 : 0),
      }));
    } catch {
      setError(t("error.saveInteraction"));
    } finally {
      setIsSaving(false);
    }
  }

  async function submitComment(
    postId: number,
    content: string,
    target: CommentTarget,
  ) {
    const sessionId = sessionIdRef.current;
    const post = feed?.posts.find((item) => item.id === postId);
    if (!sessionId || !post) return;

    pendingCommentIdRef.current += 1;
    const tempId = `pending-${postId}-${pendingCommentIdRef.current}`;
    setPostFeedback((current) => ({
      ...current,
      [postId]: {
        liked: current[postId]?.liked ?? false,
        skipped: current[postId]?.skipped ?? false,
        comments: [
          ...(current[postId]?.comments ?? []).filter(thread=>!(thread.targetAgentId===target.targetAgentId&&thread.exchanges.some(e=>e.userComment===content&&e.error))),
          {
            id: tempId,
            targetAgentId: target.targetAgentId,
            targetAgentName: target.targetAgentName,
            parentCommunityActivityId: target.parentCommunityActivityId,
            exchanges: [
              {
                id: tempId,
                userComment: content,
                isLoading: true,
              },
            ],
          },
        ],
      },
    }));

    setIsSaving(true);
    setError("");
    setLastSaved(null);
    try {
      const result = await createAgentReply({
        session_id: sessionId,
        post_id: postId,
        agent_id: target.targetAgentId,
        user_comment: content,
        parent_community_activity_id: target.parentCommunityActivityId,
        response_latency_ms: latencyForPost(postId),
        language,
      });
      setPostFeedback((current) => ({
        ...current,
        [postId]: {
          liked: current[postId]?.liked ?? false,
          skipped: current[postId]?.skipped ?? false,
          comments: (current[postId]?.comments ?? []).map((thread) =>
            thread.id === tempId
              ? {
                  id: String(result.comment.interaction_id),
                  targetAgentId: target.targetAgentId,
                  targetAgentName: target.targetAgentName,
                  parentCommunityActivityId: target.parentCommunityActivityId,
                  exchanges: [
                    {
                      id: String(result.comment.interaction_id),
                      userInteractionId: result.comment.interaction_id,
                      userComment: result.comment.content,
                      agentReply: result.agent_reply.content,
                      agentReplyInteractionId: result.agent_reply.interaction_id,
                      isLoading: false,
                      generationMode: String(
                        result.generation_metadata.generation_mode ?? "",
                      ),
                      safetyFlag: result.agent_reply.safety_flag,
                    },
                  ],
                }
              : thread,
          ),
        },
      }));
      setStats((current) => ({
        ...current,
        comments: current.comments + 1,
        agentReplies: current.agentReplies + 1,
      }));
      setLastSaved({ key: "feed.commentSaved" });
      window.dispatchEvent(new Event('v5-guides-changed'));
      onWorldChanged?.();
    } catch (failure) {
      const message = failure instanceof Error && /[\u4e00-\u9fff]/.test(failure.message) ? failure.message : t("error.saveComment");
      setPostFeedback((current) => ({
        ...current,
        [postId]: {
          liked: current[postId]?.liked ?? false,
          skipped: current[postId]?.skipped ?? false,
          comments: (current[postId]?.comments ?? []).map((thread) =>
            thread.id === tempId
              ? {
                  ...thread,
                  exchanges: thread.exchanges.map((exchange) =>
                    exchange.id === tempId
                      ? {
                          ...exchange,
                          isLoading: false,
                          error: message,
                        }
                      : exchange,
                  ),
                }
              : thread,
          ),
        },
      }));
      setError(message);
      throw failure;
    } finally {
      setIsSaving(false);
    }
  }

  async function submitThreadReply(
    postId: number,
    threadId: string,
    targetAgentId: number,
    parentInteractionId: number,
    content: string,
  ) {
    const sessionId = sessionIdRef.current;
    const post = feed?.posts.find((item) => item.id === postId);
    if (!sessionId || !post) return;

    pendingCommentIdRef.current += 1;
    const tempId = `pending-reply-${postId}-${pendingCommentIdRef.current}`;
    setPostFeedback((current) => ({
      ...current,
      [postId]: {
        liked: current[postId]?.liked ?? false,
        skipped: current[postId]?.skipped ?? false,
        comments: (current[postId]?.comments ?? []).map((thread) =>
          thread.id === threadId
            ? {
                ...thread,
                exchanges: [
                  ...thread.exchanges,
                  {
                    id: tempId,
                    userComment: content,
                    isLoading: true,
                  },
                ],
              }
            : thread,
        ),
      },
    }));

    setIsSaving(true);
    setError("");
    setLastSaved(null);
    try {
      const result = await createAgentReply({
        session_id: sessionId,
        post_id: postId,
        agent_id: targetAgentId,
        user_comment: content,
        parent_interaction_id: parentInteractionId,
        response_latency_ms: latencyForPost(postId),
        language,
      });
      setPostFeedback((current) => ({
        ...current,
        [postId]: {
          liked: current[postId]?.liked ?? false,
          skipped: current[postId]?.skipped ?? false,
          comments: (current[postId]?.comments ?? []).map((thread) =>
            thread.id === threadId
              ? {
                  ...thread,
                  exchanges: thread.exchanges.map((exchange) =>
                    exchange.id === tempId
                      ? {
                          id: String(result.comment.interaction_id),
                          userInteractionId: result.comment.interaction_id,
                          userComment: result.comment.content,
                          agentReply: result.agent_reply.content,
                          agentReplyInteractionId:
                            result.agent_reply.interaction_id,
                          isLoading: false,
                          generationMode: String(
                            result.generation_metadata.generation_mode ?? "",
                          ),
                          safetyFlag: result.agent_reply.safety_flag,
                        }
                      : exchange,
                  ),
                }
              : thread,
          ),
        },
      }));
      setStats((current) => ({
        ...current,
        comments: current.comments + 1,
        agentReplies: current.agentReplies + 1,
      }));
      setLastSaved({ key: "feed.replySaved" });
      window.dispatchEvent(new Event('v5-guides-changed'));
      onWorldChanged?.();
    } catch {
      const message = t("error.saveReply");
      setPostFeedback((current) => ({
        ...current,
        [postId]: {
          liked: current[postId]?.liked ?? false,
          skipped: current[postId]?.skipped ?? false,
          comments: (current[postId]?.comments ?? []).map((thread) =>
            thread.id === threadId
              ? {
                  ...thread,
                  exchanges: thread.exchanges.map((exchange) =>
                    exchange.id === tempId
                      ? {
                          ...exchange,
                          isLoading: false,
                          error: message,
                        }
                      : exchange,
                  ),
                }
              : thread,
          ),
        },
      }));
      setError(message);
    } finally {
      setIsSaving(false);
    }
  }

  async function submitNewPost(content: string) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;

    setIsSaving(true);
    setError("");
    setLastSaved(null);
    try {
      await publishUserPost(
        sessionId,
        content,
        language,
        globalThis.crypto?.randomUUID?.() ?? `post-${Date.now()}`,
      );
      await loadFeed(sessionId);
      onWorldChanged?.();
      setLastSaved({ key: "feed.postPublished" });
    } catch {
      setError(t("error.publishPost"));
      throw new Error("publish failed");
    } finally {
      setIsSaving(false);
    }
  }

  async function goToNextDay() {
    const sessionId = sessionIdRef.current;
    const currentDay = feed?.timeline.current_day;
    if (!sessionId || !currentDay || isAdvancing) return;

    setIsAdvancing(true);
    setError("");
    setLastSaved(null);
    setAnnouncedDay(null);
    try {
      const result = await advanceSessionDay(sessionId, currentDay);
      await loadFeed(sessionId);
      setAnnouncedDay(result.current_day);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch {
      setError(t("error.advanceDay"));
    } finally {
      setIsAdvancing(false);
    }
  }

  async function finishSession() {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    setIsSaving(true);
    setError("");
    try {
      await finishSessionApi(sessionId);
      router.push("/result");
    } catch {
      setError(t("error.finishSession"));
    } finally {
      setIsSaving(false);
    }
  }

  async function openNotification(notification: SimulationNotification) {
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    setNotificationsOpen(false);

    if (!notification.is_read) {
      setFeed((current) =>
        current
          ? {
              ...current,
              notifications: current.notifications.map((item) =>
                item.notification_id === notification.notification_id
                  ? { ...item, is_read: true }
                  : item,
              ),
            }
          : current,
      );
      try {
        await markNotificationRead(sessionId, notification.notification_id);
      } catch {
        setError(t("error.readNotification"));
      }
    }

    if (notification.post_id) {
      window.setTimeout(() => {
        document
          .getElementById(`post-${notification.post_id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 0);
    }
  }

  function latencyForPost(postId: number) {
    const shownAt = postShownAtRef.current[postId];
    if (!shownAt) return undefined;
    return Math.max(Date.now() - shownAt, 0);
  }

  const currentDay = feed?.timeline.current_day ?? 1;
  const totalDays = feed?.timeline.total_days ?? 7;
  const isFinalDay = currentDay >= totalDays;
  const virtualDate = feed?.timeline.virtual_date
    ? formatVirtualDate(feed.timeline.virtual_date, language)
    : "";

  return (
    <SocialIdentityProvider sessionId={providedSessionId??feed?.session.session_id} nickname={feed?.session.nickname??"你"} enabled={v5Enabled}><main ref={scrollRef} className={embedded ? "h-full overflow-y-auto bg-stone-50 px-3 pb-5 pt-3 sm:px-5" : "min-h-screen px-5 pb-8 pt-20 sm:px-8"}>
      <div className={embedded ? "mx-auto max-w-5xl" : "mx-auto max-w-6xl"}>
        <header className="relative flex flex-col gap-5 border-b border-stone-200 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-teal-700">
              <span>{t("feed.eyebrow")}</span>
              <span className="text-stone-300">/</span>
              <span>{t("feed.dayProgress", { current: currentDay, total: totalDays })}</span>
            </div>
            <h1 className="mt-2 text-3xl font-bold text-stone-950">
              {t("feed.title")}
            </h1>
            <p className="mt-2 text-sm font-medium text-stone-700">
              {virtualDate}
            </p>
            <p className="mt-1 max-w-2xl text-sm text-stone-600">
              {language === "zh-CN" ? "看看朋友们的近况，或约一段一起度过的时光。" : "Updates from island friends and invitations to spend time together."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {embedded && onClose ? (
              <button
                type="button"
                data-testid="social-phone-close"
                onClick={onClose}
                className="focus-ring inline-flex h-11 w-11 items-center justify-center rounded-md border border-stone-300 bg-white text-stone-700 hover:bg-stone-50"
                aria-label={language === "zh-CN" ? "关闭手机" : "Close phone"}
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            ) : null}
            <div className="relative">
              <button
                type="button"
                onClick={() => setNotificationsOpen((current) => !current)}
                className="focus-ring relative inline-flex h-11 w-11 items-center justify-center rounded-md border border-stone-300 bg-white text-stone-700 transition hover:bg-stone-50"
                title={
                  notificationsOpen
                    ? t("feed.closeNotifications")
                    : t("feed.openNotification")
                }
                aria-label={t("feed.notifications")}
                aria-expanded={notificationsOpen}
              >
                <Bell className="h-5 w-5" aria-hidden="true" />
                {unreadCount > 0 ? (
                  <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-600 px-1 text-[11px] font-bold text-white">
                    {unreadCount}
                  </span>
                ) : null}
              </button>
              {notificationsOpen ? (
                <NotificationPanel
                  notifications={feed?.notifications ?? []}
                  unreadCount={unreadCount}
                  onClose={() => setNotificationsOpen(false)}
                  onOpen={openNotification}
                />
              ) : null}
            </div>

            {!embedded && !isFinalDay ? (
              <button
                type="button"
                onClick={goToNextDay}
                disabled={isAdvancing || isSaving || isLoading}
                className="focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-teal-700 px-5 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isAdvancing ? (
                  <RotateCw className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <CalendarDays className="h-4 w-4" aria-hidden="true" />
                )}
                {isAdvancing ? t("feed.advancing") : t("feed.nextDay")}
                {!isAdvancing ? (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                ) : null}
              </button>
            ) : !embedded ? (
              <button
                type="button"
                onClick={finishSession}
                disabled={isSaving}
                className="focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-stone-950 px-5 text-sm font-semibold text-white transition hover:bg-stone-800 disabled:opacity-60"
              >
                <Flag className="h-4 w-4" aria-hidden="true" />
                {t("feed.finish")}
              </button>
            ) : null}
          </div>
        </header>

        <nav className="mt-4 flex flex-wrap gap-2" aria-label={language === "zh-CN" ? "社交动态筛选" : "Social feed filters"}>
          <button type="button" data-testid="social-filter-all" aria-pressed={activeFilter === "all"} onClick={() => setActiveFilter("all")} className={`focus-ring min-h-10 rounded-full px-4 text-sm font-bold ${activeFilter === "all" ? "bg-teal-800 text-white" : "border border-stone-300 bg-white text-stone-700"}`}>{language === "zh-CN" ? "动态" : "Updates"}</button>
          <button type="button" data-testid="social-filter-invitations" aria-pressed={activeFilter === "invitations"} onClick={() => setActiveFilter("invitations")} className={`focus-ring min-h-10 rounded-full px-4 text-sm font-bold ${activeFilter === "invitations" ? "bg-teal-800 text-white" : "border border-stone-300 bg-white text-stone-700"}`}>{language === "zh-CN" ? "邀约" : "Invitations"}</button>
          {v5Enabled && <button data-testid="social-filter-messages" className="focus-ring rounded-full border bg-white px-4 py-2 font-bold" aria-pressed={activeFilter === 'messages'} onClick={()=>setActiveFilter('messages')}>私信</button>}
          {feed ? <span data-testid="social-world-time" className="ml-auto self-center rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold text-amber-950">{language === "zh-CN" ? `第 ${feed.timeline.current_day} 天 · ${feed.timeline.current_time}` : `Day ${feed.timeline.current_day} · ${feed.timeline.current_time}`}</span> : null}
        </nav>

        {v5Enabled && providedSessionId && activeFilter === 'messages' && <PrivateMessages sessionId={providedSessionId} disabled={mutationsDisabled} onChanged={()=>onWorldChanged?.()} />}
        <div hidden={activeFilter === 'messages'} className={activeFilter === 'messages' ? 'hidden' : 'mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]'}>
          <section className="min-w-0 space-y-4">
            {activeFilter === "invitations" && providedSessionId ? <PhoneActivityComposer sessionId={providedSessionId} language={language} disabled={mutationsDisabled} onChanged={() => {void loadFeed(providedSessionId); onWorldChanged?.();}} /> : null}
            {!isLoading && feed && activeFilter === "all" ? (
              <PostComposer
                nickname={feed.session.nickname}
                disabled={isSaving || isAdvancing || mutationsDisabled}
                onSubmit={submitNewPost}
              />
            ) : null}

            {isLoading ? (
              <StatusPanel
                icon={<RotateCw className="h-5 w-5 animate-spin" />}
                text={t("feed.loading")}
              />
            ) : null}

            {error ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                {error}
              </p>
            ) : null}

            {announcedDay ? (
              <p className="rounded-md border border-teal-200 bg-teal-50 px-4 py-3 text-sm font-medium text-teal-900">
                {t("feed.newDayReady", { day: announcedDay })}
              </p>
            ) : null}

            {lastSaved ? (
              <p className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                {t(lastSaved.key, lastSaved.values)}
              </p>
            ) : null}

            {currentPosts.length > 0 ? (
              <PostGroup
                title={t("feed.today")}
                posts={currentPosts}
                currentDay={currentDay}
                postFeedback={postFeedback}
                phoneInvitations={phoneInvitations}
                disabled={isSaving || isAdvancing || mutationsDisabled}
                onLike={(postId) => recordInteraction(postId, "like")}
                onUnlike={(postId) => recordInteraction(postId, "unlike")}
                onSkip={(postId) => recordInteraction(postId, "skip")}
                onComment={submitComment}
                onThreadReply={submitThreadReply}
                onInvitationResponse={respondToInvitation}
              />
            ) : null}

            {activeFilter === "invitations" && earlierPosts.length>0 && <hr className="my-6 border-stone-300" aria-label="历史邀约分割线"/>}
            {earlierPosts.length > 0 ? (
              <PostGroup
                title={activeFilter === "invitations" ? "历史邀约 · 已结束、取消或过期" : t("feed.earlierPosts")}
                posts={earlierPosts}
                currentDay={currentDay}
                postFeedback={postFeedback}
                phoneInvitations={phoneInvitations}
                disabled={isSaving || isAdvancing || mutationsDisabled}
                onLike={(postId) => recordInteraction(postId, "like")}
                onUnlike={(postId) => recordInteraction(postId, "unlike")}
                onSkip={(postId) => recordInteraction(postId, "skip")}
                onComment={submitComment}
                onThreadReply={submitThreadReply}
                onInvitationResponse={respondToInvitation}
              />
            ) : null}

            {!isLoading && posts.length === 0 ? (
              <div className="rounded-lg border border-stone-200 bg-white p-6 text-center shadow-sm">
                <p className="text-base font-semibold text-stone-950">
                  {t("feed.emptyTitle")}
                </p>
                <p className="mt-2 text-sm text-stone-600">
                  {t("feed.emptyDescription")}
                </p>
              </div>
            ) : null}
          </section>

          {!embedded ? <aside className="h-fit rounded-lg border border-stone-200 bg-white p-5 shadow-sm lg:sticky lg:top-20">
            <div className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-teal-700" aria-hidden="true" />
              <h2 className="text-base font-semibold text-stone-950">
                {t("feed.timeline")}
              </h2>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              {(feed?.timeline.days ?? []).map((day) => (
                <DayStatus
                  key={day.day}
                  day={day.day}
                  date={day.date}
                  currentDay={currentDay}
                  unlocked={day.is_unlocked}
                />
              ))}
            </div>
            <p className="mt-4 text-xs leading-5 text-stone-500">
              {isFinalDay ? t("feed.finalDayHint") : t("feed.nextDayHint")}
            </p>

            <div className="mt-5 border-t border-stone-200 pt-5">
              <div className="flex items-center gap-2">
                <ClipboardCheck className="h-5 w-5 text-teal-700" aria-hidden="true" />
                <h2 className="text-base font-semibold text-stone-950">
                  {t("feed.progress")}
                </h2>
              </div>
              <dl className="mt-4 space-y-3">
                <ProgressRow label={t("feed.visiblePosts")} value={posts.length} />
                <ProgressRow label={t("feed.viewsRecorded")} value={stats.views} />
                <ProgressRow label={t("feed.likes")} value={stats.likes} />
                <ProgressRow label={t("feed.skips")} value={stats.skips} />
                <ProgressRow label={t("feed.comments")} value={stats.comments} />
                <ProgressRow label={t("feed.agentReplies")} value={stats.agentReplies} />
                <ProgressRow
                  label={t("feed.recordedActions")}
                  value={totalInteractions}
                />
              </dl>
            </div>

            {!isFinalDay ? (
              <button
                type="button"
                onClick={finishSession}
                disabled={isSaving || isAdvancing}
                className="focus-ring mt-5 inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-md border border-stone-300 bg-white px-3 text-sm font-medium text-stone-700 transition hover:bg-stone-50 disabled:opacity-60"
              >
                <Flag className="h-4 w-4" aria-hidden="true" />
                {t("feed.finish")}
              </button>
            ) : null}
          </aside> : null}
        </div>
      </div>
    </main></SocialIdentityProvider>
  );
}

function PostGroup({
  title,
  posts,
  currentDay,
  postFeedback,
  phoneInvitations,
  disabled,
  onLike,
  onUnlike,
  onSkip,
  onComment,
  onThreadReply,
  onInvitationResponse,
}: {
  title: string;
  posts: SimulationPost[];
  currentDay: number;
  postFeedback: Record<number, PostFeedback>;
  phoneInvitations: Record<number, PhoneInvitationCard>;
  disabled: boolean;
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
  onInvitationResponse: (
    postId: number,
    response: "accept" | "reject" | "defer" | "withdraw",
  ) => Promise<void> | void;
}) {
  return (
    <Fragment>
      <div className="flex items-center gap-3 py-1">
        <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
        <h2 className="text-xs font-semibold uppercase text-stone-500">{title}</h2>
        <span className="h-px flex-1 bg-stone-200" aria-hidden="true" />
      </div>
      {posts.map((post) => (
        <div key={post.id} data-feed-post-id={post.id}><PostCard
          post={post}
          currentDay={currentDay}
          liked={postFeedback[post.id]?.liked ?? false}
          comments={postFeedback[post.id]?.comments ?? []}
          onLike={onLike}
          onUnlike={onUnlike}
          onSkip={onSkip}
          onComment={onComment}
          onThreadReply={onThreadReply}
          disabled={disabled}
          invitation={phoneInvitations[post.id]}
          onInvitationResponse={(response) => onInvitationResponse(post.id, response)}
        /></div>
      ))}
    </Fragment>
  );
}

function NotificationPanel({
  notifications,
  unreadCount,
  onClose,
  onOpen,
}: {
  notifications: SimulationNotification[];
  unreadCount: number;
  onClose: () => void;
  onOpen: (notification: SimulationNotification) => Promise<void> | void;
}) {
  const { language, t } = useLanguage();
  return (
    <section className="absolute right-0 z-30 mt-2 w-[min(22rem,calc(100vw-2.5rem))] rounded-lg border border-stone-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-stone-950">
            {t("feed.notifications")}
          </h2>
          <p className="mt-0.5 text-xs text-stone-500">
            {t("feed.unreadNotifications", { count: unreadCount })}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-md text-stone-500 transition hover:bg-stone-100"
          title={t("feed.closeNotifications")}
          aria-label={t("feed.closeNotifications")}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {notifications.length > 0 ? (
        <div className="max-h-80 overflow-y-auto py-1">
          {notifications.map((notification) => (
            <button
              key={notification.notification_id}
              type="button"
              onClick={() => onOpen(notification)}
              className={`focus-ring block w-full border-b border-stone-100 px-4 py-3 text-left transition last:border-b-0 hover:bg-stone-50 ${
                notification.is_read ? "bg-white" : "bg-teal-50"
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                    notification.is_read ? "bg-stone-300" : "bg-teal-600"
                  }`}
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <p className="text-sm leading-5 text-stone-800">
                    {notification.translations?.[language]?.content ??
                      notification.content}
                  </p>
                  <p className="mt-1 text-xs text-stone-500">
                    {t("feed.dayLabel", { day: notification.day })}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <p className="px-4 py-6 text-center text-sm text-stone-500">
          {t("feed.noNotifications")}
        </p>
      )}
    </section>
  );
}

function DayStatus({
  day,
  date,
  currentDay,
  unlocked,
}: {
  day: number;
  date: string;
  currentDay: number;
  unlocked: boolean;
}) {
  const { language, t } = useLanguage();
  const status =
    day === currentDay
      ? t("feed.currentDay")
      : unlocked
        ? t("feed.visitedDay")
        : t("feed.lockedDay");
  return (
    <div
      className={`min-h-[72px] rounded-md border px-2 py-2 text-center ${
        day === currentDay
          ? "border-teal-300 bg-teal-50"
          : unlocked
            ? "border-stone-200 bg-white"
            : "border-stone-200 bg-stone-50"
      }`}
    >
      <p
        className={`text-sm font-semibold ${
          day === currentDay ? "text-teal-900" : "text-stone-700"
        }`}
      >
        {new Intl.DateTimeFormat(language, { weekday: "short" }).format(
          new Date(`${date}T12:00:00`),
        )}
      </p>
      <p className="mt-1 text-[11px] leading-4 text-stone-500">
        {t("feed.dayLabel", { day })} · {status}
      </p>
    </div>
  );
}

function ProgressRow({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-sm text-stone-600">{label}</dt>
      <dd className="text-sm font-semibold tabular-nums text-stone-950">{value}</dd>
    </div>
  );
}

function StatusPanel({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-stone-200 bg-white px-4 py-3 text-sm text-stone-600">
      {icon}
      {text}
    </div>
  );
}

function statsFromInteractions(interactions: InteractionRecord[]): LocalStats {
  const currentLikes = new Map<number, boolean>();
  const stats = { ...EMPTY_STATS };
  for (const interaction of interactions) {
    if (interaction.event_type === "post_view") stats.views += 1;
    if (interaction.event_type === "skip") stats.skips += 1;
    if (interaction.event_type === "comment") stats.comments += 1;
    if (interaction.event_type === "agent_reply") stats.agentReplies += 1;
    if (interaction.event_type === "like") currentLikes.set(interaction.post_id, true);
    if (interaction.event_type === "unlike") currentLikes.set(interaction.post_id, false);
  }
  stats.likes = Array.from(currentLikes.values()).filter(Boolean).length;
  return stats;
}

function hydrateFeedback(
  interactions: InteractionRecord[],
  posts: SimulationPost[],
): Record<number, PostFeedback> {
  const feedback: Record<number, PostFeedback> = {};
  const commentExchangeById = new Map<number, CommentExchange>();
  const threadByCommentId = new Map<number, CommentThread>();
  const threadByAgentReplyId = new Map<number, CommentThread>();
  const activityById = new Map(
    posts.flatMap((post) =>
      post.community_comments.map((activity) => [activity.activity_id, activity] as const),
    ),
  );
  const postById = new Map(posts.map((post) => [post.id, post]));

  const ensurePost = (postId: number) => {
    if (!feedback[postId]) {
      feedback[postId] = { liked: false, skipped: false, comments: [] };
    }
    return feedback[postId];
  };

  for (const interaction of interactions) {
    if (interaction.post_id <= 0) continue;
    const postState = ensurePost(interaction.post_id);

    if (interaction.event_type === "like") {
      postState.liked = true;
    } else if (interaction.event_type === "unlike") {
      postState.liked = false;
    } else if (interaction.event_type === "skip") {
      postState.skipped = true;
    } else if (interaction.event_type === "comment") {
      const exchange: CommentExchange = {
        id: String(interaction.interaction_id),
        userInteractionId: interaction.interaction_id,
        userComment: interaction.content,
        isLoading: false,
        safetyFlag: interaction.safety_flag,
      };
      const existingThread = interaction.parent_interaction_id
        ? threadByAgentReplyId.get(interaction.parent_interaction_id)
        : undefined;
      const parentActivity = interaction.parent_community_activity_id
        ? activityById.get(interaction.parent_community_activity_id)
        : undefined;
      const originalPost = postById.get(interaction.post_id);
      const targetAgentId =
        parentActivity?.actor.agent_id ??
        interaction.agent_id ??
        originalPost?.agent_id ??
        0;
      const targetAgentName =
        parentActivity?.actor.name ??
        (originalPost?.agent_id === targetAgentId
          ? originalPost.agent_name
          : `Agent ${targetAgentId}`);
      const thread =
        existingThread ?? {
          id: String(interaction.interaction_id),
          targetAgentId,
          targetAgentName,
          parentCommunityActivityId:
            interaction.parent_community_activity_id ?? undefined,
          exchanges: [],
        };
      thread.exchanges.push(exchange);
      if (!existingThread) {
        postState.comments.push(thread);
      }
      commentExchangeById.set(interaction.interaction_id, exchange);
      threadByCommentId.set(interaction.interaction_id, thread);
    } else if (
      interaction.event_type === "agent_reply" &&
      interaction.parent_interaction_id
    ) {
      const exchange = commentExchangeById.get(interaction.parent_interaction_id);
      const thread = threadByCommentId.get(interaction.parent_interaction_id);
      if (exchange && thread) {
        exchange.agentReply = interaction.content;
        exchange.agentReplyInteractionId = interaction.interaction_id;
        exchange.generationMode = interaction.generation_mode;
        exchange.safetyFlag = interaction.safety_flag;
        threadByAgentReplyId.set(interaction.interaction_id, thread);
      }
    }
  }

  return feedback;
}

function formatVirtualDate(value: string, language: string) {
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat(language, {
    month: "long",
    day: "numeric",
  }).format(date);
}
