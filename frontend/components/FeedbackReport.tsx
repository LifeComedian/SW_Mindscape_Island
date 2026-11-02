import type { ScoreResult } from "@/lib/api";
import { TranslationKey, useLanguage } from "@/lib/i18n";

type FeedbackReportProps = {
  result: ScoreResult;
};

function formatLabel(key: string) {
  return key.replaceAll("_", " ");
}

const FEATURE_LABEL_KEYS: Record<string, TranslationKey> = {
  post_view_count: "feature.post_view_count",
  like_count: "feature.like_count",
  unlike_count: "feature.unlike_count",
  skip_count: "feature.skip_count",
  comment_count: "feature.comment_count",
  agent_reply_count: "feature.agent_reply_count",
  unique_agents_interacted: "feature.unique_agents_interacted",
  engagement_rate: "feature.engagement_rate",
  skip_rate: "feature.skip_rate",
  comment_rate: "feature.comment_rate",
  average_response_latency_ms: "feature.average_response_latency_ms",
  median_response_latency_ms: "feature.median_response_latency_ms",
  session_duration_seconds: "feature.session_duration_seconds",
  comment_total_word_count: "feature.comment_total_word_count",
  average_comment_length_words: "feature.average_comment_length_words",
  negative_word_count: "feature.negative_word_count",
  negative_word_ratio: "feature.negative_word_ratio",
  positive_word_count: "feature.positive_word_count",
  positive_word_ratio: "feature.positive_word_ratio",
  self_reference_count: "feature.self_reference_count",
  self_reference_ratio: "feature.self_reference_ratio",
  question_count: "feature.question_count",
  lexical_diversity: "feature.lexical_diversity",
};

export default function FeedbackReport({ result }: FeedbackReportProps) {
  const { t } = useLanguage();
  const scoreTone = result.has_sufficient_data
    ? "border-teal-200 bg-teal-50 text-teal-950"
    : "border-amber-200 bg-amber-50 text-amber-950";

  return (
    <section className="space-y-6">
      <div className={`rounded-lg border p-5 ${scoreTone}`}>
        <p className="text-sm font-medium uppercase tracking-normal">
          {t("report.output")}
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-sm opacity-80">{t("report.score")}</p>
            <p className="text-2xl font-bold">{result.prototype_score.toFixed(2)}</p>
          </div>
          <div>
            <p className="text-sm opacity-80">{t("report.signal")}</p>
            <p className="text-2xl font-bold">{result.prototype_signal_label}</p>
          </div>
        </div>
        <p className="mt-4 text-sm leading-6">{result.prototype_signal_description}</p>
        <p className="mt-2 text-sm leading-6">{result.summary}</p>
        <p className="mt-2 text-sm leading-6">{result.disclaimer}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <FeatureList title={t("report.behaviorFeatures")} features={result.behavior_features} />
        <FeatureList title={t("report.textFeatures")} features={result.text_features} />
        <DataQuality features={result.data_quality} />
      </div>
    </section>
  );
}

function FeatureList({
  title,
  features,
}: {
  title: string;
  features: Record<string, number>;
}) {
  const { t } = useLanguage();

  return (
    <div className="rounded-lg border border-stone-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-stone-950">{title}</h2>
      <dl className="mt-4 space-y-3">
        {Object.entries(features).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-3">
            <dt className="text-sm capitalize text-stone-600">
              {FEATURE_LABEL_KEYS[key] ? t(FEATURE_LABEL_KEYS[key]) : formatLabel(key)}
            </dt>
            <dd className="text-sm font-semibold text-stone-950">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function DataQuality({ features }: { features: Record<string, unknown> }) {
  const { t } = useLanguage();
  const warnings = Array.isArray(features.warnings) ? features.warnings : [];

  return (
    <div className="rounded-lg border border-stone-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-stone-950">
        {t("report.dataQuality")}
      </h2>
      <dl className="mt-4 space-y-3">
        <QualityRow label={t("report.interactionCount")} value={features.interaction_count} />
        <QualityRow label={t("report.commentCount")} value={features.comment_count} />
        <QualityRow
          label={t("report.sufficientData")}
          value={features.has_sufficient_data ? t("report.yes") : t("report.no")}
        />
      </dl>
      {warnings.length > 0 ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="text-sm font-semibold text-amber-950">
            {t("report.warnings")}
          </p>
          <ul className="mt-2 space-y-1">
            {warnings.map((warning) => (
              <li key={String(warning)} className="text-sm leading-5 text-amber-900">
                {localizeWarning(String(warning), t)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function localizeWarning(
  warning: string,
  t: (key: TranslationKey) => string,
) {
  if (warning === "No post_view events were recorded.") {
    return t("warning.noPostViews");
  }
  if (warning === "No user comments were recorded.") {
    return t("warning.noComments");
  }
  return warning;
}

function QualityRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-sm text-stone-600">{label}</dt>
      <dd className="text-sm font-semibold text-stone-950">{String(value ?? "")}</dd>
    </div>
  );
}
