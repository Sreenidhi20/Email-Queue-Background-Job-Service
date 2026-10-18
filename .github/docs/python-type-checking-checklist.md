# Python and Pylance Checklist

Use this checklist when adding or changing Python code in Mailroom. Run Pylance
diagnostics for the workspace, including `tests/`, and resolve diagnostics at
their source instead of hiding them with broad ignores or `Any` casts.

## Before finishing a change

- [ ] Run workspace diagnostics in VS Code/Pylance and inspect every affected
  source **and test** file.
- [ ] Check the diagnostic code and inferred type; do not rely on the message
  alone or assume a runtime success means the type is correct.
- [ ] Trace the diagnostic to the declaration or library boundary producing
  the type. Check callers before changing a public signature.
- [ ] Prefer explicit types, generic specialization, runtime narrowing, and
  structural protocols over casts, broad ignores, or disabling diagnostics.
- [ ] If a diagnostic comes from a third-party library's incomplete typings,
  verify the installed version/signature, isolate the boundary, and suppress
  only the exact diagnostic on the smallest expression with an explanation.
- [ ] Run the focused tests, then the full test suite when practical.
- [ ] Re-run diagnostics after edits and confirm new diagnostics are resolved.
- [ ] Separate error-level diagnostics from informational unused-parameter
  hints required by framework callback signatures.

## Patterns for recurring diagnostics

### Generic response factories

`ApiResponse.ok(...)` can infer `Unknown` when its generic payload type is not
clear at the call site. Keep the response payload typed across the router
boundary: provide a typed payload and, when inference still fails, construct
the parameterized response explicitly, such as
`ApiResponse[HealthResponseDto].ok(payload)`.

For factories returning an empty response, account for generic invariance.
Construct and return `ApiResponse[None]` explicitly rather than returning an
unparameterized `cls(...)` whose type is `ApiResponse[T]`.

```python
@classmethod
def fail(cls, status_code: int, detail: str, error: str) -> "ApiResponse[None]":
    return ApiResponse[None](
        status_code=status_code,
        is_success=False,
        data=None,
        detail=detail,
        error=error,
    )
```

At a typed endpoint, specialize the response factory too:

```python
return ApiResponse[HealthResponseDto].ok(service.check())
```

### Context-manager generator annotations

With `@contextmanager`, annotate the generator function as
`Generator[YieldType, SendType, ReturnType]`, not `Iterator[YieldType]`.
With `@asynccontextmanager`, use `AsyncGenerator[YieldType, SendType]`,
not `AsyncIterator[YieldType]`. Import these from `collections.abc`.
This return annotation change is for the generator function decorated by the
context-manager decorator. An ordinary FastAPI dependency generator such as
`get_session`, without `@contextmanager`, can continue to return
`Iterator[Session]`.

```python
@contextmanager
def session_scope(self) -> Generator[Session, None, None]:
    session = self._session_factory()
    try:
        yield session
    finally:
        session.close()
```

For an async FastAPI lifespan decorated with `@asynccontextmanager`, use
`AsyncGenerator[None, None]`.

### Settings populated from environment

Pydantic Settings reads values from `.env` and the environment at runtime, but
Pylance may still treat a required settings field as a missing constructor
argument at `Settings()`. If using a validated empty default to satisfy static
analysis, use a field constraint such as `Field(default="", min_length=1,
validate_default=True)`. This preserves startup failure when no value is loaded;
never use a non-empty fake URL. Verify Pylance diagnostics, `.env` loading, and
missing-value validation.

`validate_default=True` is essential: without it, an unset value may use the
empty default without validation. Check both the regular settings load from
`.env` and construction with `_env_file=None` and no `DATABASE_URL`; the latter
must raise a Pydantic `ValidationError`.

### FastAPI exception handlers

FastAPI's exception-handler callback type accepts an `Exception` parameter.
Annotate registered callbacks with that accepted type, then narrow to a
specific application error inside the handler if needed. Keep the handler's
request type and sync/async form compatible with FastAPI's handler signature.
Do not suppress callback incompatibility by widening unrelated types.

For a handler registered to one exception class, narrow immediately:

```python
async def _on_app_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return make_response(exc.detail, exc.error_text)
```

The runtime guard makes subclass-only properties safe for static analysis.
Re-raising an unexpected exception prevents the handler from formatting an
unrelated error as though it were the registered application error. Prefix an
intentionally unused framework callback parameter with `_`; any remaining
unused-parameter message is informational, not a type error.

### Celery and Redis library typing

