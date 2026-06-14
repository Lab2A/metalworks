// GENERATED FILE — do not edit by hand.
// Source of truth: metalworks/contract (Python, Pydantic).
// Regenerate: python scripts/gen_ts_types.py

export type Fork = "product_pinned" | "demographic_pinned" | "both";
export type SignalStrength = "low" | "medium" | "high";

export interface EvidenceRef {
  /** Target QuoteCitation/WebFinding/PriceEvidence id. Empty for a cluster ref. */
  evidence_id?: string;
  /** Which evidence family this points at. */
  kind: "quote" | "web" | "price" | "cluster";
  /** Set only when kind=='cluster' — 1-based InsightCluster.rank. */
  cluster_rank?: number | null;
}

export interface EvidenceRecord {
  id: string;
  kind: "quote" | "web" | "price";
  text: string;
  /** permalink (quote/price) or source_url (web); '' if none. */
  url: string;
  provenance: "verbatim" | "grounded-web" | "derived";
}

export interface QuoteCitation {
  /** Verbatim quote, exact-matched to the source comment. */
  text: string;
  /** Direct link to the source thread/comment. */
  permalink: string;
  /** Source subreddit, e.g. 'r/Supplements'. */
  subreddit: string;
  /** Stable pseudonymous author id (salted hash) — for distinct-author counting, never the raw username. Pseudonymization, not anonymization. */
  author_hash: string;
  /** Upvotes on the source comment, for context. */
  upvotes?: number;
  /** Stable content-addressed evidence id (``q:<hash of permalink|text>``). */
  id: string;
}

export interface InsightCluster {
  /** 1-based rank within the report (by demand_score). */
  rank: number;
  /** One-line synthesized insight (what consumers want/feel/struggle with). */
  claim: string;
  /** Ranking signal. Weights distinct-author breadth ABOVE single-post virality (50 authors x 2 upvotes outranks 1 author x 200 upvotes). */
  demand_score: number;
  /** Number of DISTINCT authors expressing this — the honest base rate, not mention count. */
  distinct_author_count: number;
  /** Total mentions (>= distinct_author_count). Kept separate so base-rate honesty is visible. */
  mention_count: number;
  /** Confidence chip, derived from distinct_author_count. */
  signal: SignalStrength;
  /** 2-3 verified quotes. A cluster with zero verified quotes is never shipped (no-quote-no-theme). */
  quotes: QuoteCitation[];
  attribution_method?: string | null;
  attribution_confidence?: string | null;
  demographic_match?: number | null;
}

export interface SlotPlan {
  product?: string | null;
  audience?: string | null;
  price?: number | null;
  given?: string[];
  find?: string[];
}

export interface AudienceAttribute {
  estimate: string;
  confidence: SignalStrength;
  evidence: string;
}

export interface AudienceProfile {
  age_range?: AudienceAttribute | null;
  income_band?: AudienceAttribute | null;
  geography?: AudienceAttribute | null;
  buying_behavior?: AudienceAttribute | null;
  caveat?: string | null;
}

export interface AudienceSegment {
  name: string;
  profile: AudienceProfile;
  preferences?: string[];
  demand_score: number;
  distinct_author_count: number;
}

export interface PriceEvidence {
  text: string;
  kind: string;
  amount?: number | null;
  permalink?: string | null;
  /** Stable content-addressed evidence id (``p:<hash of permalink|text>``). */
  id: string;
}

export interface PriceFinding {
  low?: number | null;
  high?: number | null;
  currency?: string;
  confidence?: SignalStrength | null;
  evidence?: PriceEvidence[];
  insufficient_signal?: boolean;
}

export interface SourceMapEntry {
  subreddit: string;
  subscribers?: number | null;
  threads_examined?: number;
  skew?: string | null;
}

export interface MarketSizing {
  reddit_floor: number;
  addressable_market: number;
  penetration: Record<string, number>;
}

export interface TargetSubreddit {
  /** Subreddit name without 'r/' prefix. */
  name: string;
  /** One-line reason this sub was suggested. */
  rationale: string;
}

export interface TriageThresholds {
  auto_accept_pct?: number;
  auto_reject_pct?: number;
  /** Absolute cosine below which to auto-reject regardless of percentile. None = percentile-only. */
  cosine_floor?: number | null;
  /** Absolute cosine above which to auto-accept regardless of percentile. None = percentile-only. */
  cosine_ceiling?: number | null;
}

