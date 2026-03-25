import logging
import re
from pathlib import Path
from typing import Optional

def clean_ansi_codes(text):
    """Remove ANSI escape codes from text."""
    if not text:
        return ""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

class ANSIStripFormatter(logging.Formatter):    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
            
    def format(self, record):
        message = super().format(record)
        return clean_ansi_codes(message)


LOG_LEVEL = "INFO"
LOG_FILE = None
CONSOLE_OUTPUT = True

def global_logger(level, log_file, console_output):
    global LOG_LEVEL, LOG_FILE, CONSOLE_OUTPUT
    LOG_LEVEL = level
    LOG_FILE = log_file
    CONSOLE_OUTPUT = console_output

def setup_logger(
    name: str,
    level: Optional[str] = None, 
    log_file: Optional[str] = None,
    console_output: Optional[bool] = None
) -> logging.Logger:
    """
    Set up a logger with both file and console handlers.
    
    Args:
        name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        console_output: Whether to output to console
        
    Returns:
        Configured logger instance
    """
    # Use global settings if not provided
    global LOG_LEVEL, LOG_FILE, CONSOLE_OUTPUT
    if log_file is None:
        log_file = LOG_FILE
    if level is None:
        level = LOG_LEVEL
    if console_output is None:
        console_output = CONSOLE_OUTPUT

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Avoid duplicate output
    logger.propagate = False
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create formatters
    file_formatter = ANSIStripFormatter(
        fmt='%(asctime)s|%(levelname)s|%(name)s|%(message)s',
        datefmt='%Y%m%d_%H%M%S'
    )
    
    console_formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] [%(name)s]: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler with ANSI stripping
    if log_file:
        # Ensure .txt extension
        log_file = str(Path(log_file))
        
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(file_formatter)  # Uses ANSI-stripping formatter
        logger.addHandler(file_handler)
    
    # Console handler (keeps ANSI codes for colored terminal output)
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, level.upper()))
        console_handler.setFormatter(console_formatter)  # Regular formatter
        logger.addHandler(console_handler)
    
    return logger


class ProofLogger:
    """Context manager for proof-specific logging."""
    
    def __init__(self, theorem_name: str, log_dir: str = "logs"):
        self.theorem_name = theorem_name
        self.log_dir = Path(log_dir)
        self.log_file = None
        self.logger = None
        
    def __enter__(self):
        # Create log file for this proof session
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / f"{self.theorem_name}_{self._timestamp()}.log"
        
        self.logger = setup_logger(
            name=f"proof_{self.theorem_name}",
            log_file=str(self.log_file),
            console_output=True
        )
        
        self.logger.info(f"Starting proof session for theorem: {self.theorem_name}")
        return self.logger
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.logger:
            if exc_type:
                self.logger.error(f"Proof session ended with error: {exc_val}")
            else:
                self.logger.info(f"Proof session completed for theorem: {self.theorem_name}")
    
    def _timestamp(self) -> str:
        """Generate timestamp for log file."""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")