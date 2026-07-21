# Task 1 Bug-Condition Exploration Evidence

- SSH alias: `wsl2-cf-kiro`
- Detached worktree: `/home/dawid/usacar-task1-exploration-ebf176d`
- Backend root: `/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder`
- Pinned HEAD: `ebf176d7f0d76636b3ae9fd163ff5ad283b8e365`
- Test: `/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/tests/test_contract_bug_condition.py`
- Isolated runtime: /home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/.venv-task1
- Test-only dependencies: `/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/.test-deps`

## Command

```sh
ssh wsl2-cf-kiro "env PYTHONPATH=/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/.test-deps:/home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder /home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/.venv-task1/bin/python -m pytest -q --tb=short /home/dawid/usacar-task1-exploration-ebf176d/usa-car-finder/tests/test_contract_bug_condition.py"
```

## Sanitized expected-failure counterexamples

1. OpenAPI: `app.openapi()` raised `AssertionError: A response class is needed to generate OpenAPI`.
2. Viewer: generated synthetic token `server-only-sentinel` occurred in browser-visible HTML. Additional synthetic examples containing quotes/markup, Unicode, slashes, and a long value were also disclosed. The test output contains synthetic values only.
3. Capabilities: an authorized in-process `GET /api/capabilities` returned `404 Not Found`; Hypothesis explicit configuration counterexample was `manheim_enabled=None`.

## Result

`3 failed, 1 warning in 2.47s` (pytest exit code 1). This failure is expected on unfixed code and is task success: Property 1 PBT status is recorded as passed evidence. No application fix was implemented, no lifespan worker or Uvicorn process was started, and no production database or service was accessed or changed.
