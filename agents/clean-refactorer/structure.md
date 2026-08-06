# Target structures — clean architecture per stack

Concrete folder trees the `clean-refactorer` agent moves a messy codebase toward. The rule across
all of them is the **Dependency Rule**: source dependencies point inward only; the **domain depends
on nothing**, frameworks/DB/HTTP live at the edge behind ports, controllers/UI are thin.

```
domain/         entities · value objects · domain services · PORTS (interfaces the app needs)   ← pure
application/    use cases / interactors orchestrating the domain via ports                       ← depends on domain
infrastructure/ adapters that IMPLEMENT ports: DB/ORM, HTTP clients, message bus, framework glue ← depends on domain+application
interfaces/     controllers · presenters · CLI · UI — translate the outside world ↔ use cases    ← depends on application+domain
```

## Spring Boot (Java 17/21)

```
src/main/java/com/example/
├─ domain/
│  ├─ model/            # Order, Money (value objects) — no JPA/Spring annotations
│  └─ port/             # OrderRepository, PaymentGateway (interfaces, defined by the domain need)
├─ application/
│  └─ usecase/          # PlaceOrder, CancelOrder — orchestrate domain, depend only on ports
├─ infrastructure/
│  ├─ persistence/      # JpaOrderRepository implements domain.port.OrderRepository (+ @Entity adapters)
│  ├─ http/             # StripePaymentGateway implements domain.port.PaymentGateway
│  └─ config/           # Spring @Configuration wiring ports → adapters
└─ interfaces/
   └─ web/              # OrderController (@RestController) — thin: maps request → use case → response
```
Keep `@Entity`/JPA out of `domain/` — use a persistence model in `infrastructure/persistence/` and
map to/from the pure domain entity. Lock with the ArchUnit test from `fitness_init.py`.

## React 18/19 + Vite + TS

```
src/
├─ domain/            # types, value objects, pure business rules (no React, no axios)
├─ application/       # use cases / orchestration; defines ports (interfaces) it needs
├─ infrastructure/    # adapters: api clients (axios/fetch), storage, ports implemented here
└─ interfaces/        # components/, hooks/, pages/ — thin; call use cases, render; no fetch logic inside
```
The win is pulling data-fetching and business logic OUT of components into `application/` use cases
behind ports `infrastructure/` implements. Components stay presentational. Lock with the
`.dependency-cruiser.js` from `fitness_init.py` (`depcruise --validate src` in CI).

## FastAPI (Python)

```
app/
├─ domain/            # entities, value objects, ports (Protocol/ABC) — no FastAPI/SQLAlchemy
├─ application/       # use cases; depend on domain ports only
├─ infrastructure/    # SQLAlchemy repositories, httpx clients implementing the ports; DI wiring
└─ interfaces/
   └─ api/            # APIRouter endpoints — thin: parse/validate → call use case → serialize
```
Routers depend on use cases, not on the DB session directly; inject port implementations via FastAPI
`Depends`. Lock with the `.importlinter` layered contract from `fitness_init.py` (`lint-imports` in CI).

## How the agent gets here (recap)

1. **Net first** — `characterize.py` pins current I/O; commit it green, standalone.
2. **Move in slices** — Branch-by-Abstraction inside the code, Strangler Fig at boundaries; one
   atomic `git revert`-able commit each; re-run the net after every slice; revert on red.
3. **Lock** — `fitness_init.py` emits the CI fitness function so the new boundaries can't rot.
4. **Prove** — net green AND metrics improved (CC ≤ 10, 0 new duplication, no new cycles), reported
   as before/after deltas, with the structure write-up.
