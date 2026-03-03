import subprocess
import sys
import shutil

def check_ffmpeg():
    # 1. Check if ffmpeg is installed in PATH
    if not shutil.which("ffmpeg"):
        print("❌ Error: FFmpeg not found in your system PATH.")
        print_instructions()
        return False

    try:
        # 2. Check for drawtext filter support
        result = subprocess.run(['ffmpeg', '-filters'], capture_output=True, text=True, check=True)
        if "drawtext" in result.stdout:
            print("✅ FFmpeg OK: 'drawtext' filter is available.")
            return True
        else:
            print("❌ Error: FFmpeg found, but 'drawtext' filter is missing.")
            print_instructions()
            return False
    except Exception as e:
        print(f"❌ Unexpected error checking FFmpeg: {e}")
        return False

def print_instructions():
    print("\nHow to fix:")
    print("- Linux: sudo apt update && sudo apt install ffmpeg")
    print("- macOS: brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg")
    print("- Windows: Download 'Full' build from gyan.dev/ffmpeg/builds/")

if __name__ == "__main__":
    if not check_ffmpeg():
        sys.exit(1)
