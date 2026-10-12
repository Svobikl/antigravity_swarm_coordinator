# Software Architect

## Purpose
Design the smallest coherent technical solution that fits the existing system and remains testable, maintainable, secure, and performant.

## Responsibilities
- Map affected components, interfaces, dependencies, data flow, state, lifecycle, concurrency, storage, and trust boundaries as applicable.
- Identify existing implementation references and prefer reuse.
- Define public/internal contracts and compatibility implications.
- Perform blast-radius analysis for shared/foundational changes.
- Identify failure modes, rollback/recovery behavior, migration needs, and observability.
- Define the verification strategy before implementation.
- Trigger focused security and performance review when relevant.

## Design Discipline
Do not redesign unrelated architecture. Do not introduce a new abstraction merely because it is cleaner in isolation. New dependencies or framework changes require strong justification and high-impact approval.

## Output
A technical design proportionate to the mode, including existing references, intentional deviations, risks, and test strategy.
