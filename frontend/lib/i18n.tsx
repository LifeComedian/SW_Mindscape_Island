"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type Language = "en" | "zh-CN";

const STORAGE_KEY = "mindscape_language";

const english = {
  "meta.title": "MindScape Island Research Prototype",
  "language.switchToChinese": "简体中文",
  "language.switchToEnglish": "English",
  "language.switchLabel": "Switch language",

  "landing.eyebrow": "Serious game research prototype",
  "landing.title": "MindScape Island",
  "landing.description":
    "Enter a private simulated island, explore its harbor, square, and restaurant, and meet AI residents with their own routines and session-scoped memories.",
  "landing.notice":
    "This is a research prototype. It does not provide medical diagnosis, treatment, or crisis intervention.",
  "landing.start": "Enter the island",
  "landing.preview": "Meet the island residents",
  "landing.staticPosts": "Three residents, three different routines",
  "landing.miraRole": "Library assistant",
  "landing.miraPost":
    "Mira welcomes new arrivals at the harbor before organizing the community shelf.",
  "landing.leoRole": "Cafe helper",
  "landing.leoPost":
    "Leo checks the square's event board, then helps prepare the restaurant for lunch.",
  "landing.novaRole": "Community coordinator",
  "landing.novaPost":
    "Chen keeps the island's practical plans moving and handles everyday booking mix-ups.",

  "setup.back": "Back",
  "setup.title": "Set up your session",
  "setup.description":
    "Create a local research session before arriving on the island.",
  "setup.nickname": "Nickname",
  "setup.nicknamePlaceholder": "Enter a nickname",
  "setup.consent":
    "I understand this is a research prototype, not a medical diagnosis, treatment tool, or crisis service. I consent to storing this session's dialogue, choices, paths, and response timing in the local SQLite database. If this deployment enables an external language-model provider, my conversation text may be sent to that configured provider.",
  "setup.start": "Start session",
  "setup.creating": "Creating session",

  "feed.eyebrow": "Simulated community",
  "feed.title": "Community Feed",
  "feed.subtitle": "Follow a Monday-to-Sunday community timeline as conversations develop.",
  "feed.notice":
    "This research prototype does not provide medical diagnosis or crisis support.",
  "feed.finish": "Finish Session",
  "feed.nextDay": "Next day",
  "feed.advancing": "Preparing next day",
  "feed.dayProgress": "Day {current} of {total}",
  "feed.today": "Today",
  "feed.earlierPosts": "Earlier posts",
  "feed.newDayReady":
    "Day {day} is ready. New posts and conversations have appeared.",
  "feed.loading": "Loading posts...",
  "feed.emptyTitle": "No posts left in the feed.",
  "feed.emptyDescription":
    "You can finish the session and view the feedback report.",
  "feed.progress": "Session progress",
  "feed.visiblePosts": "Visible posts",
  "feed.viewsRecorded": "Views recorded",
  "feed.likes": "Likes",
  "feed.skips": "Skips",
  "feed.comments": "Comments",
  "feed.agentReplies": "Agent replies",
  "feed.recordedActions": "Recorded actions",
  "feed.timeline": "Community timeline",
  "feed.dayLabel": "Day {day}",
  "feed.currentDay": "Current",
  "feed.visitedDay": "Visited",
  "feed.lockedDay": "Upcoming",
  "feed.notifications": "Notifications",
  "feed.unreadNotifications": "{count} unread",
  "feed.noNotifications": "No notifications yet.",
  "feed.openNotification": "Open notification",
  "feed.closeNotifications": "Close notifications",
  "feed.viewPost": "View post",
  "feed.finalDayHint": "This is the final day of the community timeline.",
  "feed.nextDayHint": "Advance when you are ready to reveal tomorrow's activity.",
  "feed.likeSaved": "Like saved. This post is marked as liked.",
  "feed.likeRemoved": "Like removed.",
  "feed.skippedNamed":
    "Skipped {name}'s post. It was removed from the feed.",
  "feed.skippedGeneric": "Skip saved. The post was removed from the feed.",
  "feed.commentSaved": "Comment posted and agent reply saved.",
  "feed.replySaved": "Reply posted and agent response saved.",
  "feed.postPublished": "Your post is live. Community members have started responding.",

  "composer.title": "Create a post",
  "composer.placeholder": "Share something with the community",
  "composer.publish": "Post",
  "composer.publishing": "Posting and generating replies...",

  "post.likedNotice": "You liked this post.",
  "post.commentsTitle": "Your conversations",
  "post.communityDiscussion": "Community discussion",
  "post.yourPost": "Your post",
  "post.replyingTo": "{name} replied to {target}",
  "post.likeCount": "{count} likes",
  "post.commentCount": "{count} comments",
  "post.todayAt": "Today at {time}",
  "post.yesterdayAt": "Yesterday at {time}",
  "post.dayAt": "Day {day} at {time}",
  "post.you": "You",
  "post.replying": "{name} is replying...",
  "post.llmReply": "LLM reply",
  "post.ruleReply": "Rule-based reply",
  "post.replyTo": "Reply to {name}",
  "post.replyToOriginal": "Comment on {name}'s post",
  "post.reply": "Reply",
  "post.commentPlaceholder": "Write a short comment",
  "post.comment": "Comment",
  "post.commentLabel": "Comment",
  "post.sendTitle": "Send comment",
  "post.saving": "Saving",
  "post.like": "Like",
  "post.liked": "Liked",
  "post.likeTitle": "Like post",
  "post.unlikeTitle": "Unlike post",
  "post.skip": "Skip",
  "post.skipTitle": "Skip post",

  "result.back": "Back to island",
  "result.restart": "Restart from start",
  "result.download": "Download research JSON",
  "result.loading": "Checking session status...",
  "result.error": "The session status could not be verified. Check that the backend is running and try again.",
  "result.retry": "Try again",
  "result.eyebrow": "Neutral research debrief",
  "result.title": "Session complete",
  "result.description":
    "Your island interactions have been saved for research review. This participant page does not calculate or display a psychological score.",
  "result.neutralTitle": "Your island record is saved",
  "result.neutralDescription":
    "The prototype does not diagnose, treat, or provide crisis support. Any future research analysis must be performed offline under an approved study protocol.",
  "result.sessionStatus": "Session status: {status}",
  "result.status.active": "active",
  "result.status.completed": "completed",
  "result.status.abandoned": "abandoned",
  "result.calculating": "Calculating feedback...",

  "report.output": "Research prototype output",
  "report.score": "Prototype score",
  "report.signal": "Prototype signal",
  "report.behaviorFeatures": "Behavior features",
  "report.textFeatures": "Text features",
  "report.dataQuality": "Data quality",
  "report.interactionCount": "Interaction count",
  "report.commentCount": "Comment count",
  "report.sufficientData": "Sufficient data",
  "report.yes": "yes",
  "report.no": "no",
  "report.warnings": "Warnings",

  "feature.post_view_count": "Post views",
  "feature.like_count": "Likes",
  "feature.unlike_count": "Unlikes",
  "feature.skip_count": "Skips",
  "feature.comment_count": "Comments",
  "feature.agent_reply_count": "Agent replies",
  "feature.user_post_count": "Posts created",
  "feature.unique_agents_interacted": "Unique agents interacted",
  "feature.engagement_rate": "Engagement rate",
  "feature.skip_rate": "Skip rate",
  "feature.comment_rate": "Comment rate",
  "feature.average_response_latency_ms": "Average response latency (ms)",
  "feature.median_response_latency_ms": "Median response latency (ms)",
  "feature.session_duration_seconds": "Session duration (seconds)",
  "feature.comment_total_word_count": "Comment word count",
  "feature.average_comment_length_words": "Average comment length",
  "feature.negative_word_count": "Negative word count",
  "feature.negative_word_ratio": "Negative word ratio",
  "feature.positive_word_count": "Positive word count",
  "feature.positive_word_ratio": "Positive word ratio",
  "feature.self_reference_count": "Self-reference count",
  "feature.self_reference_ratio": "Self-reference ratio",
  "feature.question_count": "Question count",
  "feature.lexical_diversity": "Lexical diversity",

  "warning.noPostViews": "No post-view events were recorded.",
  "warning.noComments": "No user comments were recorded.",

  "island.eyebrow": "MindScape Island vertical slice",
  "island.title": "Island Community",
  "island.subtitle":
    "Explore the harbor, square, and restaurant. Residents follow their own schedules, while research scenes remain controlled and versioned.",
  "island.notice":
    "This is a non-clinical research prototype. You may leave or skip a scene without penalty.",
  "island.feed": "Community notice board",
  "island.export": "Download research JSON",
  "island.finish": "End session",
  "island.finishing": "Ending session",
  "island.finished":
    "This session has ended and its island record is saved. No psychological score is shown.",
  "island.refresh": "Refresh island",
  "island.refreshing": "Refreshing",
  "island.loading": "Restoring your island...",
  "island.noSessionTitle": "No island session found",
  "island.noSessionDescription":
    "Create a session first, or return using an island link that includes a session id.",
  "island.createSession": "Create a session",
  "island.retry": "Try again",
  "island.day": "Day {day}",
  "island.time": "Island time {time}",
  "island.location": "Current location",
  "island.locations": "Island map",
  "island.current": "You are here",
  "island.travel": "Travel here",
  "island.notConnected": "No travel route is available",
  "island.closed": "Closed",
  "island.scene": "What is happening",
  "island.observe": "Observe",
  "island.approach": "Approach",
  "island.wait": "Wait",
  "island.endDay": "End day",
  "island.residents": "Residents nearby",
  "island.noResidents": "No residents are nearby right now.",
  "island.activity": "Activity",
  "island.goal": "Current goal",
  "island.schedule": "Schedule",
  "island.unknown": "Not shared",
  "island.talk": "Talk",
  "island.conversation": "Conversation",
  "island.chooseResident": "Choose a nearby resident to start a conversation.",
  "island.conversationEmpty": "No conversation turns with this resident yet.",
  "island.messagePlaceholder": "Say something to this resident",
  "island.send": "Send",
  "island.sending": "Sending",
  "island.endConversation": "End conversation",
  "island.you": "You",
  "island.ruleReply": "Rule reply",
  "island.llmReply": "LLM reply",
  "island.scenario": "Current research scene",
  "island.noScenario": "No controlled scene is active at this location.",
  "island.event": "Current community event",
  "island.noEvent": "No ordinary community event is active here.",
  "island.eventResponsePlaceholder": "Write a brief response...",
  "island.unsupportedScenarioTitle": "Scene unavailable",
  "island.unsupportedScenarioDescription":
    "This scene cannot be presented safely by this version of the interface. Its actions are unavailable, and you may continue exploring the island.",
  "island.optionalScene": "Optional scene",
  "island.seating": "Restaurant seating",
  "island.seatingDescription":
    "Review the seats made available by this scenario. A single choice is never treated as a psychological label.",
  "island.seatsUnavailable": "Seat choices are not available from the scenario yet.",
  "island.viewSeat": "View seat",
  "island.selectSeat": "Choose seat",
  "island.changeSeat": "Change to seat",
  "island.conflict": "Community misunderstanding",
  "island.conflictDescription":
    "You can ask for context, negotiate, leave, write your own response, or skip this scene.",
  "island.clarify": "Ask for clarification",
  "island.negotiate": "Negotiate a solution",
  "island.leave": "Leave the situation",
  "island.custom": "Use my own words",
  "island.customPlaceholder": "Write the response you want to give",
  "island.submitResponse": "Submit response",
  "island.skipScenario": "Skip this scene",
  "island.followUp": "Recent follow-up",
  "island.noFollowUp": "No follow-up has appeared yet.",
  "island.recentActions": "Recent activity",
  "island.noRecentActions": "No island actions recorded yet.",
  "island.actionSaved": "Your action was saved and the island state was refreshed.",
  "island.conversationSaved": "The conversation was saved.",
  "island.busy": "Saving action...",
  "island.errorLoad": "Could not load this island session.",
  "island.errorAction": "Could not save that island action.",
  "island.errorConversation": "Could not save the conversation.",
  "island.errorFinish": "Could not end this session.",

  "error.createSession":
    "Could not create the session. Check that the backend is running and try again.",
  "error.setupRequired": "Nickname and consent are required to start.",
  "error.invalidSession": "The backend did not return a valid session id.",
  "error.recordPostView": "Could not record the post view.",
  "error.loadPosts": "Could not load posts.",
  "error.loadFeed": "Could not load this session's community timeline.",
  "error.advanceDay": "Could not advance to the next day.",
  "error.readNotification": "Could not update the notification.",
  "error.saveInteraction": "Could not save the interaction.",
  "error.saveComment": "Could not save the comment.",
  "error.saveReply": "Could not save the reply.",
  "error.publishPost": "Could not publish the post.",
  "error.finishSession": "Could not finish the session.",
  "error.scoreSession": "Could not calculate the session feedback.",
} as const;

