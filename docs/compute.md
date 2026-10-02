# Running the experiment jobs on Colab

Open the notebook straight from GitHub (the repo is public):
**https://colab.research.google.com/github/liteleliya/Reasoning-AI-Agents---Kasukabe-Defence-Group/blob/main/notebooks/colab_run.ipynb**

1. *Runtime → Change runtime type → T4 GPU*.
2. In cell 1 set `JOB`, `SHARD`, `REF` (the git tag), then *Runtime → Run all*.
3. Allow Google Drive access when asked. Results land in `MyDrive/kasukabe/<JOB>/`.
4. When the last cell prints its summary, copy it and send it on. If a cell fails, run the
   last cell and send everything it prints.

| Job | `JOB` | `REF` | What it is | Expected time on a T4 |
|---|---|---|---|---|
| J1 | `j1_parse` | `jobs-v1` | 50 calls: share of model replies that parse as valid PXP messages | ~10 min incl. setup |
| J2 | `j2_baseline` | `jobs-v1` | 100 sessions, standard agents only: how often agents deadlock | ~1 h |
| J3 | `j3_prelim` | `jobs-v2` | 30 questions × 0/1/2/3 counterfactual agents = 120 sessions | 1–2 h |

J1 and J2 can run back to back in one Colab session: after J1 finishes, change `JOB` to
`j2_baseline` in cell 1 and run cells 1 and 7 again (the server keeps running).

**Model:** Ollama serving `qwen2.5:7b-instruct` (Q4_K_M), 8 sessions in parallel, 8k context.
That is the same build Ollama serves on a laptop, so any Colab run can be reproduced locally.
`BACKEND = "vllm"` switches to vLLM with `Qwen/Qwen2.5-7B-Instruct-AWQ` (faster, but a different
build: never mix the two within one job).

**Disconnects:** free Colab stops after ~12 h or when the tab is idle too long. Run all again;
finished sessions are skipped and the job resumes from the files on Drive. If Colab refuses a
GPU, wait an hour or use another Google account.

**Times above are estimates** until the first run; replace them here with measured numbers.
