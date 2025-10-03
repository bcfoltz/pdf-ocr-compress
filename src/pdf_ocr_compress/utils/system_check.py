"""System dependency checking and validation."""

import shutil
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .logging_config import get_logger
from .errors import SystemToolError

logger = get_logger("system_check")


class ToolStatus(Enum):
    """Status of a system tool."""
    AVAILABLE = "available"
    MISSING = "missing"
    VERSION_WARNING = "version_warning"
    ERROR = "error"


@dataclass
class ToolInfo:
    """Information about a system tool."""
    name: str
    status: ToolStatus
    version: Optional[str] = None
    path: Optional[str] = None
    error: Optional[str] = None
    suggestions: List[str] = None

    def __post_init__(self):
        if self.suggestions is None:
            self.suggestions = []


class SystemChecker:
    """System dependency checker with detailed diagnostics."""
    
    def __init__(self):
        """Initialize system checker."""
        self.tool_checks = {
            "tesseract": self._check_tesseract,
            "ghostscript": self._check_ghostscript,
            "ocrmypdf": self._check_ocrmypdf,
            "pikepdf": self._check_pikepdf
        }
        
        # Minimum required versions
        self.min_versions = {
            "tesseract": "4.0.0",
            "ocrmypdf": "15.0.0",
            "pikepdf": "8.0.0"
        }
    
    def check_all_dependencies(self) -> Dict[str, ToolInfo]:
        """
        Check all system dependencies.
        
        Returns:
            Dictionary of tool names to ToolInfo objects
        """
        results = {}
        
        logger.info("Starting system dependency check")
        
        for tool_name, check_func in self.tool_checks.items():
            try:
                results[tool_name] = check_func()
                logger.debug(f"Checked {tool_name}: {results[tool_name].status.value}")
            except Exception as e:
                results[tool_name] = ToolInfo(
                    name=tool_name,
                    status=ToolStatus.ERROR,
                    error=str(e),
                    suggestions=[f"Failed to check {tool_name}: {e}"]
                )
                logger.error(f"Error checking {tool_name}: {e}")
        
        # Log summary
        available_tools = sum(1 for info in results.values() 
                            if info.status == ToolStatus.AVAILABLE)
        total_tools = len(results)
        
        logger.info(f"Dependency check complete: {available_tools}/{total_tools} tools available")
        
        return results
    
    def _check_tesseract(self) -> ToolInfo:
        """Check Tesseract OCR availability and version."""
        tool_name = "tesseract"
        
        # Check if tesseract is in PATH
        tesseract_path = shutil.which(tool_name)
        if not tesseract_path:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.MISSING,
                suggestions=self._get_install_suggestions(tool_name)
            )
        
        try:
            # Get version
            result = subprocess.run(
                [tesseract_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            version_line = result.stderr.split('\n')[0] if result.stderr else ""
            version = self._extract_version(version_line)
            
            # Check version
            status = ToolStatus.AVAILABLE
            suggestions = []
            
            if version and self._compare_versions(version, self.min_versions.get(tool_name, "0.0.0")) < 0:
                status = ToolStatus.VERSION_WARNING
                suggestions.append(f"Version {version} found, but {self.min_versions[tool_name]}+ recommended")
            
            return ToolInfo(
                name=tool_name,
                status=status,
                version=version,
                path=tesseract_path,
                suggestions=suggestions
            )
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.ERROR,
                path=tesseract_path,
                error=str(e),
                suggestions=self._get_install_suggestions(tool_name)
            )
    
    def _check_ghostscript(self) -> ToolInfo:
        """Check Ghostscript availability and version."""
        tool_name = "ghostscript"
        
        # Try different executable names based on platform
        gs_names = ["gswin64c", "gswin32c", "gs"] if sys.platform == "win32" else ["gs"]
        
        for gs_name in gs_names:
            gs_path = shutil.which(gs_name)
            if gs_path:
                break
        else:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.MISSING,
                suggestions=self._get_install_suggestions(tool_name)
            )
        
        try:
            # Get version
            result = subprocess.run(
                [gs_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            version = result.stdout.strip() if result.stdout else None
            
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.AVAILABLE,
                version=version,
                path=gs_path
            )
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.ERROR,
                path=gs_path,
                error=str(e),
                suggestions=self._get_install_suggestions(tool_name)
            )
    
    def _check_ocrmypdf(self) -> ToolInfo:
        """Check OCRmyPDF availability and version."""
        tool_name = "ocrmypdf"
        
        try:
            import ocrmypdf
            
            # Get version
            version = getattr(ocrmypdf, "__version__", None)
            
            # Check if command line tool is available
            ocrmypdf_path = shutil.which("ocrmypdf")
            
            status = ToolStatus.AVAILABLE
            suggestions = []
            
            if version and self._compare_versions(version, self.min_versions.get(tool_name, "0.0.0")) < 0:
                status = ToolStatus.VERSION_WARNING
                suggestions.append(f"Version {version} found, but {self.min_versions[tool_name]}+ recommended")
            
            return ToolInfo(
                name=tool_name,
                status=status,
                version=version,
                path=ocrmypdf_path,
                suggestions=suggestions
            )
            
        except ImportError:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.MISSING,
                suggestions=[
                    "Install OCRmyPDF: pip install ocrmypdf",
                    "Or using uv: uv add ocrmypdf",
                    "Ensure all system dependencies (tesseract, ghostscript) are installed first"
                ]
            )
    
    def _check_pikepdf(self) -> ToolInfo:
        """Check pikepdf availability and version."""
        tool_name = "pikepdf"
        
        try:
            import pikepdf
            
            version = getattr(pikepdf, "__version__", None)
            
            status = ToolStatus.AVAILABLE
            suggestions = []
            
            if version and self._compare_versions(version, self.min_versions.get(tool_name, "0.0.0")) < 0:
                status = ToolStatus.VERSION_WARNING
                suggestions.append(f"Version {version} found, but {self.min_versions[tool_name]}+ recommended")
            
            return ToolInfo(
                name=tool_name,
                status=status,
                version=version,
                suggestions=suggestions
            )
            
        except ImportError:
            return ToolInfo(
                name=tool_name,
                status=ToolStatus.MISSING,
                suggestions=[
                    "Install pikepdf: pip install pikepdf",
                    "Or using uv: uv add pikepdf"
                ]
            )
    
    def _get_install_suggestions(self, tool_name: str) -> List[str]:
        """Get installation suggestions for a specific tool."""
        suggestions = {
            "tesseract": [
                "Run the provided installation script for your platform:",
                "  Windows: .\\scripts\\install_windows.ps1 (as Administrator)",
                "  macOS: bash scripts/install_macos.sh",  
                "  Linux: bash scripts/install_linux.sh",
                "Or install manually:",
                "  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki",
                "  macOS: brew install tesseract",
                "  Linux: apt install tesseract-ocr (Ubuntu/Debian) or yum install tesseract (CentOS/RHEL)"
            ],
            "ghostscript": [
                "Run the provided installation script for your platform",
                "Or install manually:",
                "  Windows: Download from https://www.ghostscript.com/download/gsdnld.html", 
                "  macOS: brew install ghostscript",
                "  Linux: apt install ghostscript (Ubuntu/Debian) or yum install ghostscript (CentOS/RHEL)"
            ],
            "ocrmypdf": [
                "Install via pip: pip install ocrmypdf>=15.0.0",
                "Or using uv: uv add ocrmypdf",
                "Ensure system dependencies (tesseract, ghostscript) are installed first"
            ],
            "pikepdf": [
                "Install via pip: pip install pikepdf>=8.0.0",
                "Or using uv: uv add pikepdf"
            ]
        }
        
        return suggestions.get(tool_name, [f"Install {tool_name} and ensure it's in your system PATH"])
    
    def _extract_version(self, version_string: str) -> Optional[str]:
        """Extract version number from version string."""
        import re
        
        # Look for version patterns like "4.1.1", "v4.1.1", etc.
        version_pattern = r'(?:version\s+)?v?(\d+\.\d+(?:\.\d+)?)'
        match = re.search(version_pattern, version_string, re.IGNORECASE)
        
        return match.group(1) if match else None
    
    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two version strings.
        
        Returns:
            -1 if version1 < version2
            0 if version1 == version2  
            1 if version1 > version2
        """
        def version_tuple(v):
            return tuple(map(int, v.split('.')))
        
        try:
            v1_tuple = version_tuple(version1)
            v2_tuple = version_tuple(version2)
            
            if v1_tuple < v2_tuple:
                return -1
            elif v1_tuple > v2_tuple:
                return 1
            else:
                return 0
        except (ValueError, AttributeError):
            # If version comparison fails, assume they're equal
            return 0
    
    def get_health_report(self) -> Dict[str, any]:
        """
        Get a comprehensive system health report.
        
        Returns:
            Dictionary with system health information
        """
        tools = self.check_all_dependencies()
        
        # Count tools by status
        status_counts = {}
        for status in ToolStatus:
            status_counts[status.value] = sum(
                1 for tool in tools.values() 
                if tool.status == status
            )
        
        # Check system resources
        try:
            import psutil
            memory_info = {
                "total_gb": psutil.virtual_memory().total / (1024**3),
                "available_gb": psutil.virtual_memory().available / (1024**3),
                "usage_percent": psutil.virtual_memory().percent
            }
            disk_info = {
                "total_gb": psutil.disk_usage('/').total / (1024**3),
                "free_gb": psutil.disk_usage('/').free / (1024**3),
                "usage_percent": psutil.disk_usage('/').percent
            }
        except ImportError:
            memory_info = {"error": "psutil not available"}
            disk_info = {"error": "psutil not available"}
        
        return {
            "tools": {name: {
                "status": tool.status.value,
                "version": tool.version,
                "path": tool.path,
                "error": tool.error,
                "suggestions": tool.suggestions
            } for name, tool in tools.items()},
            "status_summary": status_counts,
            "system_info": {
                "platform": sys.platform,
                "python_version": sys.version,
                "cpu_count": os.cpu_count(),
                "memory": memory_info,
                "disk": disk_info
            },
            "ready_for_processing": status_counts.get("available", 0) >= 2,  # Need at least tesseract + ghostscript
            "warnings": [
                tool.error or f"{tool.name} has issues" 
                for tool in tools.values() 
                if tool.status in [ToolStatus.ERROR, ToolStatus.VERSION_WARNING]
            ]
        }


# Global system checker instance
_system_checker: Optional[SystemChecker] = None

def get_system_checker() -> SystemChecker:
    """Get global system checker instance."""
    global _system_checker
    if _system_checker is None:
        _system_checker = SystemChecker()
    return _system_checker

def check_system_ready() -> Tuple[bool, List[str]]:
    """
    Check if system is ready for PDF processing.
    
    Returns:
        (is_ready, list_of_issues)
    """
    checker = get_system_checker()
    tools = checker.check_all_dependencies()
    
    # Check critical tools
    critical_tools = ["tesseract", "ghostscript"]
    issues = []
    
    for tool_name in critical_tools:
        tool_info = tools.get(tool_name)
        if not tool_info or tool_info.status != ToolStatus.AVAILABLE:
            if tool_info:
                issues.append(f"{tool_name.title()} is not available: {tool_info.error or 'Not found'}")
            else:
                issues.append(f"{tool_name.title()} check failed")
    
    # Check Python dependencies
    python_deps = ["ocrmypdf", "pikepdf"]
    for dep_name in python_deps:
        dep_info = tools.get(dep_name)
        if not dep_info or dep_info.status == ToolStatus.MISSING:
            issues.append(f"Python package '{dep_name}' is not installed")
    
    is_ready = len(issues) == 0
    return is_ready, issues

def validate_processing_environment() -> None:
    """
    Validate that the environment is ready for processing.
    Raises SystemToolError if critical dependencies are missing.
    """
    is_ready, issues = check_system_ready()
    
    if not is_ready:
        error_msg = "System is not ready for PDF processing:\n" + "\n".join(f"- {issue}" for issue in issues)
        
        # Get installation suggestions
        checker = get_system_checker()
        tools = checker.check_all_dependencies()
        
        all_suggestions = []
        for tool_info in tools.values():
            if tool_info.status != ToolStatus.AVAILABLE and tool_info.suggestions:
                all_suggestions.extend(tool_info.suggestions)
        
        raise SystemToolError(
            "system",
            error_msg,
            all_suggestions[:10]  # Limit to first 10 suggestions
        )