export type TranslationKey = keyof typeof english;

const simplifiedChinese: Record<TranslationKey, string> = {
  "meta.title": "MindScape 岛屿研究原型",
  "language.switchToChinese": "简体中文",
  "language.switchToEnglish": "English",
  "language.switchLabel": "切换语言",

  "landing.eyebrow": "严肃游戏研究原型",
  "landing.title": "MindScape 岛屿",
  "landing.description":
    "进入一座属于本次会话的模拟岛屿，探索渡口、广场和餐厅，与拥有各自日程及会话内记忆的 AI 岛民相遇。",
  "landing.notice":
    "这是一个研究原型，不提供医学诊断、治疗或危机干预服务。",
  "landing.start": "登上岛屿",
  "landing.preview": "认识岛上的居民",
  "landing.staticPosts": "三位居民，三种不同日程",
  "landing.miraRole": "图书室助理",
  "landing.miraPost":
    "Mira 会先在渡口迎接新岛民，之后前往广场整理社区书架。",
  "landing.leoRole": "咖啡馆帮工",
  "landing.leoPost": "Leo 会查看广场的活动公告，随后去餐厅准备午间营业。",
  "landing.novaRole": "社区协调员",
  "landing.novaPost":
    "Chen 负责推进岛上的日常安排，也会处理普通的预订误会。",

  "setup.back": "返回",
  "setup.title": "设置你的会话",
  "setup.description": "抵达岛屿前，请先创建一个本地研究会话。",
  "setup.nickname": "昵称",
  "setup.nicknamePlaceholder": "请输入昵称",
  "setup.consent":
    "我理解这是一个研究原型，不是医学诊断、治疗工具或危机服务。我同意将本次会话中的对话、选择、路径和回应时间保存到本地 SQLite 数据库。如果当前部署启用了外部语言模型服务，我的对话文本可能会发送给所配置的服务商。",
  "setup.start": "开始会话",
  "setup.creating": "正在创建会话",

  "feed.eyebrow": "模拟社区",
  "feed.title": "社区动态",
  "feed.subtitle": "浏览一个从周一持续到周日、对话会逐步发展的模拟社区。",
  "feed.notice": "本研究原型不提供医学诊断或危机支持。",
  "feed.finish": "结束会话",
  "feed.nextDay": "进入下一天",
  "feed.advancing": "正在准备下一天",
  "feed.dayProgress": "第 {current} 天，共 {total} 天",
  "feed.today": "今天的新动态",
  "feed.earlierPosts": "更早的动态",
  "feed.newDayReady": "第 {day} 天已经开始，社区出现了新的动态和对话。",
  "feed.loading": "正在加载帖子...",
  "feed.emptyTitle": "动态中已经没有帖子了。",
  "feed.emptyDescription": "你可以结束会话并查看反馈报告。",
  "feed.progress": "会话进度",
  "feed.visiblePosts": "当前帖子",
  "feed.viewsRecorded": "已记录浏览",
  "feed.likes": "点赞",
  "feed.skips": "跳过",
  "feed.comments": "评论",
  "feed.agentReplies": "Agent 回复",
  "feed.recordedActions": "已记录操作",
  "feed.timeline": "社区时间线",
  "feed.dayLabel": "第 {day} 天",
  "feed.currentDay": "当前",
  "feed.visitedDay": "已浏览",
  "feed.lockedDay": "尚未开始",
  "feed.notifications": "通知",
  "feed.unreadNotifications": "{count} 条未读",
  "feed.noNotifications": "目前没有通知。",
  "feed.openNotification": "打开通知",
  "feed.closeNotifications": "关闭通知",
  "feed.viewPost": "查看帖子",
  "feed.finalDayHint": "现在是社区时间线的最后一天。",
  "feed.nextDayHint": "准备好后进入下一天，查看明天的新动态。",
  "feed.likeSaved": "点赞已保存，这条帖子已标记为喜欢。",
  "feed.likeRemoved": "已取消点赞。",
  "feed.skippedNamed": "已跳过 {name} 的帖子，并从动态中移除。",
  "feed.skippedGeneric": "跳过操作已保存，帖子已从动态中移除。",
  "feed.commentSaved": "评论和 Agent 回复均已保存。",
  "feed.replySaved": "回复和 Agent 的后续回应均已保存。",
  "feed.postPublished": "你的帖子已发布，社区成员已经开始回应。",

  "composer.title": "发布新帖子",
  "composer.placeholder": "和社区分享此刻的想法",
  "composer.publish": "发布",
  "composer.publishing": "正在发布并生成回复……",

  "post.likedNotice": "你已点赞这条帖子。",
  "post.commentsTitle": "你的对话",
  "post.communityDiscussion": "社区讨论",
  "post.yourPost": "你的帖子",
  "post.replyingTo": "{name} 回复了 {target}",
  "post.likeCount": "{count} 个赞",
  "post.commentCount": "{count} 条评论",
  "post.todayAt": "今天 {time}",
  "post.yesterdayAt": "昨天 {time}",
  "post.dayAt": "第 {day} 天 {time}",
  "post.you": "你",
  "post.replying": "{name} 正在回复...",
  "post.llmReply": "大语言模型回复",
  "post.ruleReply": "规则生成回复",
  "post.replyTo": "回复 {name}",
  "post.replyToOriginal": "评论 {name} 的帖子",
  "post.reply": "回复",
  "post.commentPlaceholder": "写一条简短评论",
  "post.comment": "评论",
  "post.commentLabel": "评论",
  "post.sendTitle": "发送评论",
  "post.saving": "正在保存",
  "post.like": "点赞",
  "post.liked": "已点赞",
  "post.likeTitle": "点赞帖子",
  "post.unlikeTitle": "取消点赞",
  "post.skip": "跳过",
  "post.skipTitle": "跳过帖子",

  "result.back": "返回岛屿",
  "result.restart": "重新开始",
  "result.download": "下载研究 JSON",
  "result.loading": "正在核对会话状态……",
  "result.error": "无法核对会话状态。请确认后端正在运行后重试。",
  "result.retry": "重试",
  "result.eyebrow": "中性研究说明",
  "result.title": "会话已完成",
  "result.description":
    "你的岛屿互动已经保存，供研究人员后续审查。参与者页面不会计算或显示心理评分。",
  "result.neutralTitle": "岛屿记录已经保存",
  "result.neutralDescription":
    "本原型不提供诊断、治疗或危机支持。任何后续研究分析都必须在获批的研究方案下离线进行。",
  "result.sessionStatus": "会话状态：{status}",
  "result.status.active": "进行中",
  "result.status.completed": "已完成",
  "result.status.abandoned": "已放弃",
  "result.calculating": "正在计算反馈...",

  "report.output": "研究原型输出",
  "report.score": "原型分数",
  "report.signal": "原型情绪信号",
  "report.behaviorFeatures": "行为特征",
  "report.textFeatures": "文本特征",
  "report.dataQuality": "数据质量",
  "report.interactionCount": "互动数量",
  "report.commentCount": "评论数量",
  "report.sufficientData": "数据是否充足",
  "report.yes": "是",
  "report.no": "否",
  "report.warnings": "提示",

  "feature.post_view_count": "帖子浏览数",
  "feature.like_count": "点赞数",
  "feature.unlike_count": "取消点赞数",
  "feature.skip_count": "跳过数",
  "feature.comment_count": "评论数",
  "feature.agent_reply_count": "Agent 回复数",
  "feature.user_post_count": "发布帖子数",
  "feature.unique_agents_interacted": "互动过的 Agent 数",
  "feature.engagement_rate": "互动率",
  "feature.skip_rate": "跳过率",
  "feature.comment_rate": "评论率",
  "feature.average_response_latency_ms": "平均响应时间（毫秒）",
  "feature.median_response_latency_ms": "响应时间中位数（毫秒）",
  "feature.session_duration_seconds": "会话时长（秒）",
  "feature.comment_total_word_count": "评论词数",
  "feature.average_comment_length_words": "平均评论长度",
  "feature.negative_word_count": "负面词数量",
  "feature.negative_word_ratio": "负面词比例",
  "feature.positive_word_count": "正面词数量",
  "feature.positive_word_ratio": "正面词比例",
  "feature.self_reference_count": "自我指称数量",
  "feature.self_reference_ratio": "自我指称比例",
  "feature.question_count": "问题数量",
  "feature.lexical_diversity": "词汇多样性",

  "warning.noPostViews": "没有记录到帖子浏览事件。",
  "warning.noComments": "没有记录到用户评论。",

  "island.eyebrow": "MindScape Island 垂直切片",
  "island.title": "岛屿社区",
  "island.subtitle": "探索渡口、广场和餐厅。岛民按照各自日程生活，研究情境则保持受控和版本化。",
  "island.notice": "这是非临床研究原型。你可以无惩罚离开或跳过任何情境。",
  "island.feed": "社区公告板",
  "island.export": "下载研究 JSON",
  "island.finish": "结束会话",
  "island.finishing": "正在结束会话",
  "island.finished": "本次会话已结束，岛屿记录已经保存。这里不会显示心理评分。",
  "island.refresh": "刷新岛屿",
  "island.refreshing": "正在刷新",
  "island.loading": "正在恢复你的岛屿……",
  "island.noSessionTitle": "没有找到岛屿会话",
  "island.noSessionDescription": "请先创建会话，或使用包含会话编号的岛屿链接返回。",
  "island.createSession": "创建会话",
  "island.retry": "重试",
  "island.day": "第 {day} 天",
  "island.time": "岛屿时间 {time}",
  "island.location": "当前位置",
  "island.locations": "岛屿地图",
  "island.current": "你在这里",
  "island.travel": "前往这里",
  "island.notConnected": "当前没有可用路线",
  "island.closed": "未开放",
  "island.scene": "此处动态",
  "island.observe": "观察",
  "island.approach": "接近",
  "island.wait": "等待",
  "island.endDay": "结束这一天",
  "island.residents": "附近岛民",
  "island.noResidents": "目前附近没有岛民。",
  "island.activity": "正在进行",
  "island.goal": "当前目标",
  "island.schedule": "日程",
  "island.unknown": "暂未透露",
  "island.talk": "对话",
  "island.conversation": "对话",
  "island.chooseResident": "选择一位附近岛民开始对话。",
  "island.conversationEmpty": "你和这位岛民还没有对话记录。",
  "island.messagePlaceholder": "想对这位岛民说什么？",
  "island.send": "发送",
  "island.sending": "正在发送",
  "island.endConversation": "结束对话",
  "island.you": "你",
  "island.ruleReply": "规则回复",
  "island.llmReply": "LLM 回复",
  "island.scenario": "当前研究情境",
  "island.noScenario": "这个地点目前没有受控研究情境。",
  "island.event": "当前社区事件",
  "island.noEvent": "这里目前没有普通社区事件。",
  "island.eventResponsePlaceholder": "写一句简短回应……",
  "island.unsupportedScenarioTitle": "情境暂不可用",
  "island.unsupportedScenarioDescription":
    "当前版本的界面无法安全呈现这个情境，因此不会提供相关操作。你仍然可以继续探索岛屿。",
  "island.optionalScene": "可选情境",
  "island.seating": "餐厅选座",
  "island.seatingDescription": "查看本情境实际提供的座位。单次选择绝不会被解释为心理标签。",
  "island.seatsUnavailable": "情境尚未提供可用座位。",
  "island.viewSeat": "查看座位",
  "island.selectSeat": "选择座位",
  "island.changeSeat": "更换到此座位",
  "island.conflict": "社区误会",
  "island.conflictDescription": "你可以询问情况、协商、离开、自由表达，或跳过这个情境。",
  "island.clarify": "询问并澄清",
  "island.negotiate": "协商解决",
  "island.leave": "离开现场",
  "island.custom": "用自己的话回应",
  "island.customPlaceholder": "写下你想作出的回应",
  "island.submitResponse": "提交回应",
  "island.skipScenario": "跳过这个情境",
  "island.followUp": "最近回访",
  "island.noFollowUp": "目前还没有新的回访。",
  "island.recentActions": "近期活动",
  "island.noRecentActions": "还没有记录岛屿行动。",
  "island.actionSaved": "行动已保存，岛屿状态已刷新。",
  "island.conversationSaved": "对话已保存。",
  "island.busy": "正在保存行动……",
  "island.errorLoad": "无法加载这个岛屿会话。",
  "island.errorAction": "无法保存这个岛屿行动。",
  "island.errorConversation": "无法保存这段对话。",
  "island.errorFinish": "无法结束本次会话。",

  "error.createSession": "无法创建会话，请确认后端正在运行后重试。",
  "error.setupRequired": "请输入昵称并勾选同意事项后再开始。",
  "error.invalidSession": "后端没有返回有效的会话编号。",
  "error.recordPostView": "无法记录帖子浏览。",
  "error.loadPosts": "无法加载帖子。",
  "error.loadFeed": "无法加载本次会话的社区时间线。",
  "error.advanceDay": "无法进入下一天。",
  "error.readNotification": "无法更新通知状态。",
  "error.saveInteraction": "无法保存互动。",
  "error.saveComment": "无法保存评论。",
  "error.saveReply": "无法保存回复。",
  "error.publishPost": "无法发布帖子。",
  "error.finishSession": "无法结束会话。",
  "error.scoreSession": "无法计算本次会话的反馈。",
};

