I went through [hawarma repository](https://github.com/hpma-bits/hawarma?utm_source=chatgpt.com) and honestly, this is already above the average “automation bot” project in terms of architectural intent. You can clearly see deliberate thinking around simulation, strategy isolation, runtime state, and bridge abstraction. ([GitHub](https://github.com/hpma-bits/hawarma))

What stands out most is that you’re *already moving away from script-style automation into a domain-model-driven system*. That’s the right direction.

A few detailed observations.

------

# What the project is doing well

## 1. Strong separation between “game interaction” and “decision making”

This is the best design decision in the repo.

You separated:

- scanner / operator / environment
- strategy
- simulator
- runtime orchestration

instead of letting everything mutate global state from random utility functions. ([GitHub](https://github.com/hpma-bits/hawarma))

That gives you:

- offline benchmarking
- deterministic replay
- strategy experimentation
- future ML/RL possibilities
- easier debugging

A lot of game bots never escape “if image found -> click coordinate” spaghetti. Yours already escaped that trap.

------

# 2. Simulator-first mindset is excellent

`env_simulator.py` + `playground/bench`

This is probably the highest leverage part of the entire repo.

You effectively created:

- a rules engine
- a policy evaluation environment
- a reproducible experimentation layer

That means your project can evolve from:

> automation script

into:

> optimization research platform

Very important difference.

You can eventually:

- evolve heuristics safely
- run Monte Carlo evaluations
- compare strategies statistically
- introduce search/planning algorithms
- generate synthetic gameplay traces

without touching Airtest/device code.

That architecture scales surprisingly far.

------

# 3. Strategy abstraction is correctly placed

This part is especially good:

> ```
> Strategy.decide(state) -> actions
> ```

That boundary is clean.

It means:

- strategies are pure-ish
- execution is externalized
- diagnostics can wrap strategies
- benchmarking becomes trivial

This is basically the right shape for:

- heuristic AI
- utility AI
- GOAP-style planners
- tree search
- reinforcement learning adapters

You accidentally designed a mini-game-AI framework.

------

# 4. Runtime realism

Most automation projects ignore:

- latency
- visibility uncertainty
- execution contention
- partial information

Your repo *does not* ignore those.

The existence of:

- `visibility_aware`
- preemptive cooking
- stockpiling
- execution reservation concepts

means you are modeling:

- future utility
- opportunity cost
- temporal constraints

That’s real systems thinking.

------

# Where the architecture still hurts

Now the important part.

Your repo currently sits in an awkward middle state between:

- “clean layered architecture”
  and
- “research playground with evolving abstractions”

That creates several tension points.

------

# Biggest issue: Runtime State is too central

Based on your previous snippets + repo structure, your runtime state object is becoming:

- state container
- reservation system
- scheduler memory
- execution tracker
- order mapping
- coordination bus

That eventually turns into a “god object”.

The danger is not size.
The danger is *behavioral gravity*.

Everything starts depending on it.

Then:

- mutations become implicit
- debugging gets hard
- temporal bugs appear
- strategy logic leaks into state management

This is the single biggest architectural risk in the project.

------

# Recommendation: Split runtime state into 4 bounded contexts

Right now you probably have one giant “truth object”.

I’d split into:

## A. Observed World State

Pure observable facts.

```python
WorldState:
    orders
    stations
    ingredients
    timers
```

No reservations.
No planning.
No derived intent.

------

## B. Execution State

Tracks in-flight actions.

```python
ExecutionState:
    active_tasks
    pending_actions
    cooldowns
    reservations
```

This models:

> what the bot is currently doing

not the world.

------

## C. Planning State

Strategy-owned ephemeral reasoning.

```python
PlanningContext:
    utility_scores
    predicted shortages
    candidate chains
```

This should NOT become global truth.

Different strategies may compute different planning assumptions.

------

## D. Statistics / Telemetry

Never mix analytics into runtime coordination.

```python
Metrics:
    completed_orders
    station_utilization
    avg_wait_time
```

Keep this append-only.

------

# Second major issue: Action model probably isn’t formalized enough

Most likely actions are currently semi-implicit:

```python
touch(x, y)
cook(meat)
serve(order)
```

You need a more formal command layer.

Something closer to:

```python
Action(
    type=COOK,
    target=GRILL_1,
    item=MEAT,
    duration=5.0,
    priority=0.82,
)
```

Why this matters:

Because eventually you’ll want:

- scheduling
- cancellation
- preemption
- rollback reasoning
- simulation parity
- conflict detection

Without formal actions:
the simulator and real runtime slowly diverge.

That divergence kills optimization projects.

------

# Third issue: Bridge layer likely mixes perception + interpretation

Your `Scanner` probably returns already-interpreted objects.

That’s convenient early on.
But later it causes pain.

Better pipeline:

```text
Capture
→ Detection
→ Recognition
→ Interpretation
→ State reconstruction
```

Meaning:

```python
RawDetection
↓
DetectedOrderCard
↓
ParsedRecipeOrder
↓
GameStateProjection
```

Why?

Because debugging vision systems becomes WAY easier.

You can inspect:

- raw detection failures
- OCR failures
- parsing failures
- state reconciliation failures

independently.

Right now those layers are probably partially collapsed.

------

# Fourth issue: Strategies may be becoming “mega-strategies”

I suspect current strategies are too monolithic.

For example:

```python
GastronomeStrategy
```

probably owns:

- scoring
- prioritization
- cooking policy
- reservation policy
- timing
- interruption logic

That becomes impossible to tune.

------

# Better direction: policy composition

Instead of:

```python
BigStrategy.decide()
```

move toward:

```python
OrderSelectionPolicy
CookingPolicy
StockpilePolicy
RiskPolicy
ExecutionPolicy
```

Then compose them.

This becomes incredibly powerful because you can benchmark combinations.

Example:

| Order Policy  | Cooking Policy | Result |
| ------------- | -------------- | ------ |
| Greedy        | Conservative   | 72     |
| Utility       | Aggressive     | 88     |
| Timeout-aware | Predictive     | 94     |

Now your experimentation space becomes systematic.

------

# Fifth issue: Domain terminology is inconsistent

This matters more than people think.

You currently mix:

- task
- action
- operation
- job
- reservation
- execution
- command

You need a strict glossary.

For AI/simulation systems, naming consistency is huge.

I strongly recommend adding:

```text
docs/domain_language.md
```

Define:

- Action
- Task
- Intent
- Reservation
- Execution
- Observation
- Projection
- Strategy
- Plan

This reduces architectural drift massively over time.

------

# What I would prioritize next

In order:

## 1. Formalize the action pipeline

Most important.

Everything downstream improves:

- simulation
- debugging
- scheduling
- metrics
- replay

------

## 2. Split runtime state

Prevent future god-object collapse.

------

## 3. Introduce event sourcing-lite

Not full CQRS nonsense.

Just append events:

```python
OrderDetected
ActionQueued
ActionExecuted
OrderCompleted
```

Then:

- replay becomes trivial
- debugging becomes amazing
- benchmarking becomes scientific

------

## 4. Build deterministic replay

This is extremely high leverage.

Save:

- observations
- decisions
- actions

Then replay without device.

You’ll evolve strategies 10x faster.

------

## 5. Add “decision introspection”

Your strategies need explainability.

Example:

```python
Decision:
    action = COOK_MEAT
    score = 0.82
    reasons = [
        "predicted shortage",
        "grill idle",
        "high-demand ingredient",
    ]
```

This becomes priceless when tuning heuristics.

------

# Long-term architectural direction

Your project is naturally evolving toward:

```text
Perception Layer
→ World Reconstruction
→ Planning
→ Scheduling
→ Execution
→ Telemetry
```

That is the correct trajectory.

Do NOT regress back into:

- utility scripts
- giant managers
- shared mutable globals
- direct UI-driven logic

You’re already past that stage.

------

# Final assessment

The repo’s biggest strength is not code quality.

It’s that the *core abstractions are heading in the right direction*.

That’s rarer.

Most hobby automation repos optimize implementation details before discovering proper boundaries.
Yours is doing the opposite:

- imperfect implementation
- but increasingly correct architectural shape

That’s the better problem to have. ([GitHub](https://github.com/hpma-bits/hawarma))