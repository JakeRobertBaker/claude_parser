# Standard Scrutiny Questions

Use these questions after each stage and answer them in `plan/plan_{i}.md`.

1. Did any dependency direction violate `cli -> adapters -> application -> ports -> domain`?
2. Did we reduce hidden mutable state, especially in adapters?
3. Did responsibilities become clearer (who decides vs who persists/transports)?
4. Did the public port interfaces become simpler and more explicit?
5. Did we preserve behavior and stability (unit tests, lint, type checks)?
6. Did we introduce temporary complexity; if yes, is there a planned removal step?
7. Are error messages and failure paths still actionable for operators?
8. Is the code easier to test in isolation after this stage?
9. Did we keep the implementation minimal (avoid unnecessary classes/abstractions)?
10. What are the top risks remaining before the next stage?
