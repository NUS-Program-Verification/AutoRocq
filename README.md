# AutoRocq: Agentic Theorem Prover for Verification

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.en.html) [![License: Commercial](https://img.shields.io/badge/License-Commercial-green.svg)](LICENSE)

**Paper**: [FSE 2026](https://arxiv.org/abs/2511.17330)

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
│   └── proof_tree.py              # Manages proof tree
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

1. Set up API key in the config or by running `export OPENAI_API_KEY=...`

2. From `proof-search` directory, run:

```bash
python3 -m main examples/example.v --config ./configs/minimal.json
```

Run with `--help` for more options.

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

If you use our work for academic research, please cite our paper:

```
@article{autorocq,
  title={Agentic Verification of Software Systems},
  author={Tu, Haoxin and Zhao, Huan and Song, Yahui and Zafar, Mehtab and Meng, Ruijie and Roychoudhury, Abhik},
  journal={Proceedings of the ACM on Software Engineering},
  volume={1},
  number={FSE},
  year={2026},
  publisher={ACM New York, NY, USA}
}
```
