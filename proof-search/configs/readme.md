## Configuration and Options

AutoRocq can be configured through a JSON config file, command-line arguments, or environment variables. When multiple sources are present, the priority is:

1. Command-line arguments (highest)
2. Config file (`--config` or `configs/default_config.json`)
3. Environment variables
4. Built-in defaults

### Command-Line Usage

```
python3 -m main [proof_file] [options]
```

| Argument | Short | Description |
|---|---|---|
| `proof_file` | | Path to the Coq `.v` file. Falls back to `proof_file_path` from config if omitted. |
| `--theorem` | `-t` | Specific theorem name to prove. Auto-detected if omitted. |
| `--config` | `-c` | Path to a JSON configuration file. |
| `--plan` | `-p` | Path to a proof plan file (plain text). |
| `--max-steps` | | Maximum proof steps to attempt. Overrides the config value. |
| `--log-level` | | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. Overrides the config value. |
| `--library-path PATH NAME` | | Add a custom Coq library path mapping. Can be repeated. |
| `--coqproject-option OPT` | | Add an extra option to the generated `_CoqProject` file. Can be repeated. |
| `--workspace` | | Set the workspace directory for Coq. |
| `--local-session-caching` | | Enable local session caching (stored to a local file). |

**Examples:**

```bash
# Custom config and step limit
python3 -m main examples/example.v --config configs/minimal.json --max-steps 100

# With a custom library
python3 -m main examples/example.v --library-path /path/to/lib libname

# Multiple extra CoqProject options
python3 -m main examples/example.v --coqproject-option "-arg" --coqproject-option "-impredicative-set"
```

---

### Config File Reference

The JSON config file has three top-level sections: `llm`, `coq`, `ablation`, plus a few root-level keys.

#### `llm` — LLM Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `model` | string | `gpt-4.1` | LLM model name. Only OpenAI models are supported at the moment. |
| `temperature` | float | `0.1` | Sampling temperature. |
| `max_tokens` | int | `512` | Maximum tokens per LLM response. |
| `api_key` | string | `null` | API key. Can also be set via `OPENAI_API_KEY` env var. |
| `timeout` | int | `30` | LLM request timeout in seconds. |
| `enable_caching` | bool | `true` | Enable prompt-level caching for repeated queries. |

#### `coq` — Coq Interface Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `timeout` | int | `10` | Timeout for individual Coq commands (seconds). |
| `max_steps` | int | `50` | Maximum number of proof steps to attempt. |
| `proof_file_path` | string | `"proof.v"` | Default proof file path (used when no file is given on the CLI). |
| `coq_path` | string | `null` | Path to the Coq binary. Uses system Coq if `null`. |
| `workspace` | string | `null` | Workspace directory. Defaults to the proof file's parent directory. |
| `library_paths` | list | `[]` | Custom Coq library paths. Each entry is `{"path": "/abs/path", "name": "libname"}`. |
| `auto_setup_coqproject` | bool | `true` | Automatically generate a `_CoqProject` file from library paths. |
| `coqproject_extra_options` | list | `[]` | Extra options appended to `_CoqProject` (e.g., `["-arg", "-impredicative-set"]`). |

#### `ablation` — Component Ablation Toggles

These flags enable or disable individual agent components, useful for ablation studies.

| Key | Type | Default | Description |
|---|---|---|---|
| `enable_recording` | bool | `true` | Record successful tactics to history for future use. |
| `enable_history_context` | bool | `true` | Provide tactic history on repeated failures. |
| `enable_hammer` | bool | `false` | Enable CoqHammer integration. Automatically imports Hammer when `true`. This feature is experimental at the moment. |
| `enable_context_search` | bool | `true` | Enable context search during proof attempts. |
| `enable_rollback` | bool | `true` | Allow rolling back failed proof steps. |
| `max_context_search` | int | `3` | Maximum number of context searches per proof attempt. |
| `max_errors` | int | `3` | Maximum consecutive errors before giving up on a tactic. |

#### Root-Level Keys

| Key | Type | Default | Description |
|---|---|---|---|
| `log_level` | string | `"INFO"` | Logging level: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `log_file` | string | `null` | Path to a log file. Auto-generated in the output directory if `null`. |
| `output_dir` | string | `null` | Output directory for logs and statistics. Auto-generated if `null`. |

---

### Environment Variables

The following environment variables are recognized as fallbacks when no config file is present:

| Variable | Maps To |
|---|---|
| `OPENAI_API_KEY` | `llm.api_key` |
| `LLM_MODEL` | `llm.model` |
| `LLM_TEMPERATURE` | `llm.temperature` |
| `COQ_PATH` | `coq.coq_path` |
| `PROOF_FILE_PATH` | `coq.proof_file_path` |
| `COQ_WORKSPACE` | `coq.workspace` |
| `LOG_LEVEL` | `log_level` |
| `LOG_FILE` | `log_file` |

---

### Example Configs


**[`minimal.json`](minimal.json)** — Lightweight config for quick tests:

```json
{
  "llm": {
    "model": "gpt-4.1",
    "temperature": 0.0,
    "max_tokens": 2000,
    "timeout": 30,
    "enable_caching": true
  },
  "coq": {
    "timeout": 60,
    "max_steps": 10,
    "library_paths": [],
    "auto_setup_coqproject": true
  },
  "ablation": {
    "enable_recording": true,
    "enable_error_feedback": true,
    "enable_context_search": true,
    "max_errors": 3
  },
  "log_level": "INFO"
}
```


**[`default_config.json`](default_config.json)** — Full-featured config with a custom library:

```json
{
  "llm": {
    "model": "gpt-4.1",
    "temperature": 0.0,
    "max_tokens": 2000,
    "timeout": 30,
    "enable_caching": true
  },
  "coq": {
    "timeout": 60,
    "max_steps": 100,
    "library_paths": [
      {"path": "/autorocq/AutoRocq-bench/libautorocq", "name": "libframac"}
    ],
    "auto_setup_coqproject": true
  },
  "ablation": {
    "enable_recording": true,
    "enable_error_feedback": true,
    "enable_history_context": true,
    "enable_rollback": false,
    "enable_hammer": false,
    "enable_context_search": true,
    "max_context_search": 3,
    "max_errors": 3
  },
  "log_level": "INFO"
}
```
