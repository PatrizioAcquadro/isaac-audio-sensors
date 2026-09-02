# Minimal Maintained Repository Surface

## Objective

End every implementation plan with a focused cleanup: inspect the affected code, files, and consumers, then remove or simplify anything that is no longer necessary. The goal is an efficient, elegant, organized, high-quality repository that remains easy to understand and maintain.

## Completion Rule

- Keep only functionality with a current product responsibility, maintained consumer, or required contract.
- Remove unused, obsolete, duplicate, compatibility-only, speculative, and test-only production surfaces, including their configuration, dependencies, tests, and documentation.
- Prefer one clear implementation per role; retain alternatives only when they serve distinct necessary purposes.
- Validate the remaining production path after cleanup.

Cleanup is consumer-first: preserve required contracts, protected evidence, `knowledge/raw/`, and out-of-scope downstream work. [[implementation_phases/10-end-to-end-validation-and-product-closeout|Plan 10]] performs the final repository-wide check, but each earlier plan removes what it makes obsolete.
