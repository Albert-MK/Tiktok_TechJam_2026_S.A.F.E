export const versionMetrics = {
  meta: {
    sampleCount: 200,
    theoreticalCeiling: 0.983,
    updated: '2026-08-31',
  },
  versions: [
    { id: 'baseline', label: 'Baseline', phase: 'Baseline', paradigm: 'Official weak BM25, stateless and no questions', hit: .125, mrr: .068, mttc: 9.81, efficiency: .119, score: .107, delta: null },
    { id: 'v0.2', label: 'v0.2', phase: 'Dialogue state', paradigm: 'Slot extraction and typed attribute questions', hit: .775, mrr: .528, mttc: 4.98, efficiency: .602, score: .666, delta: .559 },
    { id: 'v0.3', label: 'v0.3', phase: 'Dialogue state', paradigm: 'Ask other first to capture long constraints', hit: .86, mrr: .536, mttc: 3.66, efficiency: .734, score: .738, delta: .072 },
    { id: 'v0.5', label: 'v0.5', phase: 'Dialogue state', paradigm: 'Preserve valid slots through Intent Override', hit: .915, mrr: .53, mttc: 3.16, efficiency: .784, score: .773, delta: .035 },
    { id: 'v0.6', label: 'v0.6', phase: 'Dialogue state', paradigm: 'Profile tags as weak reranking signals only', hit: .925, mrr: .581, mttc: 3.05, efficiency: .795, score: .796, delta: .023 },
    { id: 'v0.7', label: 'v0.7', phase: 'Dialogue state', paradigm: 'Exact phrase recall and category AND', hit: .965, mrr: .667, mttc: 2.66, efficiency: .834, score: .85, delta: .054 },
    { id: 'v0.9', label: 'v0.9', phase: 'Dialogue state', paradigm: 'Exclude previously shown non-hits', hit: .995, mrr: .682, mttc: 2.39, efficiency: .861, score: .874, delta: .024 },
    { id: 'v1.0', label: 'v1.0', phase: 'Dialogue state', paradigm: 'Boundary fallback, re-ask other', hit: 1, mrr: .695, mttc: 2.35, efficiency: .865, score: .8815, delta: .0075 },
    { id: 'v1.1', label: 'v1.1', phase: 'Retrieval tuning', paradigm: 'Long-phrase boost and category must-match', hit: 1, mrr: .703, mttc: 2.385, efficiency: .8615, score: .8831, delta: .0016 },
    { id: 'v1.2', label: 'v1.2', phase: 'Retrieval tuning', paradigm: 'Leaf category, distinctiveness, store, and BM25 weights', hit: 1, mrr: .753, mttc: 2.44, efficiency: .856, score: .8971, delta: .014 },
    { id: 'v1.3', label: 'v1.3', phase: 'Retrieval tuning', paradigm: 'Entry-prefix match and weak profile weighting', hit: 1, mrr: .756, mttc: 2.44, efficiency: .856, score: .8979, delta: .0008 },
    { id: 'v1.4', label: 'v1.4', phase: 'Retrieval tuning', paradigm: 'Delay turn one when no hard constraint exists', hit: 1, mrr: .812, mttc: 2.61, efficiency: .839, score: .9114, delta: .0135 },
    { id: 'v1.5', label: 'v1.5', phase: 'Retrieval tuning', paradigm: 'Wait for two constraints and lower title BM25', hit: 1, mrr: .825, mttc: 2.64, efficiency: .836, score: .9148, delta: .0034 },
    { id: 'v2.0', label: 'v2.0', phase: 'Inverse inference', paradigm: 'Bayesian inversion and decision-theoretic dialogue', hit: 1, mrr: 1, mttc: 1.99, efficiency: .901, score: .9802, delta: .0654 },
  ],
  scenarioMilestones: {
    'v1.0': {
      Buying: { mrr: .674, mttc: 1.8 },
      Browsing: { mrr: .667, mttc: 2.14 },
      'Intent Override': { mrr: .819, mttc: 4.03 },
      Boundary: { mrr: .717, mttc: 3.4 },
    },
    'v1.5': {
      Buying: { mrr: .832, mttc: 2.29 },
      Browsing: { mrr: .791, mttc: 2.28 },
      'Intent Override': { mrr: .858, mttc: 4.1 },
      Boundary: { mrr: .95, mttc: 4 },
    },
    'v2.0': {
      Buying: { mrr: 1, mttc: 1.51 },
      Browsing: { mrr: 1, mttc: 1.76 },
      'Intent Override': { mrr: 1, mttc: 3.7 },
      Boundary: { mrr: 1, mttc: 2.5 },
    },
  },
  ablations: [
    { name: 'Full v2.0', score: .9802 },
    { name: 'Batch Top-10', score: .9109 },
    { name: 'No elimination', score: .9709 },
    { name: 'Card paraphrase', score: .9743 },
    { name: 'Foreign card', score: .8294 },
  ],
  customerProbe: [
    { version: 'v1.5', score: .9118 },
    { version: 'v2.0', score: .9799 },
  ],
};
