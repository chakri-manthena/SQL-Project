export default function App() {
  return (
    <main className="workspace">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="SQL-Project home">
          <span className="wordmark-mark">S</span>
          <span>SQL<span className="wordmark-light">/</span>Project</span>
        </a>
        <span className="status"><i /> API workspace</span>
      </header>
      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">SQLSearch · SQLRepair</p>
        <h1 id="page-title">Practice, compare, repair.</h1>
        <p className="description">A workspace for student-authored SQL query exercises.</p>
      </section>
      <section className="workspace-panel" aria-label="Exercise workspace">
        <div className="panel-heading">
          <div>
            <span className="section-label">WORKSPACE</span>
            <h2>Ready for the first exercise</h2>
          </div>
          <span className="step-count">00 <span>/ 10</span></span>
        </div>
        <div className="panel-body">
          <span className="prompt-index">01</span>
          <p>The exercise interface will be added in the next implementation step.</p>
          <span className="panel-rule" />
        </div>
        <footer className="panel-footer">
          <span>REACT CLIENT</span>
          <span>NODE API</span>
          <span>LOCAL DEVELOPMENT</span>
        </footer>
      </section>
      <footer className="page-footer">
        <span>SQL-Project</span>
        <span>INITIAL WORKSPACE</span>
      </footer>
    </main>
  );
}
