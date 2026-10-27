import { useEffect, useState } from 'react';
import { ArrowLeft, Printer } from 'lucide-react';

export default function Handout() {
  const [problems, setProblems] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch('/api/v1/problems', { signal: controller.signal });
        if (!response.ok) throw new Error('Could not load the exercise list.');
        const summary = await response.json();
        const details = await Promise.all(summary.map(async (problem) => {
          const detailResponse = await fetch(`/api/v1/problems/${encodeURIComponent(problem.name)}`, { signal: controller.signal });
          if (!detailResponse.ok) throw new Error(`Could not load ${problem.name}.`);
          return detailResponse.json();
        }));
        if (!controller.signal.aborted) setProblems(details);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure.message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, []);

  return (
    <main className="handout">
      <header className="handout-toolbar screen-only">
        <a href="/" className="ghost-button"><ArrowLeft size={16} aria-hidden="true" /> Back to exercises</a>
        <button type="button" className="submit-button" onClick={() => window.print()} disabled={!problems.length}>
          <Printer size={16} aria-hidden="true" /> Print / Save as PDF
        </button>
      </header>
      <header className="handout-title">
        <p className="eyebrow">SQLSearch · Exercise handout</p>
        <h1>SQL query exercises</h1>
        <p>Work through the exercises in order. Write a query for each prompt using the displayed source data.</p>
      </header>
      {loading && <p role="status" className="loading-state screen-only">Preparing handout...</p>}
      {error && <p role="alert" className="feedback feedback-error">{error}</p>}
      {problems.map((problem) => (
        <article className="handout-problem" key={problem.name}>
          <div className="handout-problem-heading">
            <span className="section-label">SQLSEARCH EXERCISE</span>
            <span className="handout-tests">{problem.testCount} datasets</span>
          </div>
          <h2>{problem.name}</h2>
          <p className="handout-goal">{problem.goal}</p>
          {problem.sourceTables.map((source) => {
            const [columns, ...rows] = source.data;
            return (
              <section className="handout-source" key={source.name}>
                <div className="data-heading"><h3>{source.name}</h3><span>{rows.length} rows</span></div>
                <div className="handout-table">
                  <table>
                    <thead><tr>{columns.map((column, index) => <th key={index}>{column}</th>)}</tr></thead>
                    <tbody>{rows.map((row, index) => (
                      <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell === null ? 'NULL' : String(cell)}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </article>
      ))}
    </main>
  );
}
