import { lazy, Suspense, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import BackgroundVideo from '../components/BackgroundVideo';
import Footer from '../components/Footer';
import HeroBackground from '../components/HeroBackground';
import Nav from '../components/Nav';
import ProductPreview from '../components/ProductPreview';
import { usePageSetup } from '../hooks';

const VersionDashboard = lazy(() => import('../components/VersionDashboard'));

const benchmarkMetrics = [
  ['0.9802', 'TechnicalScore', '200 public benchmark sessions'],
  ['100.0%', 'Hit Rate@10', '200 / 200 scenarios solved'],
  ['1.000', 'MRR', 'Every target placed at Rank 1'],
  ['1.99', 'MTTC', 'Fewer than 2 turns on average'],
  ['78.8 ms', 'Average latency', '0 tokens · 0 external APIs'],
];

const scenarioRows = [
  ['Buying', '40%', 'Hard constraints from the first turn enable fast, precise convergence.'],
  ['Browsing', '40%', 'The session begins broad, so the agent must explore proactively.'],
  ['Intent Override', '15%', 'Preferences reverse in turns 3–4, forcing the belief state to adapt.'],
  ['Boundary', '5%', 'The system recovers when attribute questions receive no preference.'],
];

const evolutionStory = [
  ['0.666', 'Ask', 'Break the deadlock', 'TechnicalScore, up from the 0.107 baseline', 'Typed attribute questions turn ten empty turns into useful evidence. This single move lifts the score from 0.107 to 0.666.'],
  ['0.773', 'Remember', 'Let state survive change', 'TechnicalScore after Intent Override continuity', 'Distinctive constraints arrive first, while category and valid hard constraints persist through Intent Override instead of being blindly reset.'],
  ['0.882', 'Eliminate', 'Make every miss compound', 'TechnicalScore with stable recall and negative evidence', 'Stable recall, exclusion of shown non-hits, and Boundary recovery turn negative feedback into free evidence and complete all 200 sessions.'],
];

const rankingAblations = [
  ['+0.0047', 'Leaf category boost', 'Prioritize agreement on the deepest category nodes.'],
  ['+0.0049', 'Relaxed distinctiveness', 'Let exclusive long phrases dominate the score.'],
  ['+0.0016', 'Store and brand weighting', 'Use store metadata as a secondary ranking signal.'],
  ['+0.0008', 'Entry prefix consistency', 'Reward alignment with product-detail prefixes, lifting MRR to 0.756.'],
];

const pillars = [
  ['01', 'Rating-Count Prior', 'Targets come from real purchase records, so P(target = p) is proportional to rating_number(p). The target median is 6,846 ratings versus 12 for the catalog; turn-one Top-1 accuracy reaches 35.0%, near the 37.1% ceiling.'],
  ['02', 'Counterfactual Belief Tracking', 'For every candidate, replay the dialogue: positive descriptions must match its intent card, no-preference statements penalize candidates that should still speak, and prior misses become soft exclusions.'],
  ['03', 'Sequential Single-Guess', 'One extra turn costs 0.02, while dropping from rank one to two costs 0.15. Submit only the highest-posterior candidate: a hit locks MRR at 1.000; a miss becomes free elimination evidence.'],
  ['04', 'Optimal Experimental Design', 'Simulate the expected score after splitting candidates by each possible attribute, then ask the question with the highest decision value rather than follow a fixed script.'],
];

const robustnessRows = [
  ['Official derivation', 'Verbatim', '0.9802', '1.000'],
  ['Official derivation', 'Paraphrased', '0.9743', '1.000'],
  ['Foreign source', 'Verbatim', '0.8939', '0.950'],
  ['Foreign source', 'Paraphrased', '0.8294', '0.915'],
];

const scenarioResults = [
  ['Buying', '1.51 turns', 'Theoretical limit ≈ 1.43'],
  ['Browsing', '1.76 turns', 'Theoretical limit ≈ 1.64'],
  ['Intent Override', '3.70 turns', 'Theoretical floor ≈ 3.60'],
  ['Boundary', '2.50 turns', 'Theoretical floor ≈ 2.15'],
];

const takeaways = [
  ['01', 'Mechanism depth beats brute-force compute', 'Model the customer’s generative process and the evaluation utility instead of buying accuracy with external model calls.'],
  ['02', 'Decision theory removes ranking error', 'Sequential single-guess turns each successful recommendation into a rank-one lock and every miss into useful evidence.'],
];

export default function ProductPage() {
  usePageSetup('product-page');
  const location = useLocation();

  useEffect(() => {
    document.title = 'TikTok TechJam | Beyond Retrieval';
    if (location.hash) document.querySelector(location.hash)?.scrollIntoView({ behavior: 'smooth' });
  }, [location.hash]);

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <Nav />
      <main id="main">
        <section className="sky-hero product-hero has-media" aria-labelledby="hero-title">
          <HeroBackground />
          <div className="sky-noise" aria-hidden="true" />
          <div className="hero-copy reveal is-visible">
            <p className="eyebrow light">Conversational E-Commerce Search</p>
            <h1 id="hero-title">Beyond Retrieval:<br />Inverting the Generative Process.</h1>
            <p className="hero-lede">A conversational search agent built on inverse generative modeling and decision theory, evaluated across 50,000 products and 200 public sessions.</p>
            <p className="hero-proof" aria-label="Efficiency highlights">
              <span>1.99 average turns</span>
              <span>78.8 ms average latency</span>
              <span>0 tokens · 0 external APIs</span>
            </p>
            <div className="hero-trajectory" aria-label="TechnicalScore journey">
              <span><small>Baseline</small><strong>0.107</strong></span>
              <i aria-hidden="true">→</i>
              <span><small>Retrieval ceiling</small><strong>0.9148</strong></span>
              <i aria-hidden="true">→</i>
              <span className="is-current"><small>Inverse inference</small><strong>0.9802</strong></span>
            </div>
            <Link className="button button-light" to="/demo">Open live demo <span aria-hidden="true">↗</span></Link>
          </div>
          <ProductPreview />
        </section>

        <section id="overview" className="intro benchmark-intro section-pad scroll-chapter" data-scroll-chapter data-chapter="01 / Overview" aria-labelledby="overview-title">
          <div className="recording-frame overview-challenge-frame">
            <p className="eyebrow reveal">Overview &amp; Benchmark</p>
            <h2 className="reveal" id="overview-title">Find the hidden target.<br />Put it at Rank 1.</h2>
            <div className="intro-grid reveal">
              <p className="lead-copy">The challenge is not merely to find a plausible product. The hidden Target ASIN must reach Rank 1 in the fewest possible conversational turns.</p>
              <p>Users arrive with vague, shifting, and fragmented intent. The agent must infer one hidden item from the Amazon 2023 Clothing, Shoes &amp; Jewelry catalog within at most ten turns.</p>
            </div>
          </div>
          <div className="recording-frame overview-benchmark-frame">
            <div className="benchmark-rail reveal reveal-rail" aria-label="Core benchmark results">
              {benchmarkMetrics.map(([value, label, note]) => <Metric key={label} value={value} label={label} note={note} />)}
            </div>
            <div className="challenge-layout reveal">
              <div>
                <p className="eyebrow">Challenge mix</p>
                <h3>Four conversation modes test convergence and continuity.</h3>
              </div>
              <div className="scenario-list">
                {scenarioRows.map(([name, share, copy]) => <div key={name}><strong>{name}</strong><span>{share}</span><p>{copy}</p></div>)}
              </div>
            </div>
          </div>
          <div className="recording-frame overview-formula-frame">
            <div className="frame-heading reveal">
              <p className="eyebrow">Official scoring formula</p>
              <h3>Accuracy, rank quality, and conversational efficiency share one score.</h3>
            </div>
            <div className="score-formula reveal" aria-label="Official scoring formula">
              <span>TechnicalScore = 0.50 × Hit@10 + 0.30 × MRR + 0.20 × Efficiency</span>
              <small>Efficiency = clip((11 − MTTC) / 10, 0, 1)</small>
            </div>
          </div>
        </section>

        <section id="evolution" className="evolution-section section-pad scroll-chapter" data-scroll-chapter data-chapter="02 / Evolution" aria-labelledby="evolution-title">
          <div className="section-heading recording-frame reveal reveal-stack">
            <p className="eyebrow">From 0 to 1</p>
            <h2 id="evolution-title">Breaking through: from passive retrieval to active exploration.</h2>
            <p>The official baseline only feeds the latest utterance into BM25 and never asks a valid question. Typed questions, continuous state, stable candidate recall, and free elimination evidence move the system from 0.107 to 0.882.</p>
          </div>
          <div className="evolution-story" data-scroll-story="evolution" data-active-step="0">
            <div className="evolution-story-stage" aria-hidden="true">
              <p>System evolution</p>
              <div className="evolution-story-scores">
                {evolutionStory.map(([score, title], index) => (
                  <div className={index === 0 ? 'is-active' : ''} data-story-panel={index} key={score}>
                    <strong>{score}</strong>
                    <span>{title}</span>
                  </div>
                ))}
              </div>
              <div className="evolution-story-meter" style={{ '--evolution-count': evolutionStory.length }}>
                {evolutionStory.map(([, title], index) => <i className={index === 0 ? 'is-active' : ''} data-story-marker={index} aria-label={title} key={title} />)}
              </div>
            </div>
            <div className="evolution-story-steps">
              {evolutionStory.map(([score, title, label, context, copy], index) => (
                <article className={`recording-frame${index === 0 ? ' is-active' : ''}`} data-scroll-step data-step-index={index} key={score}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <p>{label}</p>
                  <h3>{title}</h3>
                  <strong>{score}</strong>
                  <div className="evolution-step-support">
                    <em>{context}</em>
                    <small>{copy}</small>
                  </div>
                </article>
              ))}
            </div>
          </div>
          <div className="recording-frame evolution-lessons-frame">
            <div className="frame-heading reveal"><p className="eyebrow">Three lessons</p><h3>Active dialogue converts every turn into evidence.</h3></div>
            <div className="lesson-band reveal" aria-label="Three lessons from active dialogue">
              <article><span>01</span><h3>Questions unlock information</h3><p>Moving from passive waiting to other, material, color, and typed follow-ups breaks the deadlock.</p></article>
              <article><span>02</span><h3>Override is not a reset</h3><p>The target stays constant, so category and still-valid hard constraints must survive preference reversals.</p></article>
              <article><span>03</span><h3>Misses are free evidence</h3><p>If a session continues after a Top-10 submission, every shown item is definitively not the target.</p></article>
            </div>
          </div>
        </section>

        <section id="ranking" className="ranking-section section-pad scroll-chapter" data-scroll-chapter data-chapter="03 / Retrieval Ceiling" aria-labelledby="ranking-title">
          <div className="recording-frame ranking-ablation-frame">
            <div className="section-heading reveal reveal-stack">
              <p className="eyebrow">The retrieval ceiling</p>
              <h2 id="ranking-title">Fine-grained reranking, then a deliberate wait.</h2>
              <p>Once Hit@10 reached 100%, the problem changed. The system had to protect rank quality and decide when one more question was worth more than an early recommendation.</p>
            </div>
            <div className="ablation-ledger reveal" aria-label="Ranking ablations">
              {rankingAblations.map(([gain, title, copy]) => <article key={title}><strong>{gain}</strong><div><h3>{title}</h3><p>{copy}</p></div></article>)}
            </div>
          </div>
          <div className="stopping-rule recording-frame reveal">
            <div>
              <p className="eyebrow">Strategic delayed submission</p>
              <h3>Trade a controlled turn cost for a guaranteed Rank 1.</h3>
              <p>The evaluator locks rank the first time the target enters Top-10. An early rank-eight hit contributes only 0.125 MRR, while one extra question costs just 0.02 efficiency.</p>
            </div>
            <div className="utility-tradeoff" aria-label="Expected value comparison">
              <span><small>Early submission</small><strong>1 / 8</strong><em>MRR at rank 8</em></span>
              <i aria-hidden="true">→</i>
              <span><small>One more question</small><strong>1.000</strong><em>MRR at rank 1</em></span>
            </div>
          </div>
          <div className="recording-frame strategy-frame">
            <div className="frame-heading reveal"><p className="eyebrow">v1.4 to v1.5</p><h3>Delay submission until the posterior can support Rank 1.</h3></div>
            <div className="strategy-steps reveal">
              <article><span>v1.4</span><h3>Delay generic turn one</h3><p>Submit an empty list when no hard constraint exists.</p><strong>0.898 → 0.911</strong></article>
              <article><span>v1.5</span><h3>Wait for two constraints</h3><p>Lower title BM25 weight and gather one more discriminative answer.</p><strong>0.911 → 0.9148</strong></article>
            </div>
          </div>
        </section>

        <section id="limits" className="limits-section section-pad scroll-chapter chapter-dark" data-scroll-chapter data-chapter="04 / Failed Experiments" aria-labelledby="limits-title">
          <div className="recording-frame failed-experiments-frame">
            <div className="limits-heading reveal reveal-stack">
              <p className="eyebrow light">Hitting the ceiling</p>
              <h2 id="limits-title">Why retrieval cannot break 0.92.</h2>
              <p>Information-theoretic questioning and profile priors looked promising, but both optimized signals the customer could not reliably reveal.</p>
            </div>
            <div className="failed-experiments reveal reveal-rail">
              <article><span>v7</span><h3>Adaptive Narrow</h3><strong>0.904</strong><p>Candidate-set entropy is not the same as intent a customer can express. Brand entropy may be high, yet the question is often rejected in Boundary sessions.</p></article>
              <article><span>v8</span><h3>Profile Branch</h3><strong>0.903</strong><p>Historical profiles showed no reliable correlation with the current target leaf category. Forcing them in amplified a weak signal into a harmful prior.</p></article>
            </div>
          </div>
          <div className="recording-frame retrieval-limits-frame">
            <div className="frame-heading reveal"><p className="eyebrow light">Three structural limits</p><h3>Retrieval optimizes resemblance, not the hidden generative process.</h3></div>
            <div className="retrieval-limits reveal">
              <article><span>01</span><h3>The wrong question</h3><p>Text resemblance does not answer which product generated the customer’s words.</p></article>
              <article><span>02</span><h3>An unstable state space</h3><p>The Top-80 pool reshuffles each turn, preventing belief from converging monotonically.</p></article>
              <article><span>03</span><h3>A measured ceiling</h3><p>Submitting Top-10 every turn scores 0.9109, confirming the limit of retrieval plus heuristics.</p></article>
            </div>
          </div>
          <div className="ceiling-line recording-frame reveal"><span>Forward retrieval ceiling</span><strong>0.9148</strong><p>Additional retrieval heuristics cannot break this measured limit. More features tune the surface; they do not repair the underlying inference problem.</p></div>
        </section>

        <section id="inference" className="paradigm-section section-pad scroll-chapter" data-scroll-chapter data-chapter="05 / Paradigm Shift" aria-labelledby="paradigm-title">
          <div className="recording-frame paradigm-intro-frame">
            <div className="algorithm-heading reveal reveal-stack">
              <div><p className="eyebrow">The inverse problem</p><h2 id="paradigm-title">Reframing search as Bayesian inference.</h2></div>
              <p>Instead of asking which product looks most like the user’s words, we ask which product, passed through the customer’s cognition and language-generation process, would produce the evidence we observed.</p>
            </div>
            <div className="question-shift reveal" aria-label="The change from forward retrieval to inverse inference">
              <p className="eyebrow">The question changed</p>
              <div>
                <article>
                  <span>Forward retrieval</span>
                  <strong>Which product resembles what the customer said?</strong>
                  <small>Similarity produces a shifting candidate pool and unstable ranks.</small>
                </article>
                <i aria-hidden="true">→</i>
                <article className="is-answer">
                  <span>Inverse inference</span>
                  <strong>Which product would generate exactly these words?</strong>
                  <small>A posterior over all 50,000 products can now converge.</small>
                </article>
              </div>
            </div>
          </div>
          <div className="paradigm-story" data-scroll-story="belief" data-active-step="0">
            <div className="recording-frame formula-frame">
              <p className="eyebrow">Bayesian posterior</p>
              <blockquote className="belief-formula reveal">
                <span className="formula-posterior">log P(p | Dialogue)</span>
                <span aria-hidden="true"> = </span>
                <span className="formula-prior">log P<sub>prior</sub>(p)</span>
                <span aria-hidden="true"> − </span>
                <span className="formula-evidence">Σ Penalty<sub>t</sub>(p)</span>
              </blockquote>
              <p className="formula-explanation">The posterior starts with how likely a product is to be purchased, then subtracts every contradiction accumulated across the dialogue.</p>
            </div>
            <div className="pillar-list">
              {pillars.map(([number, title, copy], index) => <article className={`pillar-row recording-frame reveal${index === 0 ? ' is-active' : ''}`} data-scroll-step data-step-index={index} key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p></article>)}
            </div>
          </div>
          <div className="comparison-band recording-frame reveal">
            <div><small>v1.5</small><strong>0.9148</strong><span>Traditional retrieval</span></div>
            <span aria-hidden="true">→</span>
            <div><small>v2.0</small><strong>0.9802</strong><span>Bayesian inverse inference</span></div>
            <p>MRR 0.825 → 1.000 · MTTC 2.64 → 1.99</p>
          </div>
        </section>

        <section id="engineering" className="engineering-section section-pad scroll-chapter" data-scroll-chapter data-chapter="06 / Engineering" aria-labelledby="engineering-title">
          <div className="recording-frame engineering-metrics-frame">
            <div className="section-heading reveal reveal-stack">
              <p className="eyebrow">Engineering &amp; Robustness</p>
              <h2 id="engineering-title">Zero tokens. <span className="engineering-inline-metric">78.8 ms.</span><br />Three layers of defense.</h2>
            </div>
            <div className="engineering-specs">
              <Metric value="0" label="External LLM calls" note="Zero token consumption" />
              <Metric value="7.2 s" label="Index build" note="One pass over 50,000 products" />
              <Metric value="191 MB" label="Resident memory" note="No GPU or vector database" />
              <Metric value="78.8 ms" label="Mean latency" note="27.1 ms p50 · 291.5 ms p95" />
            </div>
          </div>
          <div className="recording-frame engineering-table-frame">
            <div className="frame-heading"><p className="eyebrow">Adversarial robustness</p><h3>The inference pipeline degrades gracefully when intent wording changes.</h3></div>
            <DataTable label="Adversarial robustness" headers={['Intent source', 'Expression', 'Score', 'Hit@10']} rows={robustnessRows} reveal={false} />
          </div>
          <div className="recording-frame failsafe-frame">
            <div className="frame-heading"><p className="eyebrow">Three fail-safe mechanisms</p><h3>Defensive parsing keeps uncertain evidence from corrupting the posterior.</h3></div>
            <div className="failsafe-list">
              <article><span>01</span><h3>Longest-category reverse lookup</h3><p>If template parsing fails, the system searches the text for the longest known category in the catalog.</p></article>
              <article><span>02</span><h3>No-information smoothing</h3><p>When intent is uncertain, the agent drops negative evidence rather than contaminating the posterior with a false assumption.</p></article>
              <article><span>03</span><h3>IDF-weighted soft matching</h3><p>Recall is driven by high-information content words, reducing noise from wrapper language and synonymous phrasing.</p></article>
            </div>
          </div>
        </section>

        <section id="results" className="results-section section-pad scroll-chapter chapter-dark" data-scroll-chapter data-chapter="07 / Leaderboard" aria-labelledby="results-title">
          <div className="results-heading recording-frame reveal reveal-stack">
            <p className="eyebrow light">Leaderboard &amp; Demo Sandbox</p>
            <h2 id="results-title">The full trajectory, measured against each scenario’s limit.</h2>
          </div>
          <Suspense fallback={<div className="vd-loading" role="status">Loading evaluation dashboard…</div>}>
            <VersionDashboard />
          </Suspense>
          <div className="recording-frame scenario-limit-frame">
            <div className="frame-heading reveal"><p className="eyebrow light">Per-scenario theoretical limits</p><h3>Observed turn counts sit close to the information floor of every conversation mode.</h3></div>
            <div className="scenario-results reveal reveal-rail">
              {scenarioResults.map(([name, result, limit]) => <div key={name}><span>{name}</span><strong>{result}</strong><small>{limit}</small></div>)}
            </div>
          </div>
          <div className="recording-frame final-result-frame">
            <div className="result-summary reveal"><span>Final TechnicalScore</span><strong>0.9802</strong><p>Hit@10 1.000 · MRR 1.000 · MTTC 1.99 · Token Cost 0. The system closes most sessions in two turns while placing every target at Rank 1.</p></div>
          </div>
          <div className="recording-frame conversation-frame">
            <div className="conversation-proof reveal" aria-label="A sample belief-convergence moment">
              <div>
                <p className="eyebrow">One conversation</p>
                <h3>Watch uncertainty collapse into one Rank-1 decision.</h3>
              </div>
              <ol>
                <li>
                  <span>Turn 01 · Explore</span>
                  <blockquote>“I’m looking for a men’s athletic hoodie.”</blockquote>
                  <p>The agent asks for the material that best separates the remaining candidates.</p>
                </li>
                <li>
                  <span>Turn 02 · Decide</span>
                  <blockquote>“Moisture-wicking fabric.”</blockquote>
                  <p><strong>94.2% posterior · Rank 1</strong><small>31.4 ms · 0 tokens</small></p>
                </li>
              </ol>
            </div>
          </div>
          <div className="recording-frame takeaways-frame">
            <div className="frame-heading reveal"><p className="eyebrow light">Key takeaways</p><h3>Inference and decision theory outperform brute-force retrieval.</h3></div>
            <div className="takeaway-list reveal">
              {takeaways.map(([number, title, copy]) => <article key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p></article>)}
            </div>
          </div>
        </section>

        <section id="sandbox" className="final-cta final-cta-video scroll-chapter chapter-cta recording-frame reveal" data-scroll-chapter data-chapter="08 / Demo Sandbox" aria-labelledby="cta-title">
          <BackgroundVideo className="final-cta-background" src="/assets/shoptun-demo-video.mp4?v=frontend-2-cta" poster="/assets/shoptun-demo-video-poster.jpg?v=frontend-2-cta" />
          <div className="final-cta-video-overlay" aria-hidden="true" />
          <p className="eyebrow light">Live Interactive Sandbox</p>
          <h2 id="cta-title">Start a conversation.<br />Watch the posterior converge.</h2>
          <Link className="button button-light" to="/demo">Start the demo <span aria-hidden="true">↗</span></Link>
        </section>
      </main>
      <Footer />
    </>
  );
}

function Metric({ value, label, note }) {
  return <div className="metric-item"><strong>{value}</strong><span>{label}</span><small>{note}</small></div>;
}

function DataTable({ label, headers, rows, highlightLast = false, reveal = true }) {
  return (
    <div className={`data-table-wrap${reveal ? ' reveal' : ''}`} role="region" aria-label={label} tabIndex="0">
      <table className="data-table">
        <thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr className={highlightLast && index === rows.length - 1 ? 'is-highlighted' : ''} key={`${row[0]}-${row[1]}-${index}`}>{row.map((cell, cellIndex) => <td key={`${row[0]}-${index}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
