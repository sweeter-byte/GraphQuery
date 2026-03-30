from __future__ import annotations

from pathlib import Path
import sys

import nbformat
from nbclient import NotebookClient


path = Path(__file__).resolve().parent / "m3_eps_analysis.ipynb"
root = path.parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

print(f"Executing {path}")

with path.open("r", encoding="utf-8") as f:
    notebook = nbformat.read(f, as_version=4)

client = NotebookClient(notebook, timeout=3600, kernel_name="python3")
client.execute(cwd=str(root))

with path.open("w", encoding="utf-8") as f:
    nbformat.write(notebook, f)

print("Execution complete")
