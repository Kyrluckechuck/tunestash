"""
Audio format conversion utilities using ffmpeg.

Provides FLAC to M4A (AAC) conversion for maintaining consistent library format.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioConversionError(Exception):
    """Raised when audio conversion fails."""

    pass


def convert_flac_to_m4a(
    input_path: Path,
    output_path: Path | None = None,
    bitrate_kbps: int = 256,
    delete_original: bool = True,
) -> Path:
    """
    Convert FLAC file to M4A (AAC) using ffmpeg.

    Args:
        input_path: Path to input FLAC file
        output_path: Path for output M4A file (default: same name with .m4a extension)
        bitrate_kbps: AAC bitrate in kbps (default: 256)
        delete_original: Whether to delete the original FLAC after successful conversion

    Returns:
        Path to the converted M4A file

    Raises:
        AudioConversionError: If conversion fails
        FileNotFoundError: If input file doesn't exist
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if output_path is None:
        output_path = input_path.with_suffix(".m4a")

    logger.info(f"Converting {input_path.name} to M4A ({bitrate_kbps}kbps)")

    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output file if exists
        "-i",
        str(input_path),
        "-c:a",
        "aac",
        "-b:a",
        f"{bitrate_kbps}k",
        "-movflags",
        "+faststart",  # Enable streaming/seeking
        "-v",
        "warning",  # Reduce verbosity
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            error_msg = result.stderr or "Unknown error"
            logger.error(f"ffmpeg conversion failed: {error_msg}")
            raise AudioConversionError(f"ffmpeg failed: {error_msg}")

        if not output_path.exists():
            raise AudioConversionError("Output file was not created")

        # Verify output file has reasonable size
        if output_path.stat().st_size < 1000:
            raise AudioConversionError(
                "Output file is too small, conversion likely failed"
            )

        logger.info(f"Successfully converted to {output_path.name}")

        # Delete original if requested
        if delete_original:
            try:
                input_path.unlink()
                logger.debug(f"Deleted original file: {input_path.name}")
            except OSError as e:
                logger.warning(f"Failed to delete original file: {e}")

        return output_path

    except subprocess.TimeoutExpired:
        raise AudioConversionError("Conversion timed out after 5 minutes")
    except FileNotFoundError:
        raise AudioConversionError("ffmpeg not found - is it installed?")


def get_audio_format(file_path: Path) -> str | None:
    """
    Detect the audio format of a file using ffprobe.

    Returns:
        Format name (e.g., "flac", "aac", "mp3") or None if detection fails
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip().lower()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None
