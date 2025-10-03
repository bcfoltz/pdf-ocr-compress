"""Advanced compression options and custom profiles for PDF processing."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field
from enum import Enum

from ..utils import get_logger
from ..config import get_config


class CompressionType(Enum):
    """Types of compression to apply."""
    LOSSLESS = "lossless"
    LOSSY_LOW = "lossy_low"
    LOSSY_MEDIUM = "lossy_medium"
    LOSSY_HIGH = "lossy_high"
    AGGRESSIVE = "aggressive"


class ImageOptimization(Enum):
    """Image optimization strategies."""
    NONE = "none"
    BASIC = "basic"
    PHOTOS = "photos"
    DIAGRAMS = "diagrams"
    MIXED = "mixed"
    CUSTOM = "custom"


@dataclass
class ImageSettings:
    """Image-specific compression settings."""
    optimization: ImageOptimization = ImageOptimization.BASIC
    jpeg_quality: int = 85
    png_quality: int = 9
    downsample_threshold: int = 300  # DPI
    downsample_target: int = 150  # DPI
    color_image_downsample: bool = True
    grayscale_image_downsample: bool = True
    mono_image_downsample: bool = False
    remove_duplicate_images: bool = True
    convert_color_to_gray: bool = False
    
    def validate(self) -> bool:
        """Validate image settings."""
        return (
            0 <= self.jpeg_quality <= 100 and
            0 <= self.png_quality <= 9 and
            50 <= self.downsample_threshold <= 2400 and
            50 <= self.downsample_target <= 600 and
            self.downsample_target <= self.downsample_threshold
        )


@dataclass
class FontSettings:
    """Font and text compression settings."""
    subset_fonts: bool = True
    embed_fonts: bool = True
    convert_to_outlines: bool = False
    optimize_font_streams: bool = True
    remove_unused_fonts: bool = True
    compress_font_streams: bool = True


@dataclass
class ContentSettings:
    """Content optimization settings."""
    remove_metadata: bool = False
    remove_bookmarks: bool = False
    remove_annotations: bool = False
    remove_form_fields: bool = False
    remove_javascript: bool = True
    remove_embedded_files: bool = False
    flatten_transparency: bool = False
    optimize_page_content: bool = True


@dataclass
class CompressionProfile:
    """Complete compression profile with all settings."""
    name: str
    description: str
    compression_type: CompressionType
    target_size_reduction: float  # Target percentage reduction (0-100)
    
    # Ghostscript settings
    compatibility_level: str = "1.7"  # PDF version
    color_conversion_strategy: str = "LeaveColorUnchanged"
    compress_pages: bool = True
    optimize_for: str = "ebook"  # ebook, print, prepress, screen, default
    
    # Advanced settings
    image_settings: ImageSettings = field(default_factory=ImageSettings)
    font_settings: FontSettings = field(default_factory=FontSettings)
    content_settings: ContentSettings = field(default_factory=ContentSettings)
    
    # Custom Ghostscript parameters
    custom_gs_params: Dict[str, Any] = field(default_factory=dict)
    
    # Performance settings
    preserve_pdf_a: bool = False
    linearize: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompressionProfile':
        """Create from dictionary."""
        # Convert enums
        if 'compression_type' in data:
            data['compression_type'] = CompressionType(data['compression_type'])
        
        if 'image_settings' in data:
            img_data = data['image_settings']
            if 'optimization' in img_data:
                img_data['optimization'] = ImageOptimization(img_data['optimization'])
            data['image_settings'] = ImageSettings(**img_data)
        
        if 'font_settings' in data:
            data['font_settings'] = FontSettings(**data['font_settings'])
        
        if 'content_settings' in data:
            data['content_settings'] = ContentSettings(**data['content_settings'])
        
        return cls(**data)
    
    def get_ghostscript_params(self) -> Dict[str, Any]:
        """Generate Ghostscript parameters from profile settings."""
        params = {
            # Basic settings
            "-sDEVICE": "pdfwrite",
            "-dCompatibilityLevel": self.compatibility_level,
            "-dPDFSETTINGS": f"/{self.optimize_for}",
            "-dCompressPages": "true" if self.compress_pages else "false",
            "-dOptimize": "true",
        }
        
        # Color settings
        params["-sColorConversionStrategy"] = self.color_conversion_strategy
        
        # Image settings
        img = self.image_settings
        if img.color_image_downsample:
            params.update({
                "-dDownsampleColorImages": "true",
                "-dColorImageResolution": str(img.downsample_target),
                "-dColorImageDownsampleThreshold": str(img.downsample_threshold / img.downsample_target),
            })
        
        if img.grayscale_image_downsample:
            params.update({
                "-dDownsampleGrayImages": "true",
                "-dGrayImageResolution": str(img.downsample_target),
                "-dGrayImageDownsampleThreshold": str(img.downsample_threshold / img.downsample_target),
            })
        
        if img.mono_image_downsample:
            params.update({
                "-dDownsampleMonoImages": "true",
                "-dMonoImageResolution": str(img.downsample_target),
                "-dMonoImageDownsampleThreshold": str(img.downsample_threshold / img.downsample_target),
            })
        
        # JPEG quality
        if img.optimization != ImageOptimization.NONE:
            params["-dJPEGQ"] = str(img.jpeg_quality)
        
        # Font settings
        font = self.font_settings
        params.update({
            "-dSubsetFonts": "true" if font.subset_fonts else "false",
            "-dEmbedAllFonts": "true" if font.embed_fonts else "false",
        })
        
        # Content optimization
        content = self.content_settings
        if content.remove_metadata:
            params["-dPreserveMarkedContent"] = "false"
        
        # Linearization
        if self.linearize:
            params["-dLinearize"] = "true"
        
        # Custom parameters override defaults
        params.update(self.custom_gs_params)
        
        return params
    
    def estimate_size_reduction(self, file_size: int) -> int:
        """Estimate resulting file size after compression."""
        reduction_factor = self.target_size_reduction / 100
        estimated_reduction = file_size * reduction_factor
        
        # Apply compression type modifiers
        type_modifiers = {
            CompressionType.LOSSLESS: 0.8,
            CompressionType.LOSSY_LOW: 1.0,
            CompressionType.LOSSY_MEDIUM: 1.2,
            CompressionType.LOSSY_HIGH: 1.5,
            CompressionType.AGGRESSIVE: 2.0,
        }
        
        modifier = type_modifiers.get(self.compression_type, 1.0)
        estimated_reduction *= modifier
        
        return max(file_size - int(estimated_reduction), file_size // 10)  # At least 10% of original


class CompressionProfileManager:
    """Manages compression profiles and presets."""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.config = get_config()
        
        # Profile storage
        self.profiles_dir = self.config.get_config_dir() / "compression_profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        
        self.profiles_file = self.profiles_dir / "profiles.json"
        
        # Initialize with built-in profiles
        self._profiles: Dict[str, CompressionProfile] = {}
        self._load_builtin_profiles()
        self._load_user_profiles()
    
    def _load_builtin_profiles(self):
        """Load built-in compression profiles."""
        
        # Archival - minimal compression, maximum quality
        archival = CompressionProfile(
            name="archival",
            description="Minimal compression preserving maximum quality",
            compression_type=CompressionType.LOSSLESS,
            target_size_reduction=10.0,
            optimize_for="prepress",
            image_settings=ImageSettings(
                optimization=ImageOptimization.BASIC,
                jpeg_quality=95,
                downsample_threshold=300,
                downsample_target=300,
                color_image_downsample=False,
                grayscale_image_downsample=False,
            ),
            content_settings=ContentSettings(
                remove_metadata=False,
                remove_bookmarks=False,
                remove_annotations=False,
            )
        )
        
        # Balanced - good quality with reasonable compression
        balanced = CompressionProfile(
            name="balanced",
            description="High quality with moderate compression",
            compression_type=CompressionType.LOSSY_MEDIUM,
            target_size_reduction=40.0,
            optimize_for="ebook",
            image_settings=ImageSettings(
                optimization=ImageOptimization.MIXED,
                jpeg_quality=85,
                downsample_threshold=300,
                downsample_target=150,
                color_image_downsample=True,
                grayscale_image_downsample=True,
            ),
            content_settings=ContentSettings(
                remove_javascript=True,
                optimize_page_content=True,
            )
        )
        
        # Smallest - maximum compression
        smallest = CompressionProfile(
            name="smallest",
            description="Maximum compression for smallest file size",
            compression_type=CompressionType.AGGRESSIVE,
            target_size_reduction=70.0,
            optimize_for="screen",
            image_settings=ImageSettings(
                optimization=ImageOptimization.MIXED,
                jpeg_quality=75,
                downsample_threshold=300,
                downsample_target=72,
                color_image_downsample=True,
                grayscale_image_downsample=True,
                mono_image_downsample=True,
                remove_duplicate_images=True,
            ),
            content_settings=ContentSettings(
                remove_metadata=True,
                remove_javascript=True,
                remove_embedded_files=True,
                optimize_page_content=True,
            )
        )
        
        # Web optimized - for online viewing
        web_optimized = CompressionProfile(
            name="web_optimized",
            description="Optimized for web viewing with fast loading",
            compression_type=CompressionType.LOSSY_MEDIUM,
            target_size_reduction=60.0,
            optimize_for="screen",
            compatibility_level="1.4",
            linearize=True,
            image_settings=ImageSettings(
                optimization=ImageOptimization.MIXED,
                jpeg_quality=80,
                downsample_threshold=150,
                downsample_target=96,
                color_image_downsample=True,
                grayscale_image_downsample=True,
            ),
            content_settings=ContentSettings(
                remove_metadata=True,
                remove_javascript=True,
                optimize_page_content=True,
            )
        )
        
        # Photo heavy - optimized for documents with many photos
        photo_heavy = CompressionProfile(
            name="photo_heavy",
            description="Optimized for documents with many photographs",
            compression_type=CompressionType.LOSSY_MEDIUM,
            target_size_reduction=50.0,
            optimize_for="ebook",
            image_settings=ImageSettings(
                optimization=ImageOptimization.PHOTOS,
                jpeg_quality=82,
                downsample_threshold=300,
                downsample_target=150,
                color_image_downsample=True,
                grayscale_image_downsample=True,
                remove_duplicate_images=True,
            )
        )
        
        # Text heavy - optimized for text documents
        text_heavy = CompressionProfile(
            name="text_heavy",
            description="Optimized for text-heavy documents",
            compression_type=CompressionType.LOSSY_LOW,
            target_size_reduction=30.0,
            optimize_for="ebook",
            image_settings=ImageSettings(
                optimization=ImageOptimization.DIAGRAMS,
                jpeg_quality=90,
                downsample_threshold=300,
                downsample_target=150,
                mono_image_downsample=False,  # Preserve text clarity
            ),
            font_settings=FontSettings(
                subset_fonts=True,
                convert_to_outlines=False,  # Keep text searchable
            )
        )
        
        # Store built-in profiles
        builtin_profiles = [archival, balanced, smallest, web_optimized, photo_heavy, text_heavy]
        for profile in builtin_profiles:
            self._profiles[profile.name] = profile
    
    def _load_user_profiles(self):
        """Load user-defined profiles from file."""
        try:
            if self.profiles_file.exists():
                with open(self.profiles_file, 'r') as f:
                    data = json.load(f)
                
                for profile_data in data.get("user_profiles", []):
                    try:
                        profile = CompressionProfile.from_dict(profile_data)
                        self._profiles[profile.name] = profile
                    except Exception as e:
                        self.logger.warning(f"Failed to load profile {profile_data.get('name', 'unknown')}: {e}")
        
        except Exception as e:
            self.logger.warning(f"Failed to load user profiles: {e}")
    
    def save_user_profiles(self):
        """Save user-defined profiles to file."""
        try:
            # Get only user profiles (not built-in)
            builtin_names = {"archival", "balanced", "smallest", "web_optimized", "photo_heavy", "text_heavy"}
            user_profiles = [
                profile.to_dict() 
                for name, profile in self._profiles.items()
                if name not in builtin_names
            ]
            
            data = {"user_profiles": user_profiles}
            
            with open(self.profiles_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            self.logger.info(f"Saved {len(user_profiles)} user profiles")
            
        except Exception as e:
            self.logger.error(f"Failed to save user profiles: {e}")
    
    def get_profile(self, name: str) -> Optional[CompressionProfile]:
        """Get a compression profile by name."""
        return self._profiles.get(name)
    
    def get_all_profiles(self) -> Dict[str, CompressionProfile]:
        """Get all available profiles."""
        return self._profiles.copy()
    
    def get_profile_names(self) -> List[str]:
        """Get list of all profile names."""
        return list(self._profiles.keys())
    
    def add_profile(self, profile: CompressionProfile) -> bool:
        """Add a new compression profile."""
        try:
            # Validate profile
            if not profile.image_settings.validate():
                self.logger.error(f"Invalid image settings in profile {profile.name}")
                return False
            
            self._profiles[profile.name] = profile
            self.save_user_profiles()
            
            self.logger.info(f"Added compression profile: {profile.name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to add profile {profile.name}: {e}")
            return False
    
    def remove_profile(self, name: str) -> bool:
        """Remove a user-defined profile."""
        try:
            # Don't allow removal of built-in profiles
            builtin_names = {"archival", "balanced", "smallest", "web_optimized", "photo_heavy", "text_heavy"}
            if name in builtin_names:
                self.logger.warning(f"Cannot remove built-in profile: {name}")
                return False
            
            if name in self._profiles:
                del self._profiles[name]
                self.save_user_profiles()
                self.logger.info(f"Removed compression profile: {name}")
                return True
            else:
                self.logger.warning(f"Profile not found: {name}")
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to remove profile {name}: {e}")
            return False
    
    def duplicate_profile(self, source_name: str, new_name: str) -> Optional[CompressionProfile]:
        """Duplicate an existing profile with a new name."""
        try:
            source_profile = self.get_profile(source_name)
            if not source_profile:
                return None
            
            # Create copy
            new_profile_data = source_profile.to_dict()
            new_profile_data['name'] = new_name
            new_profile_data['description'] = f"Copy of {source_profile.description}"
            
            new_profile = CompressionProfile.from_dict(new_profile_data)
            
            if self.add_profile(new_profile):
                return new_profile
            
        except Exception as e:
            self.logger.error(f"Failed to duplicate profile {source_name}: {e}")
        
        return None


# Global profile manager instance
_global_profile_manager: Optional[CompressionProfileManager] = None


def get_profile_manager() -> CompressionProfileManager:
    """Get the global compression profile manager."""
    global _global_profile_manager
    if _global_profile_manager is None:
        _global_profile_manager = CompressionProfileManager()
    return _global_profile_manager


def get_compression_profile(name: str) -> Optional[CompressionProfile]:
    """Get a compression profile by name."""
    manager = get_profile_manager()
    return manager.get_profile(name)


def get_available_profiles() -> List[str]:
    """Get list of available compression profile names."""
    manager = get_profile_manager()
    return manager.get_profile_names()