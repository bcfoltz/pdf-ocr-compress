"""Secure temporary file management with automatic cleanup."""

import tempfile
import shutil
import atexit
import weakref
from pathlib import Path
from typing import Set, Optional, Generator
from contextlib import contextmanager
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from .logging_config import get_logger

logger = get_logger("temp_manager")


@dataclass
class TempFileInfo:
    """Information about a temporary file or directory."""
    path: Path
    created_at: datetime
    cleanup_on_exit: bool = True
    secure: bool = True


class SecureTempManager:
    """Secure temporary file manager with automatic cleanup."""
    
    def __init__(self, base_dir: Optional[Path] = None, 
                 max_age_hours: int = 24, cleanup_on_exit: bool = True):
        """
        Initialize secure temp manager.
        
        Args:
            base_dir: Base directory for temp files (None = system temp)
            max_age_hours: Maximum age for temp files before cleanup
            cleanup_on_exit: Whether to cleanup on application exit
        """
        self.base_dir = Path(base_dir) if base_dir else None
        self.max_age = timedelta(hours=max_age_hours)
        self.cleanup_on_exit = cleanup_on_exit
        
        # Track active temp files/directories
        self._temp_items: Set[TempFileInfo] = set()
        self._lock = threading.Lock()
        
        # Register cleanup on exit
        if cleanup_on_exit:
            atexit.register(self.cleanup_all)
            
        # Create base directory if specified
        if self.base_dir:
            self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    def create_temp_file(self, suffix: str = "", prefix: str = "pdf_ocr_", 
                        secure: bool = True, cleanup_on_exit: bool = True) -> Path:
        """
        Create a temporary file with secure permissions.
        
        Args:
            suffix: File suffix/extension
            prefix: File prefix
            secure: Whether to set secure permissions (600)
            cleanup_on_exit: Whether to cleanup on app exit
            
        Returns:
            Path to created temporary file
        """
        temp_dir = self.base_dir or Path(tempfile.gettempdir())
        
        # Create temporary file
        fd, temp_path = tempfile.mkstemp(
            suffix=suffix,
            prefix=prefix,
            dir=temp_dir
        )
        
        temp_path = Path(temp_path)
        
        try:
            # Close the file descriptor (we just want the path)
            import os
            os.close(fd)
            
            # Set secure permissions if requested
            if secure:
                temp_path.chmod(0o600)  # Owner read/write only
            
            # Track the temp file
            temp_info = TempFileInfo(
                path=temp_path,
                created_at=datetime.now(),
                cleanup_on_exit=cleanup_on_exit,
                secure=secure
            )
            
            with self._lock:
                self._temp_items.add(temp_info)
            
            logger.debug(f"Created temporary file: {temp_path}")
            return temp_path
            
        except Exception:
            # Cleanup on failure
            if temp_path.exists():
                temp_path.unlink()
            raise
    
    def create_temp_dir(self, suffix: str = "", prefix: str = "pdf_ocr_",
                       secure: bool = True, cleanup_on_exit: bool = True) -> Path:
        """
        Create a temporary directory with secure permissions.
        
        Args:
            suffix: Directory suffix
            prefix: Directory prefix  
            secure: Whether to set secure permissions (700)
            cleanup_on_exit: Whether to cleanup on app exit
            
        Returns:
            Path to created temporary directory
        """
        temp_parent = self.base_dir or Path(tempfile.gettempdir())
        
        # Create temporary directory
        temp_dir = Path(tempfile.mkdtemp(
            suffix=suffix,
            prefix=prefix,
            dir=temp_parent
        ))
        
        try:
            # Set secure permissions if requested
            if secure:
                temp_dir.chmod(0o700)  # Owner read/write/execute only
            
            # Track the temp directory
            temp_info = TempFileInfo(
                path=temp_dir,
                created_at=datetime.now(),
                cleanup_on_exit=cleanup_on_exit,
                secure=secure
            )
            
            with self._lock:
                self._temp_items.add(temp_info)
            
            logger.debug(f"Created temporary directory: {temp_dir}")
            return temp_dir
            
        except Exception:
            # Cleanup on failure
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise
    
    @contextmanager
    def temp_file(self, suffix: str = "", prefix: str = "pdf_ocr_",
                 secure: bool = True) -> Generator[Path, None, None]:
        """
        Context manager for temporary files with guaranteed cleanup.
        
        Args:
            suffix: File suffix/extension
            prefix: File prefix
            secure: Whether to set secure permissions
            
        Yields:
            Path to temporary file
        """
        temp_path = self.create_temp_file(
            suffix=suffix, 
            prefix=prefix, 
            secure=secure,
            cleanup_on_exit=False  # We'll cleanup manually
        )
        
        try:
            yield temp_path
        finally:
            self.cleanup_item(temp_path)
    
    @contextmanager
    def temp_dir(self, suffix: str = "", prefix: str = "pdf_ocr_",
                secure: bool = True) -> Generator[Path, None, None]:
        """
        Context manager for temporary directories with guaranteed cleanup.
        
        Args:
            suffix: Directory suffix
            prefix: Directory prefix
            secure: Whether to set secure permissions
            
        Yields:
            Path to temporary directory
        """
        temp_path = self.create_temp_dir(
            suffix=suffix,
            prefix=prefix, 
            secure=secure,
            cleanup_on_exit=False  # We'll cleanup manually
        )
        
        try:
            yield temp_path
        finally:
            self.cleanup_item(temp_path)
    
    def cleanup_item(self, path: Path) -> bool:
        """
        Clean up a specific temporary item.
        
        Args:
            path: Path to clean up
            
        Returns:
            True if cleanup was successful
        """
        try:
            # Find and remove from tracking
            with self._lock:
                temp_info = next((item for item in self._temp_items 
                                if item.path == path), None)
                if temp_info:
                    self._temp_items.remove(temp_info)
            
            # Remove from filesystem
            if path.exists():
                if path.is_file():
                    # Securely delete file (overwrite with zeros first)
                    if temp_info and temp_info.secure:
                        self._secure_delete_file(path)
                    else:
                        path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                
                logger.debug(f"Cleaned up temporary item: {path}")
                return True
            
        except Exception as e:
            logger.warning(f"Failed to cleanup {path}: {e}")
            return False
        
        return True
    
    def cleanup_old_items(self, max_age: Optional[timedelta] = None) -> int:
        """
        Clean up temporary items older than max_age.
        
        Args:
            max_age: Maximum age (None = use instance default)
            
        Returns:
            Number of items cleaned up
        """
        if max_age is None:
            max_age = self.max_age
        
        cutoff_time = datetime.now() - max_age
        cleaned_count = 0
        
        with self._lock:
            old_items = [item for item in self._temp_items 
                        if item.created_at < cutoff_time]
        
        for item in old_items:
            if self.cleanup_item(item.path):
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old temporary items")
        
        return cleaned_count
    
    def cleanup_all(self) -> int:
        """
        Clean up all tracked temporary items.
        
        Returns:
            Number of items cleaned up
        """
        with self._lock:
            items_to_cleanup = list(self._temp_items)
        
        cleaned_count = 0
        for item in items_to_cleanup:
            if item.cleanup_on_exit and self.cleanup_item(item.path):
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} temporary items on shutdown")
        
        return cleaned_count
    
    def get_temp_usage(self) -> dict:
        """
        Get information about current temporary file usage.
        
        Returns:
            Dictionary with usage statistics
        """
        with self._lock:
            total_size = 0
            file_count = 0
            dir_count = 0
            
            for item in self._temp_items:
                if not item.path.exists():
                    continue
                    
                if item.path.is_file():
                    file_count += 1
                    total_size += item.path.stat().st_size
                elif item.path.is_dir():
                    dir_count += 1
                    # Calculate directory size
                    for file_path in item.path.rglob('*'):
                        if file_path.is_file():
                            total_size += file_path.stat().st_size
        
        return {
            "total_items": len(self._temp_items),
            "file_count": file_count,
            "directory_count": dir_count,
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024)
        }
    
    def _secure_delete_file(self, path: Path):
        """
        Securely delete a file by overwriting with zeros.
        
        Args:
            path: Path to file to delete
        """
        try:
            # Get file size
            file_size = path.stat().st_size
            
            # Overwrite with zeros
            with open(path, "r+b") as f:
                f.write(b'\x00' * file_size)
                f.flush()
            
            # Remove the file
            path.unlink()
            
        except Exception as e:
            logger.warning(f"Secure delete failed for {path}, falling back to normal delete: {e}")
            # Fallback to normal deletion
            if path.exists():
                path.unlink()


