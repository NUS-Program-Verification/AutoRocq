import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, field

@dataclass
class LLMConfig:
    """Configuration for LLM settings."""
    model: str = "openai/gpt-4.1"
    temperature: float = 0.1
    max_tokens: int = 512
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    timeout: int = 30
    enable_caching: bool = True

@dataclass
class CoqConfig:
    """Configuration for Coq interface."""
    timeout: int = 10
    max_steps: int = 50
    proof_file_path: str = "proof.v"  # This will be updated at runtime
    coq_path: Optional[str] = None
    workspace: Optional[str] = None
    # NEW: Generic library configuration
    library_paths: List[Dict[str, str]] = field(default_factory=list)
    # Format: [{"path": "/abs/path/to/lib", "name": "libname"}, ...]
    auto_setup_coqproject: bool = True
    coqproject_extra_options: List[str] = field(default_factory=list)
    # Additional options to add to _CoqProject (e.g., ["-arg", "-impredicative-set"])

@dataclass
class ProofAgentConfig:
    """Main configuration for the proof agent."""
    llm: LLMConfig
    coq: CoqConfig

    # General settings
    log_level: str = "INFO"
    log_file: Optional[str] = None
    output_dir: Optional[str] = None

    # Component ablation settings
    enable_recording: bool = True
    enable_history_context: bool = True
    enable_error_feedback: bool = True
    enable_hammer: bool = False
    enable_context_search: bool = True
    enable_rollback: bool = True
    max_context_search: int = 3
    max_errors: int = 3
    
    @classmethod
    def from_file(cls, config_path: str) -> 'ProofAgentConfig':
        """Load configuration from JSON file."""
        config_path = Path(config_path)
        
        if not config_path.exists():
            # Create default config file
            default_config = cls.default()
            default_config.save_to_file(config_path)
            return default_config
        
        with open(config_path, 'r') as f:
            config_dict = json.load(f)
        
        # --- Parse ablation toggles if present ---
        ablation = config_dict.get("ablation", {})
        return cls(
            llm=LLMConfig(**config_dict.get('llm', {})),
            coq=CoqConfig(**config_dict.get('coq', {})),
            log_level=config_dict.get("log_level", "INFO"),
            log_file=config_dict.get("log_file"),
            output_dir=config_dict.get("output_dir"),
            enable_rollback=ablation.get("enable_rollback", True),
            enable_context_search=ablation.get("enable_context_search", True),
            enable_error_feedback=ablation.get("enable_error_feedback", True),
            enable_hammer=ablation.get("enable_hammer", False),
            enable_history_context=ablation.get("enable_history_context", True),
            enable_recording=ablation.get("enable_recording", True),
            max_context_search=ablation.get("max_context_search", 3),
            max_errors=ablation.get("max_errors", 3),
        )
    
    @classmethod
    def default(cls) -> 'ProofAgentConfig':
        """Create default configuration."""
        return cls(
            llm=LLMConfig(),
            coq=CoqConfig(),
        )
    
    @classmethod
    def from_env(cls) -> 'ProofAgentConfig':
        """Load configuration from environment variables."""
        config = cls.default()
        
        # LLM settings
        if os.getenv('LLM_MODEL'):
            config.llm.model = os.getenv('LLM_MODEL')
        if os.getenv('LLM_TEMPERATURE'):
            config.llm.temperature = float(os.getenv('LLM_TEMPERATURE'))
            
        # Coq settings
        if os.getenv('COQ_PATH'):
            config.coq.coq_path = os.getenv('COQ_PATH')
        if os.getenv('PROOF_FILE_PATH'):
            config.coq.proof_file_path = os.getenv('PROOF_FILE_PATH')
        if os.getenv('COQ_WORKSPACE'):
            config.coq.workspace = os.getenv('COQ_WORKSPACE')
            
        # General settings
        if os.getenv('LOG_LEVEL'):
            config.log_level = os.getenv('LOG_LEVEL')
        if os.getenv('LOG_FILE'):
            config.log_file = os.getenv('LOG_FILE')
            
        return config
    
    def save_to_file(self, config_path: str):
        """Save configuration to JSON file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        config_dict = {
            'llm': asdict(self.llm),
            'coq': asdict(self.coq),
            'enable_rollback': self.enable_rollback,
            'log_level': self.log_level,
            'log_file': self.log_file,
            'output_dir': self.output_dir
        }
        
        with open(config_path, 'w') as f:
            json.dump(config_dict, f, indent=2)
    
    def update_from_dict(self, updates: Dict[str, Any]):
        """Update configuration from dictionary."""
        for key, value in updates.items():
            if hasattr(self, key):
                if key in ['llm', 'coq']:
                    # Update nested config objects
                    config_obj = getattr(self, key)
                    for sub_key, sub_value in value.items():
                        if hasattr(config_obj, sub_key):
                            setattr(config_obj, sub_key, sub_value)
                else:
                    setattr(self, key, value)

def load_config(config_path: Optional[str] = None) -> ProofAgentConfig:
    """
    Load configuration with fallback priority:
    1. Config file (if provided)
    2. Default config file (configs/default_config.json)
    3. Environment variables
    4. Default values
    """
    # First priority: explicit config path
    if config_path and Path(config_path).exists():
        return ProofAgentConfig.from_file(config_path)
    
    # Second priority: default config file
    default_config_path = Path(__file__).parent.parent / "configs" / "default_config.json"
    if default_config_path.exists():
        return ProofAgentConfig.from_file(str(default_config_path))
    
    # Third priority: environment variables
    elif any(key.startswith(('OPENAI_', 'LLM_', 'COQ_', 'LOG_')) for key in os.environ):
        return ProofAgentConfig.from_env()
    
    # Last resort: default values
    else:
        return ProofAgentConfig.default()

def get_data_path(filename: str) -> Path:
    """Get path to data file."""
    return Path(__file__).parent.parent / "data" / filename

def get_log_path(filename: str) -> Path:
    """Get path to log file."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir / filename