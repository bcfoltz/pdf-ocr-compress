"""Batch processing module for handling multiple PDF files."""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import json

from ..utils import (
    get_logger, 
    get_performance_logger, 
    PDFProcessingError,
    human_readable_size,
    unique_output_path
)
from ..config import get_config
from .async_processor import AsyncProcessor, ProcessingJob, get_async_processor


class BatchOperation(Enum):
    OCR_ONLY = "ocr_only"
    COMPRESS_ONLY = "compress_only" 
    OCR_AND_COMPRESS = "ocr_and_compress"
    AUTO_PROCESS = "auto_process"


@dataclass
class BatchFile:
    """Individual file in a batch operation."""
    input_path: Path
    output_path: Optional[Path] = None
    operation: BatchOperation = BatchOperation.AUTO_PROCESS
    params: Dict[str, Any] = field(default_factory=dict)
    size: Optional[int] = None
    
    def __post_init__(self):
        if self.size is None and self.input_path.exists():
            self.size = self.input_path.stat().st_size
        
        if self.output_path is None:
            # Generate output path based on operation
            suffix_map = {
                BatchOperation.OCR_ONLY: "ocr",
                BatchOperation.COMPRESS_ONLY: "compressed", 
                BatchOperation.OCR_AND_COMPRESS: "processed",
                BatchOperation.AUTO_PROCESS: "processed"
            }
            suffix = suffix_map[self.operation]
            self.output_path = unique_output_path(
                self.input_path, 
                suffix=suffix
            )
    
    @property
    def size_human(self) -> str:
        """Get human-readable file size."""
        return human_readable_size(self.size) if self.size else "Unknown"


@dataclass
class BatchProgress:
    """Progress tracking for batch operations."""
    total_files: int
    completed_files: int = 0
    failed_files: int = 0
    current_file: Optional[str] = None
    current_progress: float = 0.0
    start_time: Optional[float] = None
    estimated_completion: Optional[float] = None
    
    @property
    def overall_progress(self) -> float:
        """Get overall batch progress percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.completed_files + self.current_progress / 100) / self.total_files * 100
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Get estimated time to completion in seconds."""
        if not self.start_time or self.completed_files == 0:
            return None
        
        elapsed = time.time() - self.start_time
        rate = self.completed_files / elapsed
        remaining_files = self.total_files - self.completed_files
        
        if rate > 0:
            return remaining_files / rate
        return None
    
    @property
    def eta_human(self) -> str:
        """Get human-readable ETA."""
        eta = self.eta_seconds
        if eta is None:
            return "Calculating..."
        
        if eta < 60:
            return f"{eta:.0f}s"
        elif eta < 3600:
            return f"{eta/60:.0f}m {eta%60:.0f}s"
        else:
            hours = eta // 3600
            minutes = (eta % 3600) // 60
            return f"{hours:.0f}h {minutes:.0f}m"


@dataclass
class BatchResult:
    """Results from a batch processing operation."""
    total_files: int
    successful_files: List[Tuple[Path, Path]] = field(default_factory=list)
    failed_files: List[Tuple[Path, str]] = field(default_factory=list)
    skipped_files: List[Tuple[Path, str]] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    @property
    def success_count(self) -> int:
        return len(self.successful_files)
    
    @property
    def failure_count(self) -> int:
        return len(self.failed_files)
    
    @property
    def skip_count(self) -> int:
        return len(self.skipped_files)
    
    @property
    def success_rate(self) -> float:
        if self.total_files == 0:
            return 0.0
        return self.success_count / self.total_files * 100
    
    @property
    def total_duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