export interface ResearchBrief {
  /** Stable UUID for this version of the brief. */
  brief_id: string;
  /** Owning tenant. Defaults to 'local' for library/CLI use. */
  workspace_id?: string;
  /** Monotonic version counter within the supersedes chain. */
  version?: number;
  /** Prior brief_id this version replaces. None for the first version. */
  supersedes?: string | null;
  /** The refined research question after the planner conversation. */
  question: string;
  /** What decision will this research inform. */
  decision_context: string;
  /** How the user will judge if the report did its job. */
  success_criteria: string[];
  /** Specific sub-questions the report MUST answer. Surfaced in must_address_resolution. */
  must_address: string[];
  /** Reddit communities the corpus pull will cover. */
  target_subreddits: TargetSubreddit[];
  /** External angles to pursue in the web stream. */
  web_research_directions: string[];
  /** Explicitly out of scope. */
  excluded_sources?: string[];
  /** How far back to pull from the historical corpus. */
  time_window_months?: number;
  /** One-paragraph definition of relevance the exploration classifier follows. Goes in the user role of the classifier prompt, never system. */
  relevance_rubric: string;
  triage_thresholds?: TriageThresholds;
  output_template?: "full" | "brief_only";
  confidence_threshold?: SignalStrength;
  /** When the user confirmed the brief preview and kicked off the run. */
  finalized_at?: string | null;
}

export interface WebFinding {
  /** 1-based index within this report's web_findings list. */
  finding_index: number;
  /** One-line factual claim from the web. */
  claim: string;
  /** The number, date, name, or quote that anchors the claim. */
  specifics: string;
  /** From the grounding tool's citation metadata. */
  source_url: string;
  /** From the grounding tool's citation metadata. */
  source_title: string;
  /** From the grounding metadata when available. */
  published_at?: string | null;
  /** Service-assigned, not LLM-assigned. */
  confidence: SignalStrength;
  /** Stable content-addressed evidence id (``w:<hash of source_url|claim>``). */
  id: string;
}

export interface ExplorationReport {
  threads_pulled: number;
  threads_auto_accepted: number;
  threads_auto_rejected: number;
  threads_classified: number;
  threads_relevant: number;
  threads_synthesized: number;
  noise_composition?: Record<string, number>;
  similarity_percentiles?: Record<string, number>;
  /** Percentile bands (p10..p90) of the blended cosine + BM25 hybrid score that actually drives the bucketing. Empty for legacy reports that ran on cosine-only triage. */
  hybrid_percentiles?: Record<string, number>;
}

export interface CorpusStats {
  /** Decile → thread count. */
  percentile_bands?: Record<string, number>;
  subreddit_distribution?: SourceMapEntry[];
  /** ISO month → thread count. */
  time_distribution?: Record<string, number>;
}

export interface CrossReference {
  /** 1-based rank, references InsightCluster.rank. */
  cluster_rank: number;
  /** 1-based indices, reference WebFinding.finding_index. */
  web_finding_indices: number[];
  /** How the streams relate on this claim. */
  agreement: "agree" | "silent_web" | "silent_corpus" | "disagree";
  /** One-line synthesis: where they converge, or what the disagreement is. */
  note: string;
}

export interface DemandReport {
  report_id: string;
  /** Owning tenant. Set by the service, never the LLM. Defaults to 'local' for library/CLI use. */
  client_id?: string;
  query: string;
  fork: Fork;
  pinned_axis: string;
  optimized_axis: string;
  /** Provenance: 'reddit_arctic_shift' | 'reddit_live' | 'mixed'. */
  source?: string;
  date_range_start: string;
  date_range_end: string;
  total_threads: number;
  total_distinct_authors: number;
  ranked_clusters: InsightCluster[];
  partial?: boolean;
  caveat?: string | null;
  /** 'library' | 'cli' | 'mcp' | 'ui' | 'agent'. */
  created_by?: string;
  generated_at: string;
  verdict?: string | null;
  slot_plan?: SlotPlan | null;
  audience_profile?: AudienceProfile | null;
  segments?: AudienceSegment[];
  market_sizing?: MarketSizing | null;
  price_finding?: PriceFinding | null;
  source_map?: SourceMapEntry[];
  /** The brief this run was produced against (frozen-version FK). */
  brief?: ResearchBrief | null;
  web_findings?: WebFinding[];
  corpus_stats?: CorpusStats | null;
  corpus_shape?: ExplorationReport | null;
  cross_references?: CrossReference[];
  /** must_address item → 'cluster:N' | 'web:N' | 'unaddressable: <reason>'. */
  must_address_resolution?: Record<string, string>;
}

