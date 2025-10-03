"""Enhanced error recovery mechanisms for PDF processing operations."""

import time
import json
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager
import shutil
import subprocess

from .logging_config import get_logger
from .errors import PDFProcessingError, SystemToolError, FileAccessError
from ..config import get_config


class RecoveryStrategy(Enum):
    """Types of recovery strategies."""
    RETRY = "retry"
    FALLBACK = "fallback"
    PARTIAL_RECOVERY = "partial_recovery"
    SAFE_MODE = "safe_mode"
    ALTERNATIVE_TOOL = "alternative_tool"
    SKIP_AND_CONTINUE = "skip_and_continue"


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"          # Warnings, minor issues
    MEDIUM = "medium"    # Recoverable errors
    HIGH = "high"        # Serious errors, may affect quality
    CRITICAL = "critical"  # Fatal errors, processing cannot continue


@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt."""
    timestamp: float
    strategy: RecoveryStrategy
    error_type: str
    error_message: str
    success: bool
    duration: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorContext:
    """Context information about an error."""
    operation: str
    file_path: Path
    parameters: Dict[str, Any]
    error: Exception
    severity: ErrorSeverity
    recovery_attempts: List[RecoveryAttempt] = field(default_factory=list)
    
    @property
    def attempt_count(self) -> int:
        """Number of recovery attempts."""
        return len(self.recovery_attempts)
    
    @property
    def last_attempt(self) -> Optional[RecoveryAttempt]:
        """Last recovery attempt."""
        return self.recovery_attempts[-1] if self.recovery_attempts else None


class RecoveryRule:
    """Rule for handling specific types of errors."""
    
    def __init__(self, 
                 error_patterns: List[str],
                 strategies: List[RecoveryStrategy],
                 max_attempts: int = 3,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM):
        self.error_patterns = error_patterns
        self.strategies = strategies
        self.max_attempts = max_attempts
        self.severity = severity
    
    def matches(self, error: Exception) -> bool:
        """Check if this rule applies to the given error."""
        error_str = str(error).lower()
        return any(pattern.lower() in error_str for pattern in self.error_patterns)
    
    def get_next_strategy(self, context: ErrorContext) -> Optional[RecoveryStrategy]:
        """Get the next recovery strategy to try."""
        if context.attempt_count >= self.max_attempts:
            return None
        
        # Try strategies in order
        attempted_strategies = {attempt.strategy for attempt in context.recovery_attempts}
        
        for strategy in self.strategies:
            if strategy not in attempted_strategies:
                return strategy
        
        return None


class ErrorRecoveryManager:
    """Manages error recovery for PDF processing operations."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.config = get_config()
        
        # Recovery rules
        self.rules: List[RecoveryRule] = []
        self._init_default_rules()
        
        # Recovery history
        self.recovery_history: Dict[str, List[ErrorContext]] = {}
        
        # Thread-safe operations
        self._lock = threading.Lock()
    
    def _init_default_rules(self):
        """Initialize default recovery rules."""
        
        # File access errors
        self.rules.append(RecoveryRule(
            error_patterns=["permission denied", "access denied", "file in use"],
            strategies=[RecoveryStrategy.RETRY, RecoveryStrategy.FALLBACK],
            max_attempts=3,
            severity=ErrorSeverity.MEDIUM
        ))
        
        # Memory errors
        self.rules.append(RecoveryRule(
            error_patterns=["memory", "out of memory", "memoryerror"],
            strategies=[RecoveryStrategy.SAFE_MODE, RecoveryStrategy.PARTIAL_RECOVERY],
            max_attempts=2,
            severity=ErrorSeverity.HIGH
        ))
        
        # Ghostscript errors
        self.rules.append(RecoveryRule(
            error_patterns=["ghostscript", "gs failed", "pdf error"],
            strategies=[RecoveryStrategy.FALLBACK, RecoveryStrategy.SAFE_MODE, RecoveryStrategy.ALTERNATIVE_TOOL],
            max_attempts=3,
            severity=ErrorSeverity.MEDIUM
        ))
        
        # OCR errors
        self.rules.append(RecoveryRule(
            error_patterns=["tesseract", "ocr failed", "language pack"],
            strategies=[RecoveryStrategy.FALLBACK, RecoveryStrategy.ALTERNATIVE_TOOL],
            max_attempts=2,
            severity=ErrorSeverity.MEDIUM
        ))
        
        # Corrupted file errors
        self.rules.append(RecoveryRule(
            error_patterns=["corrupted", "invalid pdf", "malformed", "damaged"],
            strategies=[RecoveryStrategy.PARTIAL_RECOVERY, RecoveryStrategy.SAFE_MODE],
            max_attempts=2,
            severity=ErrorSeverity.HIGH
        ))
        
        # Network/timeout errors
        self.rules.append(RecoveryRule(
            error_patterns=["timeout", "connection", "network"],
            strategies=[RecoveryStrategy.RETRY],
            max_attempts=3,
            severity=ErrorSeverity.LOW
        ))
        
        # Disk space errors
        self.rules.append(RecoveryRule(
            error_patterns=["no space", "disk full", "insufficient space"],
            strategies=[RecoveryStrategy.SAFE_MODE, RecoveryStrategy.SKIP_AND_CONTINUE],
            max_attempts=1,
            severity=ErrorSeverity.CRITICAL
        ))
    
    def _determine_severity(self, error: Exception) -> ErrorSeverity:
        """Determine error severity based on error type and message."""
        
        error_str = str(error).lower()
        
        # Critical errors
        if any(pattern in error_str for pattern in ["disk full", "no space", "critical", "fatal"]):
            return ErrorSeverity.CRITICAL
        
        # High severity errors
        if any(pattern in error_str for pattern in ["memory", "corrupted", "damaged", "malformed"]):
            return ErrorSeverity.HIGH
        
        # Medium severity errors
        if any(pattern in error_str for pattern in ["failed", "error", "exception"]):
            return ErrorSeverity.MEDIUM
        
        # Default to low
        return ErrorSeverity.LOW
    
    def _find_matching_rule(self, error: Exception) -> Optional[RecoveryRule]:
        """Find the first matching recovery rule for an error."""
        for rule in self.rules:
            if rule.matches(error):
                return rule
        return None
    
    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create a backup of the file for recovery purposes."""
        try:
            backup_path = file_path.with_suffix(f".backup_{int(time.time())}")
            shutil.copy2(file_path, backup_path)
            self.logger.debug(f"Created backup: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.warning(f"Failed to create backup for {file_path}: {e}")
            return None
    
    def _attempt_file_repair(self, file_path: Path) -> bool:
        """Attempt to repair a corrupted PDF file."""
        try:
            # Try using ghostscript to repair the PDF
            repair_cmd = [
                "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
                "-dPDFSETTINGS=/prepress", "-dCompatibilityLevel=1.4",
                f"-sOutputFile={file_path}.repaired", str(file_path)
            ]
            
            result = subprocess.run(repair_cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                # Replace original with repaired version
                repaired_path = Path(f"{file_path}.repaired")
                if repaired_path.exists():
                    shutil.move(repaired_path, file_path)
                    self.logger.info(f"Successfully repaired PDF: {file_path}")
                    return True
            
        except Exception as e:
            self.logger.warning(f"PDF repair attempt failed: {e}")
        
        return False
    
    def _apply_retry_strategy(self, context: ErrorContext, operation_func: Callable, 
                            delay: float = 1.0) -> Tuple[bool, Any]:
        """Apply retry strategy with exponential backoff."""
        
        attempt_start = time.time()
        
        try:
            # Wait before retry (exponential backoff)
            wait_time = delay * (2 ** context.attempt_count)
            time.sleep(min(wait_time, 30))  # Cap at 30 seconds
            
            # Retry the operation
            result = operation_func()
            
            # Success
            duration = time.time() - attempt_start
            attempt = RecoveryAttempt(
                timestamp=attempt_start,
                strategy=RecoveryStrategy.RETRY,
                error_type=type(context.error).__name__,
                error_message=str(context.error),
                success=True,
                duration=duration,
                details={"retry_delay": wait_time}
            )
            context.recovery_attempts.append(attempt)
            
            self.logger.info(f"Retry successful for {context.operation} on {context.file_path.name}")
            return True, result
            
        except Exception as e:
            duration = time.time() - attempt_start
            attempt = RecoveryAttempt(
                timestamp=attempt_start,
                strategy=RecoveryStrategy.RETRY,
                error_type=type(e).__name__,
                error_message=str(e),
                success=False,
                duration=duration,
                details={"retry_delay": wait_time}
            )
            context.recovery_attempts.append(attempt)
            
            self.logger.warning(f"Retry failed for {context.operation}: {e}")
            return False, None
    
    def _apply_fallback_strategy(self, context: ErrorContext) -> Tuple[bool, Any]:
        """Apply fallback strategy with reduced parameters."""
        
        attempt_start = time.time()
        
        try:
            # Create fallback parameters (more conservative settings)
            fallback_params = context.parameters.copy()
            
            # Reduce quality/performance settings
            if "preset" in fallback_params:
                if fallback_params["preset"] == "smallest":
                    fallback_params["preset"] = "balanced"
                elif fallback_params["preset"] == "balanced":
                    fallback_params["preset"] = "archival"
            
            if "jobs" in fallback_params and fallback_params["jobs"] > 1:
                fallback_params["jobs"] = 1  # Single-threaded
            
            if "dpi" in fallback_params and fallback_params["dpi"] > 150:
                fallback_params["dpi"] = 150  # Lower DPI
            
            # Try with fallback parameters
            # Note: This would need to be implemented by the calling function
            # For now, we'll just record the attempt
            
            duration = time.time() - attempt_start
            attempt = RecoveryAttempt(
                timestamp=attempt_start,
                strategy=RecoveryStrategy.FALLBACK,
                error_type=type(context.error).__name__,
                error_message=str(context.error),
                success=False,  # Would be set by actual implementation
                duration=duration,
                details={"fallback_params": fallback_params}
            )
            context.recovery_attempts.append(attempt)
            
            return False, fallback_params  # Return modified params for caller to use
            
        except Exception as e:
            self.logger.error(f"Fallback strategy failed: {e}")
            return False, None
    
    def _apply_safe_mode_strategy(self, context: ErrorContext) -> Tuple[bool, Any]:
        """Apply safe mode strategy with minimal processing."""
        
        attempt_start = time.time()
        
        try:
            # Create safe mode parameters
            safe_params = {
                "preset": "archival",  # Minimal compression
                "jobs": 1,            # Single-threaded
                "dpi": 72,            # Low DPI
                "optimize": False,     # No optimization
                "safe_mode": True     # Flag for safe processing
            }
            
            duration = time.time() - attempt_start
            attempt = RecoveryAttempt(
                timestamp=attempt_start,
                strategy=RecoveryStrategy.SAFE_MODE,
                error_type=type(context.error).__name__,
                error_message=str(context.error),
                success=False,  # Would be set by actual implementation
                duration=duration,
                details={"safe_params": safe_params}
            )
            context.recovery_attempts.append(attempt)
            
            return False, safe_params
            
        except Exception as e:
            self.logger.error(f"Safe mode strategy failed: {e}")
            return False, None
    
    def _apply_partial_recovery_strategy(self, context: ErrorContext) -> Tuple[bool, Any]:
        """Apply partial recovery strategy for corrupted files."""
        
        attempt_start = time.time()
        
        try:
            # Attempt file repair first
            if self._attempt_file_repair(context.file_path):
                duration = time.time() - attempt_start
                attempt = RecoveryAttempt(
                    timestamp=attempt_start,
                    strategy=RecoveryStrategy.PARTIAL_RECOVERY,
                    error_type=type(context.error).__name__,
                    error_message=str(context.error),
                    success=True,
                    duration=duration,
                    details={"repair_method": "ghostscript"}
                )
                context.recovery_attempts.append(attempt)
                
                return True, "file_repaired"
            
            return False, None
            
        except Exception as e:
            self.logger.error(f"Partial recovery strategy failed: {e}")
            return False, None
    
    @contextmanager
    def error_recovery_context(self, operation: str, file_path: Path, 
                              parameters: Dict[str, Any]):
        """Context manager for error recovery operations."""
        
        context = ErrorContext(
            operation=operation,
            file_path=file_path,
            parameters=parameters,
            error=None,
            severity=ErrorSeverity.LOW
        )
        
        # Create backup if needed
        backup_path = None
        if file_path.exists():
            backup_path = self._create_backup(file_path)
        
        try:
            yield context
            
            # Clean up backup on success
            if backup_path and backup_path.exists():
                backup_path.unlink()
                
        except Exception as e:
            context.error = e
            context.severity = self._determine_severity(e)
            
            # Store context in history
            with self._lock:
                if operation not in self.recovery_history:
                    self.recovery_history[operation] = []
                self.recovery_history[operation].append(context)
            
            # Restore backup if available
            if backup_path and backup_path.exists():
                try:
                    if file_path.exists():
                        file_path.unlink()
                    shutil.move(backup_path, file_path)
                    self.logger.info(f"Restored backup for {file_path}")
                except Exception as restore_error:
                    self.logger.error(f"Failed to restore backup: {restore_error}")
            
            raise  # Re-raise the original exception
    
    def attempt_recovery(self, context: ErrorContext, 
                        operation_func: Callable) -> Tuple[bool, Any]:
        """Attempt to recover from an error using appropriate strategies."""
        
        # Find matching rule
        rule = self._find_matching_rule(context.error)
        if not rule:
            self.logger.warning(f"No recovery rule found for error: {context.error}")
            return False, None
        
        # Get next strategy to try
        strategy = rule.get_next_strategy(context)
        if not strategy:
            self.logger.warning(f"All recovery strategies exhausted for {context.operation}")
            return False, None
        
        self.logger.info(f"Attempting recovery with strategy: {strategy.value}")
        
        # Apply strategy
        if strategy == RecoveryStrategy.RETRY:
            return self._apply_retry_strategy(context, operation_func)
        elif strategy == RecoveryStrategy.FALLBACK:
            return self._apply_fallback_strategy(context)
        elif strategy == RecoveryStrategy.SAFE_MODE:
            return self._apply_safe_mode_strategy(context)
        elif strategy == RecoveryStrategy.PARTIAL_RECOVERY:
            return self._apply_partial_recovery_strategy(context)
        else:
            self.logger.warning(f"Strategy {strategy.value} not implemented")
            return False, None
    
    def get_recovery_suggestions(self, error: Exception) -> List[str]:
        """Get user-friendly recovery suggestions for an error."""
        
        suggestions = []
        error_str = str(error).lower()
        
        # File access issues
        if any(term in error_str for term in ["permission", "access denied", "file in use"]):
            suggestions.extend([
                "Close any applications that might be using the PDF file",
                "Check file permissions and ensure you have write access",
                "Try running the application as administrator",
                "Make sure the file is not open in another PDF viewer"
            ])
        
        # Memory issues
        if any(term in error_str for term in ["memory", "out of memory"]):
            suggestions.extend([
                "Try processing smaller files or reduce the number of parallel jobs",
                "Close other applications to free up memory",
                "Use a lower DPI setting for OCR",
                "Consider processing files one at a time"
            ])
        
        # Tool issues
        if any(term in error_str for term in ["ghostscript", "tesseract"]):
            suggestions.extend([
                "Ensure Ghostscript and Tesseract are properly installed",
                "Check that the tools are accessible from the command line",
                "Try reinstalling the PDF processing tools",
                "Verify the system PATH includes the tool directories"
            ])
        
        # File corruption
        if any(term in error_str for term in ["corrupted", "invalid", "malformed"]):
            suggestions.extend([
                "Try opening the file in a PDF viewer to verify it's not corrupted",
                "If the file is corrupted, try to obtain a new copy",
                "Use safe mode processing with minimal optimization",
                "Consider using online PDF repair tools first"
            ])
        
        # Default suggestions
        if not suggestions:
            suggestions.extend([
                "Try using safe mode with conservative settings",
                "Ensure the PDF file is valid and not password-protected",
                "Check available disk space and system resources",
                "Try processing a different file to isolate the issue"
            ])
        
        return suggestions
    
    def get_recovery_history(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get recovery history statistics."""
        
        with self._lock:
            if operation:
                contexts = self.recovery_history.get(operation, [])
            else:
                contexts = []
                for op_contexts in self.recovery_history.values():
                    contexts.extend(op_contexts)
        
        if not contexts:
            return {"total_errors": 0, "recovery_attempts": 0, "success_rate": 0.0}
        
        total_attempts = sum(len(ctx.recovery_attempts) for ctx in contexts)
        successful_attempts = sum(
            1 for ctx in contexts 
            for attempt in ctx.recovery_attempts 
            if attempt.success
        )
        
        return {
            "total_errors": len(contexts),
            "recovery_attempts": total_attempts,
            "successful_recoveries": successful_attempts,
            "success_rate": (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0.0,
            "most_common_errors": self._get_most_common_errors(contexts),
            "most_successful_strategies": self._get_most_successful_strategies(contexts)
        }
    
    def _get_most_common_errors(self, contexts: List[ErrorContext]) -> List[Tuple[str, int]]:
        """Get most common error types."""
        error_counts = {}
        
        for context in contexts:
            error_type = type(context.error).__name__
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        
        return sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    def _get_most_successful_strategies(self, contexts: List[ErrorContext]) -> List[Tuple[str, float]]:
        """Get most successful recovery strategies."""
        strategy_stats = {}
        
        for context in contexts:
            for attempt in context.recovery_attempts:
                strategy = attempt.strategy.value
                if strategy not in strategy_stats:
                    strategy_stats[strategy] = {"total": 0, "successful": 0}
                
                strategy_stats[strategy]["total"] += 1
                if attempt.success:
                    strategy_stats[strategy]["successful"] += 1
        
        # Calculate success rates
        strategy_rates = []
        for strategy, stats in strategy_stats.items():
            success_rate = (stats["successful"] / stats["total"]) * 100
            strategy_rates.append((strategy, success_rate))
        
        return sorted(strategy_rates, key=lambda x: x[1], reverse=True)


# Global recovery manager instance
_global_recovery_manager: Optional[ErrorRecoveryManager] = None


def get_recovery_manager() -> ErrorRecoveryManager:
    """Get the global error recovery manager."""
    global _global_recovery_manager
    if _global_recovery_manager is None:
        _global_recovery_manager = ErrorRecoveryManager()
    return _global_recovery_manager


def with_error_recovery(operation: str, file_path: Path, parameters: Dict[str, Any]):
    """Decorator for operations that should have error recovery."""
    manager = get_recovery_manager()
    return manager.error_recovery_context(operation, file_path, parameters)


def get_error_suggestions(error: Exception) -> List[str]:
    """Get recovery suggestions for an error."""
    manager = get_recovery_manager()
    return manager.get_recovery_suggestions(error)