# Analytica Workbench

A professional no-code/low-code data analysis workbench for preparation, exploration, statistical analysis, predictive modeling, evaluation, and reproducible reporting.

## Foundation

- Next.js App Router
- React + strict TypeScript
- ESLint with Next.js Core Web Vitals rules
- Responsive, accessibility-aware application shell
- System light/dark appearance and reduced-motion support
- Liquid-glass-inspired navigation/control layer with solid analytical content surfaces
- GitHub Actions verification on pushes and pull requests

## Local development

Requires Node.js 20.19 or newer.

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Verification

```bash
npm run verify
```

This runs linting, TypeScript validation, and a production build.

## Product structure

The product is organized around six major work modes:

`Data → Prepare → Explore → Analyze → Model → Results`

See [`docs/architecture.md`](docs/architecture.md) for the architectural baseline.

## Status

The repository currently contains the application foundation and initial workspace shell. Analytical engines, persistence, authentication, dataset execution, and production feature modules are intentionally not stubbed with fake behavior; they will be implemented against defined requirements.