export interface Research {
  demand: DemandReport;
  competitors?: CompetitorMap | null;
  positioning?: PositioningBrief | null;
}

export interface ReportSummary {
  report_id: string;
  query: string;
  fork: Fork;
  total_threads: number;
  total_distinct_authors: number;
  generated_at: string;
  top_claims?: string[];
  brief_id?: string | null;
}

export interface RunSummary {
  report_id: string;
  brief_id?: string | null;
  query: string;
  status: "queued" | "planning_brief" | "pulling_arctic_shift" | "embedding_triage" | "llm_classifying" | "analyzing_relevant" | "web_research" | "compiling" | "complete" | "failed" | "compile_failed" | "oom_chunked";
  progress?: string | null;
  error?: string | null;
  total_distinct_authors?: number | null;
  created_at: string;
  generated_at?: string | null;
  ready_at?: string | null;
}

export interface StrengthClaim {
  /** A concrete strength, one clause. */
  claim: string;
  /** A WebFinding ref backing the strength, when one matched. */
  evidence?: EvidenceRef | null;
}

export interface GapClaim {
  /** 1-based index within the competitor's gaps. */
  gap_index: number;
  /** The gap, phrased as what the competitor misses. */
  claim: string;
  /** Service-assigned, never LLM. */
  severity: SignalStrength;
  /** The single resolvable ref backing this gap. */
  evidence: EvidenceRef;
}

export interface Competitor {
  /** 1-based index within the map. */
  competitor_index: number;
  /** The competitor / alternative name. */
  name: string;
  /** direct | adjacent | status_quo. */
  kind: "direct" | "adjacent" | "status_quo";
  /** What it is, in one line. */
  one_liner: string;
  strengths?: StrengthClaim[];
  gaps?: GapClaim[];
}

export interface CompetitorMap {
  /** Stable id for this map (derived from report_id). */
  map_id: string;
  /** The DemandReport this map was derived from. */
  report_id: string;
  competitors?: Competitor[];
  /** The mandatory 'do nothing' alternative (kind=status_quo). */
  status_quo_alternative: Competitor;
  generated_at: string;
  /** True when a stage degraded. */
  partial?: boolean;
  /** What to treat as lower-confidence. */
  caveat?: string | null;
}

export interface WedgeClaim {
  /** What the beachhead audience uses today, from real web findings. */
  competitive_alternative: string;
  /** What this product does differently — the white space competitors miss. */
  unique_attribute: string;
  /** Why that attribute matters to the audience. */
  value: string;
  /** The narrow first audience to win. */
  beachhead: string;
  /** The frame of reference the product competes in. */
  market_category: string;
  /** 1-based InsightCluster.rank the wedge stands on (silent_web/disagree). */
  source_cluster_rank: number;
  /** Refs (cluster quotes + web findings) backing the wedge. */
  evidence?: EvidenceRef[];
}

export interface PriceHypothesis {
  /** Low end of the willingness-to-pay band. */
  low?: number | null;
  /** High end of the band. */
  high?: number | null;
  currency?: string;
  /** One-line PMC/PME framing of how the band was derived (from price evidence). */
  framing?: string;
  /** Refs to the PriceEvidence backing the band. */
  evidence?: EvidenceRef[];
  insufficient_signal?: boolean;
}

export interface PositioningBrief {
  /** The DemandReport this brief was derived from. */
  report_id: string;
  /** The assembled Dunford statement (or an honest null when no wedge). */
  positioning_statement: string;
  /** The wedge; None when no white-space cluster qualifies. */
  wedge?: WedgeClaim | null;
  /** Price band copied through from the report; None if absent. */
  price_hypothesis?: PriceHypothesis | null;
  /** True when the wedge is absent or a clause failed verification. */
  partial?: boolean;
  /** Why the brief is partial / what to treat as unconfirmed. */
  caveat?: string | null;
}

export interface RubricDimension {
  /** The fixed rubric dimension. */
  name: "where_are_the_users" | "technical_sophistication" | "usage_frequency" | "realtime_or_hardware" | "distribution";
  /** What the evidence says for this dimension (LLM-phrased). */
  finding: string;
  /** Refs backing the finding. Empty iff is_assumption is True. */
  evidence_refs?: EvidenceRef[];
  /** True when no evidence backs this dimension — a stated guess. */
  is_assumption?: boolean;
}

export interface TradeOff {
  /** The trade-off, one clause. */
  text: string;
  evidence_refs?: EvidenceRef[];
}

