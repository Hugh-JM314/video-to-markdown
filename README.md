# video-to-markdown

Convert local video files to structured Markdown notes with subtitle extraction, Whisper speech recognition, intelligent segmentation, and automatic screenshots.

## Features

- **Subtitle Extraction**: Extract subtitles from SRT files or embedded in video
- **Speech Recognition**: Use OpenAI Whisper for automatic transcription when no subtitles available
- **Intelligent Segmentation**: Automatically segment video content into meaningful sections
- **Automatic Screenshots**: Insert screenshot placeholders at key points and generate actual screenshots
- **Multi-format Support**: Works with MP4, MOV, AVI, MKV, and WebM formats

## Installation

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install FFmpeg

**Windows:**
```bash
# Download from https://www.gyan.dev/ffmpeg/builds/
# Extract to project root or add to PATH
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt-get install ffmpeg
```

## Usage

```bash
# Basic usage
python main.py "path/to/video.mp4" --output "output/directory"

# Example
python main.py "my_video.mp4" --output ./notes
```

## Requirements

- Python 3.8+
- FFmpeg (see installation above)
- Whisper model will be downloaded automatically on first run

## Project Structure

```
video-to-markdown/
├── main.py              # Main application
├── skill.json           # Skill configuration
├── requirements.txt     # Python dependencies
├── README.md            # This file
└── output/             # Generated output
```

## License

MIT License