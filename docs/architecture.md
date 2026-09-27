# Application Architecture

## Product model

Analytica Workbench is a desktop-first professional analytics workspace organized around a reproducible project containing datasets, transformations, analyses, models, and results.

## Primary workspace

The UI architecture follows a stable three-region model:

1. **Navigation layer** — project-level destinations and workspace modes.
2. **Content layer** — data grids, charts, statistical output, model evaluation, and reports. This remains predominantly solid and high-legibility.
3. **Contextual layer** — inspectors, configuration, commands, and transient controls. Glass effects are reserved primarily for this UI layer rather than analytical content.

## Product domains

- `data`: import, profiling, schema, and dataset state
- `prepare`: cleaning, transformation, reshaping, joins, and operation history
- `explore`: descriptive statistics, distributions, relationships, and visualization
- `analyze`: hypothesis tests, classical statistics, diagnostics, and effect estimates
- `model`: supervised/unsupervised modeling, validation, metrics, and explainability
- `results`: persistent outputs, comparison, reporting, and export

## Engineering direction

The application uses the Next.js App Router and strict TypeScript. Feature code should be organized by domain rather than by generic component type as the product grows. Shared UI primitives belong under `src/components`; feature-specific state and UI should remain within the relevant feature domain.

All analytical operations must eventually be represented as explicit, reproducible pipeline steps rather than destructive invisible mutations.