class BatchProcessor:
    """Batch processor for handling multiple PDF operations."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.perf_logger = get_performance_logger()
        self.config = get_config()
        self.async_processor = get_async_processor()
        
    def create_batch_from_files(
        self,
        file_paths: List[Path],
        operation: BatchOperation = BatchOperation.AUTO_PROCESS,
        output_dir: Optional[Path] = None,
        common_params: Optional[Dict[str, Any]] = None
    ) -> List[BatchFile]:
        """Create batch files from a list of input paths."""
        batch_files = []
        common_params = common_params or {}
        
        for input_path in file_paths:
            if not input_path.exists():
                self.logger.warning(f"Input file does not exist: {input_path}")
                continue
            
            if not input_path.suffix.lower() == '.pdf':
                self.logger.warning(f"Skipping non-PDF file: {input_path}")
                continue
            
            # Generate output path
            if output_dir:
                output_path = output_dir / f"{input_path.stem}_processed.pdf"
                output_path = unique_output_path(output_path)
            else:
                output_path = None  # Will be generated by BatchFile
            
            batch_file = BatchFile(
                input_path=input_path,
                output_path=output_path,
                operation=operation,
                params=common_params.copy()
            )
            
            batch_files.append(batch_file)
        
        return batch_files
    
    def validate_batch(self, batch_files: List[BatchFile]) -> Tuple[List[BatchFile], List[str]]:
        """Validate batch files and return valid files + error messages."""
        valid_files = []
        errors = []
        
        for batch_file in batch_files:
            # Check input file exists and is readable
            if not batch_file.input_path.exists():
                errors.append(f"Input file does not exist: {batch_file.input_path}")
                continue
            
            if not batch_file.input_path.is_file():
                errors.append(f"Input path is not a file: {batch_file.input_path}")
                continue
            
            # Check output directory is writable
            try:
                batch_file.output_path.parent.mkdir(parents=True, exist_ok=True)
                # Test write access
                test_file = batch_file.output_path.parent / ".write_test"
                test_file.touch()
                test_file.unlink()
            except Exception as e:
                errors.append(f"Cannot write to output directory {batch_file.output_path.parent}: {e}")
                continue
            
            # Check file size constraints
            max_size = 500 * 1024 * 1024  # 500MB limit for batch processing
            if batch_file.size and batch_file.size > max_size:
                errors.append(f"File too large for batch processing: {batch_file.input_path} ({batch_file.size_human})")
                continue
            
            valid_files.append(batch_file)
        
        return valid_files, errors
    
    async def process_batch(
        self,
        batch_files: List[BatchFile],
        processor_funcs: Dict[str, Callable],
        progress_callback: Optional[Callable[[BatchProgress], None]] = None,
        max_concurrent: int = 2
    ) -> BatchResult:
        """Process a batch of files with progress tracking."""
        
        # Validate batch
        valid_files, errors = self.validate_batch(batch_files)
        
        if errors:
            self.logger.warning(f"Batch validation found {len(errors)} errors")
        
        if not valid_files:
            raise PDFProcessingError("No valid files in batch")
        
        # Initialize results
        result = BatchResult(
            total_files=len(valid_files),
            start_time=time.time()
        )
        
        # Initialize progress
        progress = BatchProgress(
            total_files=len(valid_files),
            start_time=time.time()
        )
        
        # Group files by operation type for efficient processing
        operation_groups = {}
        for batch_file in valid_files:
            op_key = batch_file.operation.value
            if op_key not in operation_groups:
                operation_groups[op_key] = []
            operation_groups[op_key].append(batch_file)
        
        self.logger.info(f"Starting batch processing of {len(valid_files)} files", extra={
            "extra_data": {
                "total_files": len(valid_files),
                "operations": {op: len(files) for op, files in operation_groups.items()}
            }
        })
        
        # Process each operation group
        for operation, files in operation_groups.items():
            await self._process_operation_group(
                files, 
                operation,
                processor_funcs,
                result,
                progress,
                progress_callback,
                max_concurrent
            )
        
        result.end_time = time.time()
        
        self.perf_logger.log_batch_complete(
            total_files=result.total_files,
            successful_files=result.success_count,
            failed_files=result.failure_count,
            duration=result.total_duration,
            success_rate=result.success_rate
        )
        
        return result
    
    async def _process_operation_group(
        self,
        files: List[BatchFile],
        operation: str,
        processor_funcs: Dict[str, Callable],
        result: BatchResult,
        progress: BatchProgress,
        progress_callback: Optional[Callable[[BatchProgress], None]],
        max_concurrent: int
    ):
        """Process a group of files with the same operation."""
        
        if operation not in processor_funcs:
            for batch_file in files:
                result.failed_files.append((batch_file.input_path, f"Unknown operation: {operation}"))
            return
        
        # Process files in chunks to limit concurrency
        for i in range(0, len(files), max_concurrent):
            chunk = files[i:i + max_concurrent]
            
            # Submit jobs for this chunk
            job_ids = []
            for batch_file in chunk:
                progress.current_file = batch_file.input_path.name
                
                def file_progress_callback(file_progress: float, message: str = ""):
                    progress.current_progress = file_progress
                    if progress_callback:
                        progress_callback(progress)
                
                job_id = self.async_processor.submit_job(
                    operation=operation,
                    input_path=batch_file.input_path,
                    output_path=batch_file.output_path,
                    processor_func=processor_funcs[operation],
                    params=batch_file.params,
                    progress_callback=file_progress_callback
                )
                job_ids.append((job_id, batch_file))
            
            # Wait for chunk completion
            while True:
                completed_jobs = []
                
                for job_id, batch_file in job_ids:
                    job = self.async_processor.get_job_status(job_id)
                    
                    if job.status.value == "completed":
                        result.successful_files.append((batch_file.input_path, job.result))
                        progress.completed_files += 1
                        completed_jobs.append((job_id, batch_file))
                        
                    elif job.status.value == "failed":
                        result.failed_files.append((batch_file.input_path, job.error))
                        progress.failed_files += 1
                        progress.completed_files += 1
                        completed_jobs.append((job_id, batch_file))
                
                # Remove completed jobs
                for completed_job in completed_jobs:
                    job_ids.remove(completed_job)
                
                if not job_ids:  # All jobs in chunk completed
                    break
                
                if progress_callback:
                    progress_callback(progress)
                
                await asyncio.sleep(0.5)
    
    def save_batch_report(
        self, 
        result: BatchResult, 
        output_path: Path,
        include_details: bool = True
    ) -> None:
        """Save batch processing report to file."""
        
        report = {
            "summary": {
                "total_files": result.total_files,
                "successful_files": result.success_count,
                "failed_files": result.failure_count,
                "skipped_files": result.skip_count,
                "success_rate": result.success_rate,
                "total_duration": result.total_duration,
                "timestamp": time.time()
            }
        }
        
        if include_details:
            report["details"] = {
                "successful_files": [
                    {"input": str(input_path), "output": str(output_path)}
                    for input_path, output_path in result.successful_files
                ],
                "failed_files": [
                    {"input": str(input_path), "error": error}
                    for input_path, error in result.failed_files
                ],
                "skipped_files": [
                    {"input": str(input_path), "reason": reason}
                    for input_path, reason in result.skipped_files
                ]
            }
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)
            
            self.logger.info(f"Batch report saved to {output_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save batch report: {e}")
            raise PDFProcessingError(f"Failed to save batch report: {e}")


# Global batch processor instance
_global_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor() -> BatchProcessor:
    """Get the global batch processor instance."""
    global _global_batch_processor
    if _global_batch_processor is None:
        _global_batch_processor = BatchProcessor()
    return _global_batch_processor