const dictionaries: Record<Language, Record<TranslationKey, string>> = {
  en: english,
  "zh-CN": simplifiedChinese,
};

type TranslationValues = Record<string, string | number>;

type LanguageContextValue = {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: TranslationKey, values?: TranslationValues) => string;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

function formatTranslation(template: string, values?: TranslationValues) {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    values[key] === undefined ? match : String(values[key]),
  );
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>("en");

  const setLanguage = useCallback((nextLanguage: Language) => {
    setLanguageState(nextLanguage);
    localStorage.setItem(STORAGE_KEY, nextLanguage);
    document.documentElement.lang = nextLanguage;
    document.title = dictionaries[nextLanguage]["meta.title"];
  }, []);

  useEffect(() => {
    const queryLanguage = new URLSearchParams(window.location.search).get("language");
    const storedLanguage = localStorage.getItem(STORAGE_KEY);
    const browserLanguage = navigator.language.toLowerCase();
    const initialLanguage: Language =
      queryLanguage === "en" || queryLanguage === "zh-CN"
        ? queryLanguage
        : storedLanguage === "en" || storedLanguage === "zh-CN"
        ? storedLanguage
        : browserLanguage.startsWith("zh")
          ? "zh-CN"
          : "en";
    const applyInitialLanguage = window.setTimeout(
      () => setLanguage(initialLanguage),
      0,
    );
    return () => window.clearTimeout(applyInitialLanguage);
  }, [setLanguage]);

  const t = useCallback(
    (key: TranslationKey, values?: TranslationValues) =>
      formatTranslation(dictionaries[language][key], values),
    [language],
  );

  const contextValue = useMemo(
    () => ({ language, setLanguage, t }),
    [language, setLanguage, t],
  );

  return (
    <LanguageContext.Provider value={contextValue}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within LanguageProvider.");
  }
  return context;
}