export interface SurfaceRecommendation {
  report_id: string;
  /** The recommended surface to build. */
  chosen: "sdk" | "web" | "mobile" | "cli" | "browser_extension" | "api" | "desktop";
  /** The second-best surface. */
  runner_up?: "sdk" | "web" | "mobile" | "cli" | "browser_extension" | "api" | "desktop" | null;
  /** Why this surface, in one short paragraph (LLM-phrased). */
  rationale: string;
  rubric?: RubricDimension[];
  trade_offs?: TradeOff[];
  /** Service-assigned from grounded rubric coverage. */
  confidence?: SignalStrength;
  generated_at: string;
  partial?: boolean;
  caveat?: string | null;
}

export interface Screen {
  /** Screen name. */
  name: string;
  /** What this screen is for, one line. */
  purpose: string;
  /** The single primary action on this screen. */
  primary_action: string;
  /** True when this screen directly serves the positioning wedge. */
  serves_wedge?: boolean;
  /** Voices asking for this screen. Empty → an unvalidated hypothesis. */
  evidence_refs?: EvidenceRef[];
  /** True iff at least one evidence_ref backs the screen. */
  validated?: boolean;
}

export interface UxSkeleton {
  report_id: string;
  surface: "sdk" | "web" | "mobile" | "cli" | "browser_extension" | "api" | "desktop";
  screens?: Screen[];
  generated_at: string;
  partial?: boolean;
  caveat?: string | null;
}

export interface DesignBrief {
  report_id: string;
  /** A short brief for the design step (tone, surface, audience). */
  summary: string;
  /** Always present: this brief is NOT evidence-backed. */
  note?: string;
}

export interface SiteSection {
  /** Section job on the page: hero/feature/objection/pricing/social_proof/cta. */
  role: string;
  /** Rendered section text (contains a verbatim fragment if claimed). */
  copy: string;
  /** Refs backing the section — one quote ref for verbatim, empty for connective. */
  evidence_refs?: EvidenceRef[];
  /** verbatim = exact-matched quote fragment; connective = claim-free glue. */
  provenance: "verbatim" | "derived" | "connective";
}

export interface MarketingSite {
  /** Stable id for this generated site. */
  site_id: string;
  /** The DemandReport this site was derived from. */
  report_id: string;
  /** Ordered sections; verbatim sections carry quote refs, connective ones none. */
  sections?: SiteSection[];
  /** True when synthesis was unavailable and the site is empty. */
  partial?: boolean;
  /** Why the site is partial / what to treat as unbuilt. */
  caveat?: string | null;
}

export interface ClaimCitation {
  /** The exact claim substring as it appears in the asset body. */
  claim_text: string;
  /** 0-based char offset of claim_text in body. */
  span_start: number;
  /** Exclusive char offset; body[span_start:span_end]==claim_text. */
  span_end: number;
  /** Ref to the supporting quote — resolves against the report's evidence by id. */
  evidence_ref: EvidenceRef;
}

export interface LaunchAsset {
  /** Channel id: 'product_hunt' | 'show_hn' | 'x_thread' | ... */
  surface: string;
  /** The headline / title / first-tweet hook for this surface. */
  title: string;
  /** The channel-native body copy. ClaimCitation spans index into it. */
  body: string;
  /** Alternate hooks/headlines a human can choose from. */
  variants?: string[];
  /** Grounded claims; each span indexes body and each ref resolves in the report. */
  claim_citations?: ClaimCitation[];
}

export interface ChannelStep {
  /** Channel id this step acts on. */
  surface: string;
  /** What the human does (e.g. 'Submit the Product Hunt draft'). */
  action: string;
  /** Relative schedule, e.g. 'T+0h', 'T+2h'. */
  scheduled_offset: string;
  /** Always true — a person executes this step, never the library. */
  requires_human?: boolean;
  /** Always true — posting is gated behind explicit human action. */
  posting_gated?: boolean;
}

export interface ChannelPlan {
  /** The DemandReport this plan was derived from. */
  report_id: string;
  /** One step per launch surface, in execution order. */
  steps?: ChannelStep[];
}

export interface FaqItem {
  /** The sub-question, copied verbatim from brief.must_address. */
  question: string;
  /** Always '' at plan time — the answer is authored later, never invented here. */
  answer_hint?: string;
}

export interface ContentPage {
  /** Normalized cluster claim (lowercased, collapsed whitespace). Not invented. */
  target_phrase: string;
  /** Deterministic heuristic: 'comparison' | 'guide' | 'answer'. */
  page_kind: string;
  /** 1-based InsightCluster.rank this page is projected from. */
  source_cluster_rank: number;
  /** FAQ items, built verbatim from brief.must_address (empty when no brief). */
  faq?: FaqItem[];
  /** Real counts: {'distinct_authors': ..., 'mentions': ...} from the cluster. */
  stat_anchors?: Record<string, number>;
  /** Deterministic markdown section headings for answer-first formatting. */
  outline?: string[];
}

