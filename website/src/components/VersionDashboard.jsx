import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { versionMetrics } from '../data/versionMetrics';

const colors = {
  score: '#0095F7',
  hit: '#E8F4FF',
  mrr: '#8D9AAF',
  mttc: '#48B87A',
  efficiency: '#67B9FF',
  ceiling: '#657388',
  phase1: '#67B9FF',
  phase2: '#8B7CF6',
  phase3: '#0095F7',
};

const axisStyle = { fontSize: 16, fill: '#A7B1C1' };
const legendStyle = { fontSize: 16, color: '#A7B1C1' };
const chartMargin = { top: 38, right: 28, left: 8, bottom: 8 };
const gridStroke = 'oklch(1 0 0 / .10)';
const tooltipStyle = {
  background: 'oklch(0.20 0.025 267)',
  border: '1px solid oklch(1 0 0 / .16)',
  borderRadius: 4,
  color: 'oklch(0.95 0.008 260)',
  fontSize: 16,
};

const labelTwoDecimals = (value) => Number(value).toFixed(2);

function ChartPanel({ title, caption, children, wide = false, tall = false }) {
  return (
    <section className={`vd-panel recording-frame${wide ? ' is-wide' : ''}`} aria-label={title}>
      <h4>{title}</h4>
      <p>{caption}</p>
      <div className={`vd-chart${tall ? ' is-tall' : ''}`}>{children}</div>
    </section>
  );
}

function Stat({ value, label, accent = false }) {
  return <div className="vd-stat"><strong className={accent ? 'is-accent' : ''}>{value}</strong><span>{label}</span></div>;
}