Pylance may report partially unknown types for Celery decorators/configuration
or Redis client factory/command methods when third-party typing is incomplete.
Keep task payloads, task results, and application-owned configuration typed.
Prefer small typed adapters/protocols at these library boundaries; avoid
spreading `Any` or `cast(Any, ...)` through application code. Confirm a
targeted runtime check or test for behavior that stubs cannot describe, and
record any unavoidable narrow suppression beside the affected call. The
installed `redis-py` version marks its package as typed, but its `from_url`
kwargs and sync `ping` return are still partially unknown to Pylance. Suppress
only `reportUnknownMemberType` on those two calls in
[`src/infrastructure/redis.py`](../src/infrastructure/redis.py), with comments
explaining that `from_url` creates a synchronous `Redis` client and `ping`
returns its boolean response. The path from this checklist is
[`mailroom/src/infrastructure/redis.py`](../../mailroom/src/infrastructure/redis.py).

In this Redis client, the installed `redis-py` version (6.4.0) has a `py.typed`
marker, but the inspected signatures still leave `Redis.from_url` keyword
arguments and `Redis.ping()` partially unknown. Keep the client synchronous,
set connection/socket timeouts, and limit the suppression to the affected
expressions. Do not add a broad file-level ignore or type the client as `Any`.

The selected environment has no usable Celery stubs. Keep Celery imports,
configuration, and decorators at their infrastructure/task boundaries. The
project uses narrow ignores for the missing import stubs, unknown configuration
update, and untyped task decorator; task function inputs and outputs stay
annotated. Test the decorated task by calling it directly when checking its
body, and use a broker/worker integration smoke test to check queue behavior.

## Test-specific rules

- A runtime assertion such as `assertIsNotNone(value)` may not narrow an
  optional value for Pylance. Follow it with an explicit `if value is None:
  self.fail(...)` guard before accessing attributes.
- Test fakes should implement the same structural contract as the production
  dependency. Type injected dependencies as small `Protocol`s when services
  are intended to accept fakes; do not type-ignore incompatible test doubles.
- Celery's task decorator may obscure a task's runtime wrapper attributes
  (such as `.run`) to Pylance. Test task behavior through a typed task-facing
  seam or add a narrow, justified adapter; do not assume an untyped decorator
  provides useful static types.
- Keep tests runnable without live PostgreSQL, Redis, or SMTP. Use an isolated
  database and fakes/mocks for dependency behavior, plus a separate integration
  smoke test when verifying the real broker.

For a possibly missing SQLAlchemy scalar result, use a narrowing guard:

```python
saved = session.scalar(statement)
if saved is None:
    self.fail("Expected row was not persisted")
self.assertTrue(saved.database_healthy)
```

For injected health dependencies, define small `Protocol`s around the methods
the service actually calls (`add(...)` and `ping()`). This permits structurally
compatible fakes without inheriting concrete infrastructure classes or using
`cast`.

If an untyped Celery decorator hides wrapper attributes such as `.run`, avoid
depending on that undocumented type surface in a unit test. Call the decorated
task directly if it is callable; test actual enqueueing and worker execution
separately against Redis.

## Resolved diagnostic history

The initial audit recorded these recurring issues and resolutions:

- `reportUnknownMemberType` at `ApiResponse.ok(...)`: specialize the response
  factory with the payload DTO at the endpoint.
- `reportReturnType` in `ApiResponse.fail`: construct `ApiResponse[None]`
  explicitly because generic parameters are invariant.
- `reportDeprecated` for `@contextmanager`/`@asynccontextmanager`: annotate
  their generator functions with `Generator`/`AsyncGenerator`, respectively.
- `reportCallIssue` at `Settings()`: use a validated empty default for the
  environment-provided required setting, then verify missing configuration
  still fails at runtime.
- `reportArgumentType` at FastAPI exception-handler registration: accept the
  framework's `Exception` argument and narrow it with `isinstance`.
- Redis `reportUnknownMemberType`: narrowly suppress the incomplete signatures
  for `from_url` and synchronous `ping`, documenting the installed API.
- Celery `reportMissingTypeStubs`, `reportUnknownMemberType`, and
  `reportUntypedFunctionDecorator`: keep narrow suppressions at its import,
  configuration, and decorator boundaries.
- In `mailroom/tests/test_health.py`, explicitly guard a possibly-`None`
  scalar result and use protocols for fake health dependencies.
- In `mailroom/tests/test_tasks.py`, invoke the decorated task directly rather
  than relying on its untyped `.run` attribute.

Re-run workspace diagnostics after changes; this history is not a substitute
for checking the current diagnostics.
