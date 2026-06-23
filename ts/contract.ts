// GENERATED FILE — do not edit by hand.
// Source of truth: metalworks/contract (Python, Pydantic).
// Regenerate: python scripts/gen_ts_types.py

export type Fork = "product_pinned" | "demographic_pinned" | "both";
export type SignalStrength = "low" | "medium" | "high";
export type Decision = "go" | "pivot" | "no_go";
export type ChannelSurfaceType = "launch_platform" | "marketplace" | "community" | "answer_engine_geo" | "embedded_loop" | "wedge_integration" | "borrowed_audience" | "data_asset" | "earned_media" | "social" | "search" | "app_store" | "paid" | "sales";
export type ProductType = "b2b_sales_led" | "b2b_plg" | "dev_tool" | "consumer" | "ai_product" | "marketplace" | "prosumer";

export interface EvidenceRef {
  /** Target ResolvedCitation/WebFinding/PriceEvidence id. Empty for a cluster ref. */
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

export interface CitationRef {
  /** Content-addressed citation id (``q:<hash>``); matches the resolved form's id. */
  evidence_id: string;
  /** Corpus-wide id of the backing record/comment (resolve against the corpus). */
  record_id: string;
  /** Evidence family — quote for a cluster citation. */
  kind?: "quote";
}

export interface ResolvedCitation {
  /** Stable content-addressed citation id (``q:<hash of source_url|text>``). Defaulted/recomputed by the `id` computed field; carried so a CitationRef matches. */
  evidence_id?: string;
  /** Corpus-wide id of the backing record/comment, for live re-resolution. */
  record_id?: string;
  /** Origin source, e.g. 'reddit', 'hackernews', 'reviews'. */
  source?: string;
  /** Human-readable origin label, e.g. 'r/Supplements' for Reddit. */
  source_name?: string;
  /** Resolvable link to the quote in context (the provenance link). */
  source_url?: string;
  /** Verbatim quote, exact-matched to the source comment. */
  text: string;
  /** Stable pseudonymous author id (salted hash) — for distinct-author counting, never the raw username. Pseudonymization, not anonymization. */
  author_hash: string;
  /** Source-native engagement signal (Reddit upvotes, HN points, …), for context. */
  engagement?: number;
  /** Source-specific fields that don't earn a spine column. */
  extra?: Record<string, unknown>;
  /** Stable content-addressed evidence id (``q:<hash of source_url|text>``). */
  id: string;
}

export interface InsightCluster {
  /** 1-based rank within the report (by demand_score). */
  rank: number;
  /** One-line synthesized insight (what consumers want/feel/struggle with). */
  claim: string;
  /** Ranking signal. Weights distinct-author breadth ABOVE single-post virality (50 authors x 2 upvotes outranks 1 author x 200 upvotes). */
  demand_score: number;
  /** Number of DISTINCT authors expressing this — the honest base rate, not mention count. Authored sources only (0 for authorless web; see breadth_count). */
  distinct_author_count: number;
  /** Source-neutral breadth = distinct authors + distinct domains (authorless web). The demand_score driver, so authored / web / mixed clusters rank comparably. Equals distinct_author_count for all-authored (Reddit/HN) clusters. */
  breadth_count?: number;
  /** What breadth_count counts: 'authors' (all authored), 'domains' (all authorless web), or 'voices' (mixed). */
  breadth_unit?: string;
  /** Total mentions (>= distinct_author_count). Kept separate so base-rate honesty is visible. */
  mention_count: number;
  /** Confidence chip, derived from distinct_author_count. */
  signal: SignalStrength;
  /** 2-3 verified quotes (materialized, portable). A cluster with zero verified quotes is never shipped (no-quote-no-theme). */
  quotes: ResolvedCitation[];
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

export interface EvidenceBackedChoice {
  /** Why this is a GENUINELY distinct path, not a synonym of another fork. */
  rationale?: string;
  /** Backing evidence (refs into report.evidence) — the proof this fork is real. */
  evidence?: EvidenceRef[];
  /** Confidence chip — a thin fork never reads as strong as a deep one. */
  signal?: SignalStrength;
}

export interface SegmentChoice {
  /** Why this is a GENUINELY distinct path, not a synonym of another fork. */
  rationale?: string;
  /** Backing evidence (refs into report.evidence) — the proof this fork is real. */
  evidence?: EvidenceRef[];
  /** Confidence chip — a thin fork never reads as strong as a deep one. */
  signal?: SignalStrength;
  name: string;
  profile: AudienceProfile;
  preferences?: string[];
  demand_score?: number;
  distinct_author_count?: number;
  /** id -> author-set Jaccard vs other segments; near 1.0 ⇒ NOT distinct. */
  overlap?: Record<string, number>;
  /** Stable content-addressed fork id (``s:<hash of name|evidence ids>``). */
  id: string;
}

export interface CandidateWedge {
  /** Why this is a GENUINELY distinct path, not a synonym of another fork. */
  rationale?: string;
  /** Backing evidence (refs into report.evidence) — the proof this fork is real. */
  evidence?: EvidenceRef[];
  /** Confidence chip — a thin fork never reads as strong as a deep one. */
  signal?: SignalStrength;
  label: string;
  /** The specific complaint it kills (echoes a cluster claim). */
  pain?: string;
  scope?: "minimal" | "broad" | "lateral";
  /** The SegmentChoice.id it serves, if segment-specific. */
  segment_id?: string | null;
  effort?: "S" | "M" | "L" | "XL" | null;
  /** Ranks of the InsightClusters this draws on. */
  cluster_ranks?: number[];
  /** authors + domains, as on InsightCluster. */
  breadth_count?: number;
  breadth_unit?: string;
  distinct_author_count?: number;
  /** Stable content-addressed fork id (``w:<hash of pain|scope>``). */
  id: string;
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
  /** Source-neutral origin label for this map row (e.g. 'r/Supplements'). */
  source?: string;
  /** Deprecated Reddit alias for `source`; kept additive so the pipeline's existing population still validates. Read `source`. */
  subreddit?: string;
  subscribers?: number | null;
  threads_examined?: number;
  skew?: string | null;
}

export interface MarketSizing {
  reddit_floor: number;
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
  /** Absolute cosine above which a thread is RESCUED from the auto-reject band back to the middle for the LLM to check, regardless of percentile. The recall safety valve: with `auto_reject_pct=0.50` half the corpus is rejected on rank alone, so a genuinely relevant thread mis-ranked into the bottom band would vanish unseen. 0.50 is a deliberately conservative non-None default — well above the cosine of off-topic noise, so it rescues the obvious mis-rankings without flooding the middle bucket; set None to restore the old percentile-only behavior. */
  cosine_ceiling?: number | null;
  /** How many auto-rejected threads to sample back through the LLM classifier to ESTIMATE the false-reject rate (the fraction the rank-only reject band wrongly discarded). 0 disables the backstop. The sample is classified but NOT promoted — this measures the threshold, it does not change the corpus. */
  backstop_sample_size?: number;
}

export interface SynthesisThresholds {
  /** Cosine at/above which two comments are treated as near-duplicates and merged (feeds distinct-author/breadth counts → demand magnitude). */
  dedup_cosine_threshold?: number;
  /** Max comments loaded into synthesis (engagement-sorted, so the cap chops noise not signal). */
  comment_cap?: number;
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
  synthesis_thresholds?: SynthesisThresholds;
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
  /** Estimated fraction of the auto-rejected band the LLM classifier would have kept (sampled, not exhaustive). None ⇒ backstop not run (empty band / disabled / legacy report). A high value means auto_reject_pct is too aggressive — relevant threads are being discarded on rank alone. */
  false_reject_rate?: number | null;
  /** How many auto-rejected threads the backstop sampled to estimate false_reject_rate. 0 ⇒ backstop not run. */
  false_reject_sample_size?: number;
  /** Fraction of synthesis units collapsed by embed_group near-dup merging (1 - groups/units). Surfaces breadth-collapse: a high rate means the dedup cosine threshold is folding many comments into few groups, shrinking distinct-author/breadth counts → demand magnitude. None ⇒ synthesis dedup hasn't run for this report. */
  dedup_merge_rate?: number | null;
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
  /** Stable id for this report's refresh lineage. Empty ⇒ first version (read `effective_lineage_id`, which falls back to `report_id`). */
  lineage_id?: string;
  /** Monotonic version within the lineage (1 = original run). */
  version?: number;
  /** The prior version's `report_id` this refresh supersedes. None for v1. */
  parent_report_id?: string | null;
  query: string;
  fork: Fork;
  /** The fork's pinned axis when computed; None otherwise. */
  pinned_axis?: string | null;
  /** The fork's optimized axis when computed; None otherwise. */
  optimized_axis?: string | null;
  /** Provenance of the corpus this run drew on: 'reddit_arctic_shift' | 'reddit_live' | 'hackernews' | 'reviews' | 'mixed'. */
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
  demand_summary?: string | null;
  slot_plan?: SlotPlan | null;
  audience_profile?: AudienceProfile | null;
  segments?: SegmentChoice[];
  candidate_wedges?: CandidateWedge[];
  /** Set by a surface when the user picks a segment. None ⇒ engine surfaced the fork but nothing chosen yet; deterministic callers read `default_segment`. */
  chosen_segment_id?: string | null;
  /** Picked wedge id, else None. */
  chosen_wedge_id?: string | null;
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
  landscape?: Landscape | null;
  assessment?: Assessment | null;
  ideation?: IdeaSketch | null;
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
  lineage_id?: string;
  version?: number;
  status: "queued" | "planning_brief" | "pulling_arctic_shift" | "embedding_triage" | "llm_classifying" | "analyzing_relevant" | "web_research" | "compiling" | "complete" | "failed" | "compile_failed" | "oom_chunked";
  progress?: string | null;
  error?: string | null;
  total_distinct_authors?: number | null;
  created_at: string;
  generated_at?: string | null;
  ready_at?: string | null;
}

export interface IdeaSketch {
  /** The idea in the user's / cluster's own words. */
  idea: string;
  /** The sharpened wedge/segment hypothesis, one sentence. */
  hypothesis: string;
  /** The specific pain this addresses. */
  pain?: string;
  /** Who it's for, if discernible. */
  target_segment_hint?: string;
  /** Which entry point produced this sketch. */
  provenance: "idea-first" | "evidence-first";
  /** Backing forks (evidence-first); empty for an idea-first hypothesis. */
  evidence?: EvidenceRef[];
  /** The brief to run demand on (idea-first); None evidence-first. */
  brief?: ResearchBrief | null;
  partial?: boolean;
  caveat?: string | null;
  /** Stable content-addressed id (``idea:<hash of idea|provenance>``). */
  sketch_id: string;
}

export interface IdeationResult {
  /** The report these were surfaced from. */
  report_id?: string | null;
  sketches?: IdeaSketch[];
  partial?: boolean;
  caveat?: string | null;
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
  /** Demand-cluster ranks this competitor speaks to (gap-matched + mentioned). Powers per-fork saturation — which wedge/segment this rival actually competes for. */
  addresses_clusters?: number[];
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

export interface ExistingSolution {
  /** The product name. */
  name: string;
  /** Resolvable link to the product. */
  url?: string;
  /** The product's one-line pitch, when available. */
  tagline?: string;
  /** Source-native traction signal (e.g. PH votes). */
  traction?: number;
  /** Where it was found: producthunt | web. */
  source?: string;
  /** Demand-cluster ranks this product speaks to. */
  addresses_clusters?: number[];
  /** The cluster ref this product was matched against. */
  evidence: EvidenceRef;
}

export interface Landscape {
  /** Stable id for this landscape (derived from report_id). */
  landscape_id: string;
  /** The DemandReport this landscape was derived from. */
  report_id: string;
  /** The grounded competitor map (Pillar A core). */
  competitor_map: CompetitorMap;
  /** Real shipped products, grounded to demand clusters. */
  existing_solutions?: ExistingSolution[];
  generated_at: string;
  /** True when either half degraded. */
  partial?: boolean;
  /** What to treat as lower-confidence. */
  caveat?: string | null;
}

export interface GapAnalysis {
  /** From distinct-author breadth. */
  demand_strength: SignalStrength;
  /** The demand-strength sentence (from derive_verdict). */
  demand_summary: string;
  /** How crowded the supply is — competitors + existing solutions. */
  landscape_saturation: SignalStrength;
  /** The under-served fork's label, when one exists to pivot to. */
  open_wedge?: string | null;
  /** One line: why these signals imply the decision. */
  reasoning?: string;
  /** Top fork's distinct authors as a fraction of the pull (0..1). */
  demand_prevalence?: number;
  /** Top fork's standing among peer forks (0..1); None if no peers. */
  demand_percentile?: number | null;
  /** Distance from a band edge (0..1); None if uncomputed. */
  confidence?: number | null;
  /** What the strength self-calibrated against (e.g. 'top of 4 forks'). */
  reference?: string;
}

export interface PivotTarget {
  /** Which kind of fork to pivot to. */
  kind: "segment" | "wedge";
  /** A real SegmentChoice / CandidateWedge id in the report. */
  target_id: string;
  /** Why this fork is the better bet. */
  why?: string;
}

export interface ForkVerdict {
  /** Which kind of fork this scores. */
  kind: "wedge" | "segment";
  /** A real CandidateWedge.id / SegmentChoice.id in the report. */
  fork_id: string;
  /** The fork's human label. */
  label: string;
  /** GO | NO_GO at the fork level. */
  decision: Decision;
  /** Relative strength band for this fork. */
  demand_strength: SignalStrength;
  /** Supply crowding (space-level for now — see ForkVerdict v2). */
  landscape_saturation: SignalStrength;
  /** Fraction of the pull (0..1). */
  demand_prevalence?: number;
  /** Standing among peer forks (0..1). */
  demand_percentile?: number;
  /** Distance from a band edge (0..1). */
  confidence?: number;
  distinct_author_count?: number;
}

export interface Assessment {
  /** Stable id (derived from report_id). */
  assessment_id: string;
  /** The DemandReport this verdict was computed from. */
  report_id: string;
  /** GO | PIVOT | NO_GO — deterministic from the gap. */
  decision: Decision;
  /** Human-facing argument for the decision (LLM prose). */
  rationale: string;
  /** The computed demand-vs-landscape gap. */
  gap: GapAnalysis;
  /** Where to aim instead — set iff decision == PIVOT. */
  pivot_target?: PivotTarget | null;
  /** Per-fork GO/NO-GO — the un-collapsed answer behind the top-line decision. */
  fork_verdicts?: ForkVerdict[];
  /** Backing forks for the verdict. */
  evidence?: EvidenceRef[];
  partial?: boolean;
  caveat?: string | null;
  generated_at: string;
}

export interface DecisionLogEntry {
  /** 1-based round number. */
  iteration: number;
  /** The idea this round tested. */
  idea: string;
  /** The verdict for this round. */
  decision: Decision;
  /** Forks/ideas this round eliminated — the anti-repeat memory. */
  ruled_out?: string[];
  /** One-line reasoning for the verdict. */
  why?: string;
  /** True if this round ran a fresh corpus pull; False if it reused the corpus (a PIVOT to a fork already in the report needs no re-pull). */
  fresh_pull?: boolean;
}

export interface ValidationResult {
  /** Why the loop stopped. */
  outcome: "go" | "no_go" | "exhausted";
  /** The last round's GO/PIVOT/NO-GO verdict. */
  final_assessment?: Assessment | null;
  /** One entry per round. */
  decision_log?: DecisionLogEntry[];
  /** Rounds run. */
  iterations?: number;
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

export interface Screen {
  /** Screen name. */
  name: string;
  /** What this screen is for, one line. */
  purpose: string;
  /** The single primary action on this screen. */
  primary_action: string;
  /** Ids of the BuildSpec features this screen serves (real, not invented). */
  feature_ids?: string[];
  /** True when this screen directly serves the positioning wedge. */
  serves_wedge?: boolean;
  /** True for shell screens (auth/settings) — needed by every product, not a demand hypothesis. */
  scaffolding?: boolean;
  /** Voices asking for this screen. Empty → an unvalidated hypothesis. */
  evidence_refs?: EvidenceRef[];
  /** True iff at least one evidence_ref backs the screen. */
  validated?: boolean;
}

export interface DesignBrief {
  report_id: string;
  /** A short brief for the design step (tone, surface, audience). */
  summary: string;
  /** Always present: this brief is NOT evidence-backed. */
  note?: string;
}

export interface LandscapeSignal {
  /** The pattern across competitors (directional, not cited). */
  observation: string;
  /** The design move it suggests — lean in, or break. */
  implication: string;
  /** Competitor names this signal reads from. */
  competitors?: string[];
}

export interface DesignChoice {
  /** The fixed design dimension. */
  dimension: "aesthetic" | "decoration" | "layout" | "color" | "typography" | "spacing" | "motion";
  /** The choice, concretely (e.g. 'Fraunces display + Geist body; ink #1A1A1A'). */
  decision: string;
  /** safe = category baseline; risk = a deliberate departure with a payoff. */
  stance: "safe" | "risk";
  /** Why, one line. For a RISK: what it gains and what it costs. */
  rationale: string;
}

export interface DesignSystem {
  report_id: string;
  /** The brand the system was designed for. */
  brand_name: string;
  /** The one thing someone should remember on first contact — the north star. */
  memorable_thing: string;
  /** How grounded: a real competitor teardown, web text, or model knowledge. */
  grounding_tier: "renderer" | "web" | "model_knowledge";
  /** The aesthetic direction in one line (e.g. 'editorial monochrome, dark-first'). */
  aesthetic: string;
  /** The taste preset the system was authored under (e.g. 'editorial', 'brutalist', 'warm-minimal', 'technical') — drives the director voice + preview chrome. */
  taste?: string;
  /** One per design dimension, each SAFE/RISK-labelled. */
  choices?: DesignChoice[];
  /** Directional reads of the competition that informed the system (not cited). */
  landscape_signals?: LandscapeSignal[];
  /** The rendered DESIGN.md — the per-project source of truth. */
  design_md?: string;
  generated_at: string;
  partial?: boolean;
  caveat?: string | null;
}

export interface StyleFinding {
  /** fail (hard) / warn (soft) / ok (positive note). */
  severity: "fail" | "warn" | "ok";
  category: "fonts" | "headings" | "palette" | "system_match" | "slop";
  /** What was observed and why it's flagged, one line. */
  detail: string;
}

export interface DesignReview {
  /** The page that was audited. */
  url: string;
  /** Distinct font families actually rendered. */
  fonts?: string[];
  /** Rendered h1/h2/h3 font sizes, in document order. */
  headings?: string[];
  /** The rendered body text color. */
  ink?: string;
  /** The rendered body background color. */
  background?: string;
  findings?: StyleFinding[];
  /** 10 minus penalties for findings. */
  score?: number;
  /** True when there are no fail-severity findings. */
  passed?: boolean;
  /** Whether it was graded against a DesignSystem (not just rules). */
  against_system?: boolean;
  generated_at: string;
  partial?: boolean;
  caveat?: string | null;
}

export interface LogoOption {
  /** The design angle that produced it, e.g. 'logotype'. */
  angle: string;
  /** One line: the idea behind the mark. */
  concept: string;
  /** A self-contained, validated SVG lockup (mark + wordmark). */
  svg: string;
}

export interface LogoSet {
  /** The DemandReport / DesignSystem this set was drawn for. */
  report_id: string;
  /** The wordmark name the logos were drawn for. */
  brand_name: string;
  /** Diverse options, one per design angle. */
  options?: LogoOption[];
  /** True when fewer options than requested were produced. */
  partial?: boolean;
  /** Why the set is partial / which angles were dropped. */
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

export interface Channel {
  /** Which kind of surface this channel acts on. */
  surface_type: ChannelSurfaceType;
  /** The concrete channel id, e.g. 'show_hn' | 'shopify_app_store' | a subreddit. */
  name: string;
  /** 'push' (you broadcast) vs 'pull' (they find you). */
  motion: "push" | "pull";
  /** 'spike' (a sequenced push moment) vs 'compounding' (a continuous stream). */
  cadence: "spike" | "compounding";
  /** How you get surfaced: 'algorithmic' | 'curated' (co-sell) | 'exogenous'. */
  discovery: "algorithmic" | "curated" | "exogenous";
  /** 'revenue' (sells directly) vs 'lead_gen' (feeds the funnel). */
  role: "revenue" | "lead_gen";
  /** Where in the funnel this channel acts (awareness…retention). */
  funnel_stage: "awareness" | "consideration" | "conversion" | "retention";
  /** The grounded entity/signal in the corpus that selected this channel. */
  routing_signal: string;
  /** True when this channel is an amplifier needing an initial push to ignite — marketplaces/loops don't start their own velocity. */
  requires_spark?: boolean;
  /** The channel name that ignites this one, when requires_spark is true. */
  spark_channel?: string | null;
  /** The cheap test to validate this channel (test→focus; set downstream). */
  test?: string;
  /** What result counts as the test passing — the bar to concentrate here. */
  success_threshold?: string;
  /** Honest 'worth it' read (e.g. 'PH: awareness, not conversions'). */
  worth_it_note?: string;
  /** The carried caveat/risk for this channel. */
  caveat?: string;
  /** One line: why this channel fits this product + audience. */
  rationale?: string;
}

export interface ChannelStrategy {
  /** The source report this strategy was derived from. */
  report_id: string;
  /** The classified product/ICP archetype that biased the channel routing. */
  product_type: ProductType;
  /** One-line ICP, grounded in the report (who this is for, in their words). */
  icp_summary: string;
  /** The selected channel experiments (test→focus), spanning funnel stages. */
  channels: Channel[];
  /** The test→focus guidance — 'test these N, concentrate on the winner'. */
  focusing_rule: string;
  /** Coverage note across funnel stages; flags an all-top-of-funnel plan as a leak. */
  funnel_note: string;
}

export interface ParticipationTarget {
  /** The real community to engage, e.g. 'r/SideProject' — from the report. */
  community: string;
  /** A real thread/source_url pulled from the report's verified quotes. */
  permalink: string;
  /** What the audience is asking there, grounded in a cluster claim — not fluff. */
  why: string;
  /** The honest, value-first angle to engage with (answer the question, disclose). */
  suggested_angle: string;
}

export interface CitabilityProbe {
  /** A real conversational query you want to be the cited answer to. */
  prompt: string;
  /** The cluster claim this probe maps to — the demand it traces back to. */
  target_phrase: string;
}

export interface AnswerBrief {
  /** The audience question this brief answers (a cluster claim). */
  question: string;
  /** Answer-first, grounded prose — the factual answer you want cited. */
  answer: string;
  /** Refs into report.evidence backing the answer. An answer with none is dropped. */
  evidence_refs?: EvidenceRef[];
  /** Real counts from the cluster, e.g. {'distinct_authors': 12, 'mentions': 30}. */
  stat_anchors?: Record<string, number>;
}

export interface GeoPlan {
  /** The source report this GEO plan was derived from. */
  report_id: string;
  /** Real threads/communities to engage, from the report's permalinks. */
  participation_targets?: ParticipationTarget[];
  /** Conversational queries to test citation, from the cluster claims. */
  citability_probes?: CitabilityProbe[];
  /** Answer-first grounded briefs; each resolves against report.evidence. */
  answer_briefs?: AnswerBrief[];
}

export interface DataReportItem {
  /** 1-based rank, copied from the source cluster's rank. */
  rank: number;
  /** The claim/feature/complaint headline for this row, framed to the report kind. LLM-written from the cluster's claim — the only authored prose in the row. */
  label: string;
  /** DISTINCT authors expressing this — copied from the cluster's distinct_author_count, the honest base rate. Never invented. */
  distinct_authors: number;
  /** Total mentions (>= distinct_authors) — copied from the cluster's mention_count. Kept separate so base-rate honesty stays visible. */
  mentions: number;
  /** Real provenance links — the source_urls of the cluster's verified quotes. */
  permalinks: string[];
  /** One verbatim supporting quote from the cluster (exact text, not paraphrased). */
  quote: string;
}

export interface DataReportAsset {
  /** The source demand report this asset was derived from. */
  report_id: string;
  /** The framing: 'complaint_index' (pain points), 'feature_ranking' (requested features), or 'state_of' (the overall state of the category). */
  kind: "complaint_index" | "feature_ranking" | "state_of";
  /** The report headline, LLM-written and grounded in the report's query + kind. */
  title: string;
  /** The ranked rows, projected deterministically from the report's clusters. */
  items: DataReportItem[];
  /** The disclosed honest base: N threads analyzed, distinct-author counting, and the corpus date range — the rigor that IS the credibility. */
  methodology: string;
}

export interface AssetPart {
  /** Which channel-shaped span this is — tagline | maker_comment | gallery_caption | title | first_comment | tweet | carousel_slide | … */
  role: string;
  /** The copy for this span (appears verbatim in the asset body). */
  text: string;
}

export interface ChannelAsset {
  /** The channel this asset is for (matches Channel.name). */
  channel_name: string;
  /** The channel's surface type — which shaped the parts. */
  surface_type: ChannelSurfaceType;
  /** Where in the funnel this asset acts (carried from the channel). */
  funnel_stage: "awareness" | "consideration" | "conversion" | "retention";
  /** The concatenated/back-compat copy; parts' text + claim spans index into it. */
  body: string;
  /** The channel-shaped spans (e.g. PH: tagline + maker_comment + captions). */
  parts?: AssetPart[];
  /** The per-channel CTA / conversion ask — persuasive, not grounded. Never an 'upvote us' ask. */
  offer?: string;
  /** Grounded DEMAND/factual claims only — each resolves against report.evidence; persuasive hooks/CTAs are free and not listed here. */
  claim_citations?: ClaimCitation[];
}

export interface LoopRequirement {
  /** The loop mechanic this requirement set serves. */
  loop_kind: "watermark" | "ugc_seo" | "referral" | "free_tool" | "oss" | "single_player";
  /** Concrete things the build must ship for this loop, e.g. ['public_share_urls', 'branded_viewer', 'badge_gating'] for a watermark; ['ssr_public_pages', 'sitemap'] for UGC-SEO; ['solo_aha_before_invite'] for single_player. */
  build_requirements: string[];
  /** Why the build needs this, grounded in the selected channel's routing_signal. */
  rationale: string;
}

export interface ConversionSurfaceRequirement {
  /** The surface channels point at, e.g. 'landing_page' | 'in_product_onboarding'. */
  destination: string;
  /** The conversion job this destination does for the funnel (what it converts). */
  funnel_job: string;
  /** Concrete things the conversion destination must ship, e.g. ['above_fold_value_prop', 'single_primary_cta', 'instrumented_signup']. */
  build_requirements: string[];
  /** Why the build needs a conversion destination, grounded in the channel plan. */
  rationale: string;
}

export interface FeatureSpec {
  /** Stable slug for the feature (e.g. 'fade-tracker'). */
  feature_id: string;
  /** The feature, in a few words. */
  title: string;
  /** Why this feature — what consumer pain it serves. */
  rationale: string;
  /** ≥1 resolvable ref backing the feature. Empty → dropped at assembly. */
  evidence?: EvidenceRef[];
  /** 1-based rank of the demand cluster this feature derives from (1 = strongest validated demand). Features in a BuildSpec are ordered by this — the build order is grounded in demand, not LLM whim; the lead feature is the spine to build first. 0 means unranked (sorts last). */
  source_cluster_rank?: number;
}

export interface BuildPersona {
  /** Short persona label. */
  name: string;
  /** Who they are + what they want, one or two lines. */
  description: string;
  evidence?: EvidenceRef[];
}

export interface PricingTier {
  /** Tier name (e.g. 'Starter'). */
  name: string;
  /** Monthly price; None when unpriced. */
  price?: number | null;
  currency?: string;
  /** What the tier includes / why this price. */
  rationale: string;
  evidence?: EvidenceRef[];
}

export interface BuildSpec {
  /** Stable id for this spec (derived from report_id). */
  spec_id: string;
  report_id: string;
  /** The surface this build targets. */
  surface: "sdk" | "web" | "mobile" | "cli" | "browser_extension" | "api" | "desktop";
  /** The chosen starter/stack hint (e.g. 'next-shipfast', 'empty'). */
  stack: string;
  /** Core features, ordered as the build order: strongest validated demand first (by ``FeatureSpec.source_cluster_rank``). features[0] is the spine — build it first. */
  features?: FeatureSpec[];
  /** One line on why this surface, set when the surface was chosen automatically (``surface='auto'``). None when the surface was pinned by the caller. */
  surface_rationale?: string | null;
  personas?: BuildPersona[];
  pricing_tiers?: PricingTier[];
  /** The build's UX skeleton, sketched AFTER the features so each screen maps to real ``feature_id``s. Shell screens (auth/settings) are flagged ``scaffolding``. */
  screens?: Screen[];
  /** Distribution-driven build requirements (D3): one entry per selected embedded-loop channel — the build face of a designed-in loop (watermark ⇒ public share-URLs + branded viewer + badge-gating; UGC-SEO ⇒ SSR pages + sitemap; …). Empty when distribution requirements weren't supplied or no loop channel was selected. */
  loop_requirements?: LoopRequirement[];
  /** Distribution-driven build requirements (D3): the conversion destination the channels point at (its funnel job + what it must ship) — the build must include a place to convert. Empty when distribution requirements weren't supplied. */
  conversion_surface_requirements?: ConversionSurfaceRequirement[];
  partial?: boolean;
  caveat?: string | null;
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
