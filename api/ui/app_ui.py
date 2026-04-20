# Compatibility launcher kept so older commands still redirect to the real UI entrypoint in ui/app_ui.py.
# DEPRECATED: Milestone 4 UI moved to ui/app_ui.py
# Run: streamlit run ui/app_ui.py
import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent.parent
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "ui/app_ui.py"] + sys.argv[1:],
        cwd=root
    )
