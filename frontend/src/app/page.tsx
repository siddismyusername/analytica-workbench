const workflow = ["Data", "Prepare", "Explore", "Analyze", "Model", "Results"];

export default function Home() {
  return (
    <main className="app-shell">
      <aside className="sidebar glass-surface" aria-label="Primary navigation">
        <div className="brand-mark">A</div>
        <nav>
          {workflow.map((item, index) => (
            <button className={index === 0 ? "nav-item active" : "nav-item"} key={item} type="button">
              {item}
            </button>
          ))}
        </nav>
      </aside>

      <section className="workspace">
        <header className="toolbar glass-surface">
          <div>
            <p className="eyebrow">Analytica Workbench</p>
            <h1>Untitled analysis</h1>
          </div>
          <div className="toolbar-actions">
            <button type="button">Search</button>
            <button className="primary-action" type="button">Import data</button>
          </div>
        </header>

        <section className="content-surface" aria-labelledby="welcome-title">
          <div className="welcome-copy">
            <p className="eyebrow">Professional analytics workspace</p>
            <h2 id="welcome-title">Start with a dataset.</h2>
            <p>
              Import tabular data, understand its quality, clean and transform it, run statistical analyses,
              build models, and keep every operation reproducible.
            </p>
            <button className="primary-action" type="button">Choose a dataset</button>
          </div>

          <div className="capability-grid" aria-label="Core capabilities">
            {[
              ["Profile", "Types, missingness, uniqueness, distributions, and quality warnings."],
              ["Prepare", "Clean, transform, reshape, aggregate, and combine datasets."],
              ["Analyze", "Guided hypothesis testing, diagnostics, and statistical reporting."],
              ["Model", "Predictive modeling with evaluation, comparison, and explainability."],
            ].map(([title, description]) => (
              <article className="capability-card" key={title}>
                <h3>{title}</h3>
                <p>{description}</p>
              </article>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}
