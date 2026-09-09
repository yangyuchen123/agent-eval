# AgentEval project instructions

## Experiment execution policy

Experiments are reproducible data-production jobs, not one-off scripts.

- Do not create a new `run_*.py` runner for each experiment.
- Formal experiments must use the shared experiment runner.
- Experimental differences must be expressed through declarative config/manifest files, not copied execution code.
- If the shared runner lacks a capability, extend the shared runner instead of cloning it.
- A standalone experiment runner requires explicit approval and must document why the shared runner cannot be extended.
- Every formal experiment must declare:
  - dataset and immutable input refs;
  - case/task IDs;
  - treatment variables;
  - frozen variables;
  - judge/model/provider/config;
  - prompt/schema/protocol versions;
  - output directory;
  - expected call topology and cost tier.
- The runner must verify that only declared treatment variables differ between conditions.
- The runner must record input, prompt, schema, code/config and output digests.
- Historical result files are immutable. New replay results go to a new versioned output directory.
- A result may not be called a baseline unless its condition definition and protocol digest match the baseline definition.
- Do not reuse a result produced by a different condition merely because the filenames or labels look similar.
- Before running an expensive stage, perform a protocol and input-digest sanity check on a small fixed subset.

The existing `run_frozen_abcd.py` is a transitional frozen runner created before this policy was added. Do not create more condition-specific runners; migrate future work to the shared runner/config structure.
