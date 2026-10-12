import { useEffect, useState } from 'react';
import { CheckCircle2, Database, Play, RefreshCw, AlertCircle } from 'lucide-react';

async function request(url, options = {}) {
  const response = await fetch(`/api/v1${url}`, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || 'The request failed.');
  return body;
}

function DataTable({ title, data }) {
  if (!data?.length) return null;
  const [columns, ...rows] = data;
  return (
    <section className="data-section" aria-label={title}>
      <div className="data-heading"><h3>{title}</h3><span>{rows.length} rows</span></div>
      <div className="table-scroll" tabIndex={0} aria-label={`${title} table`}>
        <table>
          <thead><tr>{columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => (
            <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell === null ? <span className="null-value">NULL</span> : String(cell)}</td>)}</tr>
          ))}</tbody>
        </table>
        {rows.length === 0 && <p className="empty-result">No rows returned.</p>}
      </div>
    </section>
  );
}

export default function App() {
  const [participant, setParticipant] = useState('');
  const [problems, setProblems] = useState([]);
  const [selected, setSelected] = useState('Problem 1');
  const [exercise, setExercise] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('source');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError('');
      setExercise(null);
      try {
        const identity = await request('/myId', { signal: controller.signal });
        const list = await request('/problems', { signal: controller.signal });
        const detail = await request(`/problems/${encodeURIComponent(selected)}`, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setParticipant(identity);
          setProblems(list);
          setExercise(detail);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(`Cannot load the exercise. ${failure.message}`);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [selected, retry]);

  async function submit(event) {
    event.preventDefault();
    if (busy || !exercise) return;
    setBusy(true);
    setResult(null);
    setError('');
    try {
      const feedback = await request('/submitQuery', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ problem: selected, query: drafts[selected] || '' }),
      });
      setResult(feedback);
      if (feedback.actual) setTab('actual');
    } catch (failure) {
      setError(`Submission failed. ${failure.message}`);
    } finally {
      setBusy(false);
    }
  }

  function changeProblem(event) {
    setSelected(event.target.value);
    setResult(null);
    setError('');
    setTab('source');
  }

  const query = drafts[selected] || '';
  const sources = result?.source
    ? [{ name: result.sourceTableName, data: result.source }]
    : exercise?.sourceTables || [];
  const expected = result?.destination || exercise?.expected;

  return (
    <main className="workspace">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="SQL-Project home">
          <span className="wordmark-mark"><Database size={17} aria-hidden="true" /></span>
          <span>SQL<span className="wordmark-light">/</span>Project</span>
        </a>
        <span className="status">{participant ? `Participant ${participant}` : 'Connecting...'}</span>
      </header>
      <section className="exercise-header" aria-label="Exercise selection">
        <div className="exercise-picker">
          <label htmlFor="problem">Exercise</label>
          <select id="problem" value={selected} onChange={changeProblem} disabled={busy || loading}>
            {(problems.length ? problems : [{ name: 'Problem 1' }]).map((problem) => <option key={problem.name}>{problem.name}</option>)}
          </select>
        </div>
        {exercise && <span className="test-count">{exercise.testCount} test datasets</span>}
      </section>
      {loading && <p role="status" className="loading-state">Loading exercise...</p>}
      {error && <div role="alert" className="feedback feedback-error">
        <AlertCircle size={18} aria-hidden="true" /><p>{error}</p>
        {!exercise && <button type="button" onClick={() => setRetry(retry + 1)} title="Retry loading"><RefreshCw size={16} aria-hidden="true" /> Retry</button>}
      </div>}
      {exercise && <>
        <section className="exercise-goal" aria-labelledby="goal-title">
          <h1 id="goal-title">{exercise.name}</h1>
          <p>{exercise.goal}</p>
        </section>
        <form className="query-form" onSubmit={submit}>
          <div className="editor-heading"><label htmlFor="query">SQL query</label><span>{query.length} / 5000</span></div>
          <textarea id="query" value={query} maxLength={5000} spellCheck={false} disabled={busy}
            placeholder={`SELECT * FROM ${exercise.sourceTables[0].name}`}
            onChange={(event) => { setDrafts({ ...drafts, [selected]: event.target.value }); setResult(null); }} />
          <div className="editor-actions">
            <span className="section-label">{exercise.sourceTables.map((source) => source.name).join(' + ')}</span>
            <button className="submit-button" type="submit" disabled={busy || !query.trim()}>
              <Play size={16} aria-hidden="true" />{busy ? 'Running...' : 'Run query'}
            </button>
          </div>
        </form>
        {result && <div role="status" className={`feedback feedback-${result.status}`}>
          {result.status === 'success' ? <CheckCircle2 size={20} aria-hidden="true" /> : <AlertCircle size={20} aria-hidden="true" />}
          <div><strong>{result.status === 'success' ? `Passed ${result.testsPassed} of ${exercise.testCount} tests` : result.status === 'mismatch' ? 'Output does not match' : 'Query error'}</strong>
            <p>{result.message || result.errorMessage}</p></div>
        </div>}
        <section className="results-section" aria-label="Exercise tables">
          <div className="result-tabs" role="tablist" aria-label="Table views">
            {[['source', 'Source data'], ['expected', 'Expected output'], ['actual', 'Your output']].map(([value, label]) => (
              <button key={value} id={`tab-${value}`} role="tab" type="button" aria-selected={tab === value}
                aria-controls="table-panel" onClick={() => setTab(value)}>{label}</button>
            ))}
          </div>
          <div id="table-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
            {result?.destinationTableName && <p className="test-context">Data {result.destinationTableName}</p>}
            {tab === 'source' && sources.map((source) => <DataTable key={source.name} title={source.name} data={source.data} />)}
            {tab === 'expected' && <DataTable title="Expected output" data={expected} />}
            {tab === 'actual' && (result?.actual ? <DataTable title="Your output" data={result.actual} /> : <p className="empty-result">No query results.</p>)}
          </div>
        </section>
      </>}
      <footer className="page-footer"><span>SQL-Project</span><span>SQLSearch exercises</span></footer>
    </main>
  );
}
