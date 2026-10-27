import { useEffect, useState } from 'react';
import { CheckCircle2, Database, Play, RefreshCw, AlertCircle, Printer } from 'lucide-react';

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
  const [progress, setProgress] = useState(null);
  const [selected, setSelected] = useState('Problem 1');
  const [exercise, setExercise] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('source');
  const [retry, setRetry] = useState(0);
  const [repair, setRepair] = useState(null);
  const [repairBusy, setRepairBusy] = useState(false);
  const [voting, setVoting] = useState(null);
  const [voteBusy, setVoteBusy] = useState(false);
  const [voteFeedback, setVoteFeedback] = useState('');
  const [voteForm, setVoteForm] = useState({
    otherScore: 4,
    repairedScore: 4,
    myCorrectScore: 4,
    myRepairedScore: 4,
    explanation: '',
  });

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError('');
      setExercise(null);
      setProgress(null);
      try {
        const identity = await request('/myId', { signal: controller.signal });
        const [list, detail, voteProgress] = await Promise.all([
          request('/problems', { signal: controller.signal }),
          request(`/problems/${encodeURIComponent(selected)}`, { signal: controller.signal }),
          request(`/voting/progress/${encodeURIComponent(selected)}`, { signal: controller.signal }),
        ]);
        if (!controller.signal.aborted) {
          setParticipant(identity);
          setProblems(list);
          setExercise(detail);
          setProgress(voteProgress);
          try {
            const saved = localStorage.getItem(`sql-project:drafts:${identity}`);
            setDrafts(saved ? JSON.parse(saved) : {});
          } catch {
            setDrafts({});
          }
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

  useEffect(() => {
    if (!progress?.remainingSeconds) return undefined;
    const timer = setInterval(() => {
      setProgress((current) => {
        if (!current || current.remainingSeconds <= 1) {
          return current ? { ...current, status: 'ready', canRequestToVote: true, remainingSeconds: 0 } : current;
        }
        return { ...current, remainingSeconds: current.remainingSeconds - 1 };
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [Boolean(progress?.remainingSeconds)]);

  async function submit(event) {
    event.preventDefault();
    if (busy || !exercise) return;
    setBusy(true);
    setResult(null);
    setRepair(null);
    setVoting(null);
    setVoteFeedback('');
    setError('');
    try {
      const feedback = await request('/submitQuery', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ problem: selected, query: drafts[selected] || '' }),
      });
      setResult(feedback);
      if (feedback.actual) setTab('actual');
      request(`/voting/progress/${encodeURIComponent(selected)}`)
        .then(setProgress)
        .catch(() => {});
    } catch (failure) {
      setError(`Submission failed. ${failure.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function requestRepair() {
    if (!exercise || !query.trim() || repairBusy) return;
    setRepairBusy(true);
    setError('');
    try {
      const suggestion = await request('/repair/suggest', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ problem: selected, query }),
      });
      setRepair(suggestion);
    } catch (failure) {
      setError(`Repair request failed. ${failure.message}`);
    } finally {
      setRepairBusy(false);
    }
  }

  async function requestVoting() {
    if (!exercise || voteBusy) return;
    setVoteBusy(true);
    setVoteFeedback('');
    setError('');
    try {
      const payload = await request(`/voting/options/${encodeURIComponent(selected)}?query=${encodeURIComponent(query)}`);
      setVoting(payload);
      if (payload.status === 'success') {
        setVoteForm({
          otherScore: 4,
          repairedScore: 4,
          myCorrectScore: 4,
          myRepairedScore: 4,
          explanation: '',
        });
      }
    } catch (failure) {
      setError(`Could not load voting options. ${failure.message}`);
    } finally {
      setVoteBusy(false);
    }
  }

  async function submitVote(event) {
    event.preventDefault();
    if (!voting?.cards?.length || voteBusy) return;
    setVoteBusy(true);
    setError('');
    setVoteFeedback('');
    try {
      const payload = {
        sessionId: voting.sessionId,
        ratings: Object.fromEntries(voting.cards.map((card) => [
          card.id,
          Number(voteForm[`${card.id}Score`]),
        ])),
        explanation: voteForm.explanation,
      };
      const response = await request('/voting/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setVoteFeedback(response.message || 'Vote submitted');
    } catch (failure) {
      setError(`Vote submission failed. ${failure.message}`);
    } finally {
      setVoteBusy(false);
    }
  }

  function scoreValue(cardId) {
    return voteForm[`${cardId}Score`];
  }

  function updateDraft(value) {
    const updated = { ...drafts, [selected]: value };
    setDrafts(updated);
    if (participant) {
      try {
        localStorage.setItem(`sql-project:drafts:${participant}`, JSON.stringify(updated));
      } catch {
        return;
      }
    }
  }

  function changeProblem(event) {
    setSelected(event.target.value);
    setResult(null);
    setRepair(null);
    setVoting(null);
    setVoteFeedback('');
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
        <div className="topbar-actions">
          <a className="ghost-button handout-link" href="/handout" target="_blank" rel="noreferrer" title="Open printable exercise handout">
            <Printer size={15} aria-hidden="true" /> Handout
          </a>
          <span className="status">{participant ? `Participant ${participant}` : 'Connecting...'}</span>
        </div>
      </header>
      <section className="exercise-header" aria-label="Exercise selection">
        <div className="exercise-picker">
          <label htmlFor="problem">Exercise</label>
          <select id="problem" value={selected} onChange={changeProblem} disabled={busy || loading}>
            {(problems.length ? problems : [{ name: 'Problem 1' }]).map((problem) => <option key={problem.name}>{problem.name}</option>)}
          </select>
        </div>
        {exercise && <span className="test-count">{exercise.testCount} test datasets</span>}
        {progress && <span className="study-progress">
          {progress.solved && <span className="solved-mark"><CheckCircle2 size={14} aria-hidden="true" /> Solved</span>}
          <span>{progress.attempts} / {progress.needed} attempts</span>
          {progress.remainingSeconds > 0 && <span className="wait-time">{Math.floor(progress.remainingSeconds / 60)}:{String(progress.remainingSeconds % 60).padStart(2, '0')} to voting</span>}
          {progress.canRequestToVote && <span className="ready-mark">Voting ready</span>}
        </span>}
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
            onChange={(event) => { updateDraft(event.target.value); setResult(null); }} />
          <div className="editor-actions">
            <span className="section-label">{exercise.sourceTables.map((source) => source.name).join(' + ')}</span>
            <div className="action-buttons">
              <button className="ghost-button" type="button" onClick={requestRepair}
                disabled={busy || repairBusy || !query.trim() || exercise?.repairable === false}>
                {repairBusy ? 'Finding repair...' : 'Suggest repair'}
              </button>
              <button className="submit-button" type="submit" disabled={busy || !query.trim()}>
                <Play size={16} aria-hidden="true" />{busy ? 'Running...' : 'Run query'}
              </button>
            </div>
          </div>
        </form>
        {repair && <section className="repair-panel" aria-label="Repair suggestion">
          <div className="repair-header"><strong>Suggested repair</strong><span>Confidence {Math.round((repair.confidence || 0) * 100)}%</span></div>
          <code>{repair.query}</code>
          <div className="repair-actions">
            <button type="button" className="ghost-button" onClick={() => updateDraft(repair.query)}>Use suggestion</button>
          </div>
        </section>}
        {result && <div role="status" className={`feedback feedback-${result.status}`}>
          {result.status === 'success' ? <CheckCircle2 size={20} aria-hidden="true" /> : <AlertCircle size={20} aria-hidden="true" />}
          <div><strong>{result.status === 'success' ? `Passed ${result.testsPassed} of ${exercise.testCount} tests` : result.status === 'mismatch' ? 'Output does not match' : 'Query error'}</strong>
            <p>{result.message || result.errorMessage}</p></div>
        </div>}
        <section className="voting-panel" aria-label="Alternative query voting">
          <div className="voting-header">
            <h2>Compare alternative queries</h2>
            <button type="button" className="ghost-button" onClick={requestVoting} disabled={voteBusy || loading || !exercise}>
              {voteBusy ? 'Loading...' : 'Load alternatives'}
            </button>
          </div>
          {voting?.status === 'pending' && <p className="loading-state">{voting.message}</p>}
          {voting?.status === 'success' && <form onSubmit={submitVote} className="vote-form">
            {voting.cards.map((card) => (
              <label key={card.id} className="vote-card">
                <span><strong>{card.label}</strong><code>{card.query}</code></span>
                <span className="vote-score">Ease rating {scoreValue(card.id)}
                  <input
                    type="range"
                    min="1"
                    max="7"
                    value={scoreValue(card.id)}
                    onChange={(event) => {
                      const key = `${card.id}Score`;
                      setVoteForm({ ...voteForm, [key]: Number(event.target.value) });
                    }}
                  />
                </span>
              </label>
            ))}
            <label className="vote-comment">Optional comment
              <textarea
                value={voteForm.explanation}
                maxLength={1000}
                onChange={(event) => setVoteForm({ ...voteForm, explanation: event.target.value })}
                placeholder="Why did one query feel easier to understand?"
              />
            </label>
            <div className="vote-actions">
              <button className="submit-button" disabled={voteBusy} type="submit">{voteBusy ? 'Submitting...' : 'Submit ratings'}</button>
              {voteFeedback && <p className="vote-feedback">{voteFeedback}</p>}
            </div>
          </form>}
        </section>
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
