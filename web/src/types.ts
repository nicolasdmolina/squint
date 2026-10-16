// Shapes from docs/api-contract.md (v1 plus the v1.1 and v1.2 amendments). The server is the source of truth; keep these in step.

export type ModelPair = { observer: string; performer: string };

export type Session = { authenticated: boolean; password_required: boolean };

export type Status = {
  model_state: 'unloaded' | 'loading' | 'ready';
  queue_length: number;
  model_pair: ModelPair;
  calibration: { version: string | null; ready: boolean };
  /** v1.2: the trained detector that decides verdicts at 50+ words */
  classifier?: { version: string | null; ready: boolean; min_words: number | null };
  limits: { min_words: number; percent_min_words: number; max_words: number; checks_per_hour: number };
};

export type Band = 'likely_human' | 'uncertain' | 'likely_ai' | 'uncalibrated' | 'too_short';
export type Lean = 'ai' | 'neutral' | 'human';
export type LengthBucket = '20-49' | '50-149' | '150+';

export type TopGuess = { text: string; p: number };

export type Token = {
  i: number;
  start: number;
  end: number;
  text: string;
  /** null on the first token: it has no context, so it is never scored (v1.1) */
  surprise: number | null;
  expected_surprise: number | null;
  signal: number;
  signal_smooth: number;
  rank: number | null;
  /** empty on the unscored first token */
  top: TopGuess[];
  sentence: number;
};

export type Sentence = {
  i: number;
  start: number;
  end: number;
  token_start: number;
  token_end: number;
  score: number;
  lean: Lean;
  paragraph: number;
};

export type Paragraph = { i: number; start: number; end: number; score: number; lean: Lean };

export type Segment = {
  start: number;
  end: number;
  word_start: number;
  word_end: number;
  score: number;
  flagged: boolean;
};

export type Reason = { kind: string; text: string; weight: 'strong' | 'moderate' | 'weak' };

export type Verdict = {
  band: Band;
  label: string;
  confidence: 'normal' | 'low';
  length_bucket: LengthBucket;
  /** v1.2: which method set the band. Absent from older servers, which means binoculars. */
  detector?: 'classifier' | 'binoculars';
  /** the Binoculars score; it sets the band only when detector is binoculars */
  score: number;
  thresholds: { ai_below: number; human_above: number } | null;
  classifier?: {
    ai_probability: number | null;
    ai_above: number;
    human_below: number;
    min_words: number;
    version: string | null;
  } | null;
  ai_percent: number | null;
  explanation: string;
};

export type Result = {
  word_count: number;
  token_count: number;
  model_pair: ModelPair;
  verdict: Verdict;
  reasons: Reason[];
  stats: {
    top1_rate: number;
    top5_rate: number;
    mean_surprise: number;
    mean_expected_surprise: number;
    /** null with fewer than two sentences of 8+ scored tokens (v1.1) */
    sentence_score_spread: number | null;
  };
  tokens: Token[];
  sentences: Sentence[];
  paragraphs: Paragraph[];
  segments: Segment[];
  timing_ms: { queue: number; load: number; score: number };
};

export type JobStatus = 'queued' | 'loading_model' | 'scoring' | 'done' | 'error';

export type Job = {
  job_id: string;
  status: JobStatus;
  position: number;
  result: Result | null;
  error: ApiErrorBody['error'] | null;
};

export type Accuracy = {
  version: string;
  model_pair: ModelPair;
  held_out: { human: number; ai: number };
  false_flag_rate: { overall: number; non_native: number; by_length: Partial<Record<LengthBucket, number>> };
  catch_rate: {
    overall: number;
    by_source: Record<string, number>;
    by_length: Partial<Record<LengthBucket, number>>;
  };
  uncertain_rate: { human: number; ai: number };
  notes: string[];
  /** v1.2: held-out results for the trained detector (calibration/classifier.json) */
  classifier?: ClassifierAccuracy;
};

export type Count = { n: number; flagged: number; rate: number; ci95?: [number, number] };
export type GenCell = { n: number; caught: number; called_human: number };
export type ClassifierAccuracy = {
  version: string;
  model: string;
  min_words: number;
  held_out: { false_flags: Count; false_flags_non_native: Count; chatgpt_catch: Count };
  by_length: Partial<Record<LengthBucket, { humans: number; false_flag: number | null; humans_likely_human: number | null } & Record<string, unknown>>>;
};

export type ApiErrorBody = { error: { code: string; message: string; retry_after_s?: number } };