# Global temp manager instance
_temp_manager: Optional[SecureTempManager] = None

def get_temp_manager() -> SecureTempManager:
    """Get global temporary file manager instance."""
    global _temp_manager
    if _temp_manager is None:
        _temp_manager = SecureTempManager()
    return _temp_manager

# Convenience functions
def create_temp_file(suffix: str = "", prefix: str = "pdf_ocr_") -> Path:
    """Create a temporary file using the global temp manager."""
    return get_temp_manager().create_temp_file(suffix=suffix, prefix=prefix)

def create_temp_dir(suffix: str = "", prefix: str = "pdf_ocr_") -> Path:
    """Create a temporary directory using the global temp manager.""" 
    return get_temp_manager().create_temp_dir(suffix=suffix, prefix=prefix)

@contextmanager
def temp_file(suffix: str = "", prefix: str = "pdf_ocr_") -> Generator[Path, None, None]:
    """Context manager for temporary files."""
    with get_temp_manager().temp_file(suffix=suffix, prefix=prefix) as path:
        yield path

@contextmanager  
def temp_dir(suffix: str = "", prefix: str = "pdf_ocr_") -> Generator[Path, None, None]:
    """Context manager for temporary directories."""
    with get_temp_manager().temp_dir(suffix=suffix, prefix=prefix) as path:
        yield path