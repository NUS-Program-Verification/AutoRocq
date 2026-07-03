# AutoRocq: Agentic Theorem Prover for Verification

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.en.html) [![License: Commercial](https://img.shields.io/badge/License-Commercial-green.svg)](LICENSE) [![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2?logo=discord&logoColor=white)](https://discord.gg/HfS2zcMzhS)

**Paper**: [FSE 2026](https://dl.acm.org/doi/10.1145/3808164)

---


This repository contains the source code of AutoRocq, an agent prover in Rocq (formerly Coq) 8.18.0.

To discharge a formally stated theorem in Rocq, the agent runs in the following loop:

```python
context = get_initial_context()
tools = ['plan', 'tactic', 'context_search']
while not coq.is_proof_complete():
    action = llm.next_action(goal, context)
    coq.apply(action)
    context.update()
    goal.update()
```

where the LLM interacts with the Rocq proof assistant (via [CoqPyt](https://github.com/sr-lab/coqpyt)) in real time to develop a proof. 

---

### What's New

#### LiteLLM support

AutoRocq now supports your favorite model through LiteLLM! See the supported model [list](https://models.litellm.ai) and [configuration](proof-search/configs/readme.md).

#### Interactive REPL

AutoRocq now supports [interactive mode](#interactive-mode), where you can *co-develop* a proof with the agent, monitoring progress and providing hints in real time with the built-in [shell](#repl-commands).

---

### Directory Structure

```
AutoRocq-bench/                    # Benchmark of verification theorems

dockerfile/                        # Dockerfile of AutoRocq and comparison tools

eval/                              # Directory for eval results
└── final/                         # Final evluation results

proof-search/                      # Directory of proof agent src
├── main.py                        # Entry point
├── agent/                         
│   ├── proof_controller.py        # Main loop
│   ├── context_manager.py         # LLM interaction and context management
│   ├── context_search.py          # Local context search
│   ├── history_recorder.py        # Manages proof histories
│   ├── proof_tree.py              # Manages proof tree
│   └── interactive_session.py     # Interactive REPL loop
├── backend/                       # Interface with CoqPyt
├── coqpyt/                        # Interact with Coq
└── utils/                         # Helper functions

scripts/                           # Directory of scripts
├── analyze/                       # Analysis scripts of final results
└── get_results.py                 # Parser of .json results
```

### Setup Instructions

1. Install dependencies in Python

```bash
pip install -r requirement.txt
```

2. Install dependencies in opam

```bash
opam switch import deps.opam
```

### Minimal Example of Proof Agent

1. Set up API key in the config or by running `export OPENAI_API_KEY=...`. If you prefer models from other providers, see [here](proof-search/configs/readme.md).

2. To prove [`examples/example.v`](proof-search/examples/example.v) with a minimal [config](proof-search/configs/minimal.json), go to `proof-search` directory and run:

```bash
python3 -m main examples/example.v --config ./configs/minimal.json
```

If AutoRocq runs successfully, you will be able to see in the terminal
```
[INFO] [Main]: 🎉 Proof completed successfully!
```
and the proof script is saved in the same [`example.v`](proof-search/examples/example.v) file. You will also be able to find saved proof states and aggregated results at `data/`, which can be reused to prove other goals in the future.

For more configurations of the tool, check out the [readme](proof-search/configs/readme.md) or run with `--help` for more options.

### Proving Theorems from Verification Tasks

[AutoRocq-bench](https://github.com/NUS-Program-Verification/AutoRocq-bench) is a corpus of Rocq/Coq proof obligations extracted from real C code with [Frama-C](https://www.frama-c.com/) curated as part of the evaluation of AutoRocq. 
The benchmark consists of 641 theorems generated from [SV-COMP](https://gitlab.com/sosy-lab/sv-comp/bench-defs) and 60 theorems from [assertions in the Linux kernel](https://github.com/evdenis/verker).
On average, running each theorem costs ~$0.5 with GPT-4.1. 
To test on this benchmark:

1. Clone the submodule with

```bash
git submodule update --init --recursive
```

2. Compile `libautorocq` by running

```bash
cd AutoRocq-bench/libautorocq; make
```

3. Configure `library_paths` in `proof-search/configs/default_config.json` to point to `libautorocq`.

4. Run the agent by pointing to the target `.v` file. The first run may take a few minutes to initialize the library.

For example, go to `proof-search` directory and run:

```bash
python3 -m main examples/main_assert_rte_signed_overflow.v --config ./configs/default_config.json
```

---

### Interactive Mode

In addition to running AutoRocq in a hands-off style, you can *co-develop* Rocq proofs with the agent in interactive mode.
The agent exposes a REPL where you can steer, inspect, and contribute tactics alongside the LLM.

**Starting interactive mode** — pass `--interactive` (or `-i`) on the command line:

```bash
python3 -m main examples/example.v --config ./configs/minimal.json --interactive
```

Or enable it permanently in your config:

```json
{
  "interactive": {
    "enabled": true
  }
}
```

**What interactive mode does**

- **Stepping through proofs** — you can step through AutoRocq's generation and understand its trajectory.
- **Adding hints for agent** — You can add natural language `hint` to guide AutoRocq's proof strategy.
- **Co-writing proofs** — you can directly add `tactic`, print `tree`, run `search`, or `rollback` as you wish. Existing proof steps and manual edits are preserved, AutoRocq picks up exactly where you left.

#### REPL commands

| Command        | Description                                                                                                                                                                                     |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `step`         | Agent takes one action (tactic attempt or rollback), then pauses                                                                                                                                |
| `run`          | Agent runs until the focused goal changes, the agent rolls back, or the proof completes. Failed tactics are handled internally and do not stop `run`                                            |
| `tactic <tac>` | Apply a Rocq tactic directly (bypasses the LLM). Example: `tactic intros n.`                                                                                                                    |
| `hint <text>`  | Inject a natural-language hint into the agent's next prompt. Example: `hint try induction on n`                                                                                                 |
| `rollback [n]` | Undo the last `n` applied tactics (default 1), regardless of whether they were applied by you or the agent. If `n` exceeds the number of applied tactics, rolls back to `Proof.` with a warning |
| `search <cmd>` | Run a Rocq query and print the results (display-only; does not inject into LLM context). Examples: `search Search Z.add`, `search Print Z.add_comm`, `search Check Z.add`                       |
| `status`       | Display the current proof goal and hypotheses                                                                                                                                                   |
| `explain`      | Show agent reasoning history                                                                                                                                                                    |
| `tree`         | Display the current proof tree with tactic history                                                                                                                                              |
| `help`         | Print all available commands                                                                                                                                                                    |
| `quit`         | Exit the session                                                                                                                                                                                |

---

### Replicating Results from Paper

<details> 
<summary><b>Reproducing Figures</b></summary>

<br>

- Figure 3

```bash
python3 scripts/analyze/draw_complexity.py \
  ./eval/final/complexity-svcomp.csv \
  ./eval/final/complexity-coqgym-sample.csv
```

- Figure 4, 5, 6, and 7

```bash
python3 scripts/analyze/draw_results.py \
  ./eval/final/results-svcomp.csv ./eval/final/complexity-svcomp.csv \
  ./eval/final/results-coqgym.csv ./eval/final/complexity-coqgym-sample.csv
```

- Figure 8

```bash
python3 scripts/analyze/plot_searches.py
```
</details> 

<details> 
<summary><b>Setting Up Comparison Tools</b></summary>

<br>

Coming soon...

</details>

---

### Citation / Attribution

If you are interested in the work, consider joining the [Discord](https://discord.gg/HfS2zcMzhS) server for the latest discussions/development of agentic program verification!

If you use our work for academic research, please cite our paper:

```
@article{autorocq,
  title={Agentic Verification of Software Systems},
  author={Tu, Haoxin and Zhao, Huan and Song, Yahui and Zafar, Mehtab and Meng, Ruijie and Roychoudhury, Abhik},
  year = {2026},
  issue_date = {July 2026},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  volume = {3},
  number = {FSE},
  url = {https://doi.org/10.1145/3808164},
  doi = {10.1145/3808164},
  journal = {Proc. ACM Softw. Eng.}
}
```

