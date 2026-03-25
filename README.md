# AutoRocq: Agentic Verification of Software Systems

This repository contains the source code of AutoRocq, an agent prover in Rocq.

### Main Agent Loop (Pseudo)

```
tools = ['plan', 'query', 'tactic', 'rollback']

context = get_initial_context()

while not coq.is_proof_complete():
    action = llm.next_action(goal, context)
    action_handler(action)
    context.update()
    goal.update()
```

### Directory Structure

```
eval/                              # Directory for eval results
└── final/                         # Final evluation results

AutoRocq-bench/                    # Benchmark of verification lemmas

dockerfile/                        # Dockerfile of AutoRocq and comparison tools

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

### Testing on [AutoRocq-bench](https://github.com/NUS-Program-Verification/AutoRocq-bench)

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


## Reproducing Figures

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


## Citation / Attribution

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