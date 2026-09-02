# Minimal Maintained Repository Surface

## Decision

Every implementation milestone must leave `isaac-audio-sensors` simpler, clearer, or no more complex than required by its maintained product behavior. Completion includes implementing the new capability, migrating every in-scope consumer, and removing the superseded surface in the same milestone. Cleanup is not deferred to a later optional pass.

The repository retains only code, files, public symbols, algorithms, configuration, schemas, registries, adapters, dependencies, examples, tests, fixtures, documentation, and packaged resources that have at least one of these justifications:

- a current maintained product responsibility and consumer;
- a distinct, documented, and evidence-supported operating role;
- a required public, packaging, safety, transfer, or reproducibility contract;
- deliberately protected historical evidence kept outside active runtime paths.

Tests alone do not justify production functionality. Production APIs, branches, switches, mocks, shortcuts, or alternate implementations must not exist only to make tests easier. Tests use production contracts with test-owned fixtures, fakes, and adapters.

## Milestone Completion Rule

For every affected subsystem:

1. Inspect maintained internal and in-scope external consumers, package contents, and protected evidence.
2. Implement the smallest correct production design and migrate those consumers directly.
3. Remove obsolete or duplicate modules, fields, algorithms, configuration, schemas, factories, registry entries, adapters, dependencies, examples, tests, fixtures, documentation, and generated tracked artifacts.
4. Validate the remaining production path through its real interfaces and verify that built distributions do not retain removed surfaces.

Do not preserve parallel old and new paths, compatibility aliases, speculative abstractions, unused extension points, or multiple implementations with the same semantic role unless an explicit supported contract requires them. An implementation with a materially different performance, dependency, fidelity, or deployment role may remain only when that role and consumer are documented and validated.

## Quality Standard

Prefer cohesive ownership, direct data flow, few public concepts, narrow dependencies, and one canonical implementation per semantic role. Optimize runtime or scale where the application requires it, but do not trade correctness or understandable contracts for unmeasured micro-optimization. Code organization, naming, lifecycle, and failure behavior must remain easy to understand and maintain.

Plan-specific cleanup happens as soon as a milestone makes something obsolete. [[implementation_phases/10-end-to-end-validation-and-product-closeout|Plan 10]] performs the final repository-wide audit, but it is a safety net rather than permission to accumulate dead or duplicate work during earlier plans.

## Boundaries

Removal is consumer-first rather than indiscriminate. Preserve `knowledge/raw/`, frozen evidence, required historical artifacts, and out-of-scope downstream repositories. Do not treat a filename or lack of direct imports as sufficient proof of deadness; verify runtime registration, packaging, configuration, and external integration boundaries before deletion.

## Consequences

Each completed plan has an explicit product result and a correspondingly minimal maintained surface. Adding a dependency, abstraction, backend, algorithm, schema field, or configuration option creates an ongoing maintenance obligation and therefore requires concrete value. Obsolete tests change with obsolete behavior instead of forcing the production repository to preserve historical design.