export interface CitationStrategy {
  /** Example LLM prompts derived from target_phrases (for citability checks). */
  prompt_set?: string[];
  /** Deduped, disclosed quote permalinks to cite — real sources, not placeholders. */
  reddit_targets?: string[];
}

export interface ContentPlan {
  /** The DemandReport this plan was projected from. */
  report_id: string;
  /** One page per ranked InsightCluster, in rank order. */
  pages?: ContentPage[];
  /** LLM-citability play: prompt set + disclosed Reddit permalink targets. */
  citation_strategy: CitationStrategy;
}

export interface ComplianceVerdict {
  /** True if the reply is OK to post. */
  pass: boolean;
  /** Specific issues — empty when pass=True. */
  violations?: string[];
  /** Confidence in the verdict. */
  confidence: number;
}

export interface LintViolation {
  /** Stable identifier for the rule that fired (e.g., 'title_too_short'). */
  code: string;
  /** error blocks submit; warn surfaces but allows it. */
  severity: "error" | "warn";
  /** Human-readable explanation suitable for inline UI. */
  message: string;
  /** Optional [start,end] char offsets in the offending field. */
  span?: [number, number] | null;
  /** Which field the violation applies to. */
  field?: "title" | "body" | "flair" | "draft";
}

export interface PostLintVerdict {
  /** True when no `error`-severity violations fired. */
  pass: boolean;
  violations?: LintViolation[];
}

export interface RedditPost {
  /** Reddit base36 id without the 't3_' prefix. */
  post_id: string;
  /** Subreddit name without 'r/' prefix. */
  subreddit: string;
  title: string;
  /** Body text; empty for link posts. */
  selftext?: string;
  /** Full permalink to the post. */
  url: string;
  /** Username when sourced live; None when the source pseudonymizes. */
  author?: string | null;
  score?: number;
  num_comments?: number;
  created_utc?: string | null;
  flair?: string | null;
}

export interface RedditComment {
  /** Reddit base36 id without the 't1_' prefix. */
  comment_id: string;
  /** Parent submission id. */
  post_id: string;
  subreddit: string;
  body: string;
  permalink: string;
  /** Salted pseudonymous author id — pseudonymization, not anonymization. */
  author_hash: string;
  score?: number;
  created_utc?: string | null;
  /** Parent comment id for nested replies; None for top-level. */
  parent_id?: string | null;
}

export interface SubredditIntel {
  /** Subreddit name without 'r/' prefix. */
  name: string;
  title?: string | null;
  description?: string | null;
  subscribers?: number | null;
  rules?: string[];
  /** Recent top posts, for tone calibration. */
  top_post_titles?: string[];
  fetched_at?: string | null;
}

export interface InboxItem {
  message_id: string;
  /** Classification from the inbox poller. */
  kind: "comment_reply" | "post_reply" | "dm" | "mention" | "mod";
  author?: string | null;
  subject?: string | null;
  body: string;
  permalink?: string | null;
  created_utc?: string | null;
  read?: boolean;
}

export interface Opportunity {
  opportunity_id: string;
  post: RedditPost;
  /** Generated draft — a starting point, not a send. */
  draft_reply: string;
  /** Which persona the draft was written for. */
  account_type?: string | null;
  /** Why the filter kept this thread. */
  relevance_reason?: string | null;
  confidence?: number | null;
  risks?: string[];
  compliance?: ComplianceVerdict | null;
  status?: "new" | "approved" | "cancelled" | "posted";
  discovered_at?: string | null;
}

export interface Persona {
  /** Real writing samples that define the voice. */
  example_posts?: string[];
  /** Distilled description of the voice (tone, quirks, register). */
  voice_rubric?: string | null;
  /** AUTHENTIC background of the human/brand behind the account. Never fabricated. See USAGE_POLICY. */
  background?: string | null;
}

export interface PersonaSet {
  personas?: Record<string, Persona>;
}

export interface DiscoveryContext {
  voice_guidelines?: string[];
  /** Replies that performed well — style anchors. */
  winning_examples?: string[];
  /** Standing instructions from the caller. */
  pinned_notes?: string[];
  /** Topics, claims, or phrasings to never use. */
  avoid?: string[];
  personas?: PersonaSet;
}