export default function VersionDashboard() {
  const data = versionMetrics;
  const latest = data.versions.at(-1);
  const baseline = data.versions[0];
  const improvement = (latest.score - baseline.score).toFixed(4);
  const versionRows = data.versions.map((version) => ({
    ...version,
    ceiling: data.meta.theoreticalCeiling,
  }));
  const scenarioRows = Object.keys(data.scenarioMilestones['v1.0']).map((scenario) => ({
    scenario,
    'v1.0': data.scenarioMilestones['v1.0'][scenario].mrr,
    'v1.5': data.scenarioMilestones['v1.5'][scenario].mrr,
    'v2.0': data.scenarioMilestones['v2.0'][scenario].mrr,
  }));

  return (
    <div className="version-dashboard">
      <header className="vd-header recording-frame">
        <div className="vd-title-row">
          <div>
            <p className="eyebrow">Evaluation dashboard · {data.meta.sampleCount} public sessions</p>
            <h3>TechJam Agent version evaluation</h3>
            <p className="vd-formula">TechnicalScore = 0.50 × Hit@10 + 0.30 × MRR + 0.20 × Efficiency</p>
          </div>
          <span className="vd-badge">v2.0 current</span>
        </div>
        <div className="vd-stats" aria-label="Latest benchmark metrics">
          <Stat value={latest.score.toFixed(4)} label="TechnicalScore" accent />
          <Stat value="100%" label="Hit@10" accent />
          <Stat value={latest.mrr.toFixed(3)} label="MRR" accent />
          <Stat value={latest.mttc.toFixed(2)} label="MTTC, turns" />
          <Stat value={`+${improvement}`} label="Absolute gain" accent />
        </div>
        <div className="vd-phase-callout">
          <strong>Three phases</strong>
          <p><span>01</span> Active dialogue takes Hit@10 from 12.5% to 100%. <span>02</span> Retrieval tuning improves MRR and stopping policy. <span>03</span> Bayesian inversion reaches perfect MRR with 1.99 MTTC.</p>
        </div>
      </header>

      <div className="vd-grid">
        <ChartPanel title="TechnicalScore evolution" caption="Composite score; dashed line marks the 0.983 theoretical ceiling.">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={versionRows} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisStyle} angle={-35} textAnchor="end" height={66} />
              <YAxis domain={[.05, 1]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Line type="monotone" dataKey="score" name="TechnicalScore" stroke={colors.score} strokeWidth={2.5} dot={{ r: 3, fill: colors.score }}>
                <LabelList dataKey="score" position="top" formatter={labelTwoDecimals} className="vd-data-label" />
              </Line>
              <Line type="monotone" dataKey="ceiling" name="Theoretical ceiling" stroke={colors.ceiling} strokeDasharray="6 5" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Increment by version" caption="TechnicalScore gain relative to the previous adopted version.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={versionRows.slice(1)} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisStyle} angle={-35} textAnchor="end" height={66} />
              <YAxis domain={[-.005, .57]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <ReferenceLine y={0} stroke={colors.ceiling} />
              <Bar dataKey="delta" name="Δ TechnicalScore" fill={colors.phase2} maxBarSize={34}>
                <LabelList dataKey="delta" position="top" formatter={labelTwoDecimals} className="vd-data-label" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Hit@10 and MRR" caption="Coverage saturates first; rank quality is the later optimization target.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={versionRows} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisStyle} angle={-35} textAnchor="end" height={66} />
              <YAxis domain={[0, 1.05]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Bar dataKey="hit" name="Hit@10" fill={colors.hit} />
              <Bar dataKey="mrr" name="MRR" fill={colors.mrr} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Mean turns to correct" caption="MTTC in turns, lower is better; a miss is counted as 11 turns.">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={versionRows} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisStyle} angle={-35} textAnchor="end" height={66} />
              <YAxis domain={[0, 11]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="mttc" name="MTTC" stroke={colors.mttc} strokeWidth={2.5} dot={{ r: 3, fill: colors.mttc }}>
                <LabelList dataKey="mttc" position="top" formatter={labelTwoDecimals} className="vd-data-label" />
              </Line>
            </LineChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Scenario MRR at milestones" caption="Rank quality across Buying, Browsing, Intent Override, and Boundary." wide>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={scenarioRows} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="scenario" tick={axisStyle} />
              <YAxis domain={[.6, 1.02]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Bar dataKey="v1.0" fill={colors.phase1} />
              <Bar dataKey="v1.5" fill={colors.phase2} />
              <Bar dataKey="v2.0" fill={colors.phase3} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="v2.0 ablation study" caption="TechnicalScore with key mechanisms removed or inputs shifted.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.ablations} layout="vertical" margin={{ top: 8, right: 12, left: 6, bottom: 0 }}>
              <CartesianGrid stroke={gridStroke} horizontal={false} />
              <XAxis type="number" domain={[.8, 1]} tick={axisStyle} />
              <YAxis type="category" dataKey="name" tick={axisStyle} width={132} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="score" name="TechnicalScore" fill={colors.score} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="Customer Probe validation" caption="TechnicalScore across 187 synthetic profile-combination sessions.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.customerProbe} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="version" tick={axisStyle} />
              <YAxis domain={[.88, 1]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="score" name="TechnicalScore" fill={colors.phase3} barSize={56} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>

        <ChartPanel title="All metrics by version" caption="Left axis: Hit@10, MRR, and Efficiency. Right axis: MTTC." wide tall>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={versionRows} margin={chartMargin}>
              <CartesianGrid stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={axisStyle} angle={-35} textAnchor="end" height={66} />
              <YAxis yAxisId="left" domain={[0, 1.05]} tick={axisStyle} width={52} />
              <YAxis yAxisId="right" orientation="right" domain={[0, 11]} tick={axisStyle} width={52} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={legendStyle} />
              <Bar yAxisId="left" dataKey="hit" name="Hit@10" fill={colors.hit} />
              <Bar yAxisId="left" dataKey="mrr" name="MRR" fill={colors.mrr} />
              <Bar yAxisId="left" dataKey="efficiency" name="Efficiency" fill={colors.efficiency} />
              <Bar yAxisId="right" dataKey="mttc" name="MTTC" fill={colors.mttc} />
            </BarChart>
          </ResponsiveContainer>
        </ChartPanel>
      </div>

      <section className="vd-table-section recording-frame" aria-labelledby="vd-table-title">
        <h4 id="vd-table-title">Complete adopted-version record</h4>
        <p>Public development set, all reported metrics and mechanisms.</p>
        <div className="vd-table-wrap" tabIndex="0" role="region" aria-label="Complete version metrics">
          <table>
            <thead><tr><th>Version</th><th>Score</th><th>Hit@10</th><th>MRR</th><th>MTTC</th><th>Phase</th><th>Core mechanism</th></tr></thead>
            <tbody>
              {data.versions.map((version) => (
                <tr className={version.id === 'v2.0' ? 'is-current' : ''} key={version.id}>
                  <td>{version.label}</td><td>{version.score.toFixed(4)}</td><td>{(version.hit * 100).toFixed(1)}%</td><td>{version.mrr.toFixed(3)}</td><td>{version.mttc.toFixed(2)}</td><td>{version.phase}</td><td>{version.paradigm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="vd-source">Deterministic local evaluator · updated {data.meta.updated}</p>
    </div>
  );
}
