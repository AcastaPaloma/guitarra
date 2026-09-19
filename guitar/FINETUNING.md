# Fine-tuning status — deferred, not required

**The current guitar plan does not require fine-tuning.** Build and evaluate the
[closed-loop rehearsal system](REHEARSAL_LOOP.md) with fixed pretrained models first.
[DESIGN.md](DESIGN.md) owns that decision; [STATUS.md](STATUS.md) separates source from plans.

## What we are doing now

1. A planner proposes a supported attempt.
2. Local code validates and executes it through qualified tools on the same arms.
3. Optional pretrained audio-model assessment and telemetry describe the result.
4. The planner receives that history and revises an approved plan/profile.
5. Save the best validated plan explicitly for reuse after fresh-state checks.

No optimizer updates the neural-network weights during this process. “Tune the performance”
means revise the plan/context, not fine-tune the model. Improvement must be demonstrated,
not assumed just because the model changed its answer.

| Activity | Weight fine-tuning? |
|---|---|
| Supply a new camera observation or recording | No; inference input |
| Include previous attempts in the prompt | No; context update |
| Change an approved phrase/profile or save a successful plan | No; application state |
| Run a pretrained model on a Baseten GPU | No; inference serving |
| Update model parameters/adapters using a training objective | Yes; separate training work |

## What is not on the critical path

- Training an audio/buzz classifier or a joint audio-video agent.
- Collecting a large demonstration dataset before the first feedback loop.
- Using an H100 merely to claim a training contribution.
- Physical reinforcement learning, sim-to-real string physics, or an LLM predicting exact
  millisecond dynamics from invented labels.
- Fine-tuning Astra without accessible weights or an explicitly supported provider API.

Baseten can be central through actual pretrained inference, useful feedback, and measured
serving behavior. Training is not required for that architecture.

## When to reconsider training

Only after a working baseline reveals a specific persistent problem, enough permissioned
and correctly labeled data exists, and held-out testing can establish a benefit. Examples:
reducing a planner's unsupported proposals, distilling useful decisions into a smaller
model, or a measured timing-estimation problem that simpler code cannot handle well.

Use the simplest method that solves the problem. A transition table/regressor may be
better than an LLM; a deterministic planner may be better than distilling it. No trained
model can change grip settings, safety limits, or the final local execution authority.

## Preserved optional proposal

[Symbolic plan-selector LoRA research](research/PLAN_SELECTOR_FINETUNING.md) retains the
previous detailed idea, dataset/evaluation requirements, and Baseten job references. It
is explicitly deferred—not a build order, a live deployment, a completed result, or
permission to incur GPU cost. Reviving it requires an explicit decision and budget.
