"""Install every AI in custom1/ into the game's AI folder.

Copies name.per, its name/ package, and an empty name.ai marker (the game's
AI dropdown lists .ai files). Run after editing, then restart the lobby:
    .venv\\Scripts\\python custom1\\install.py
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_packages import copy_strategy  # noqa: E402

here = Path(__file__).resolve().parent
ai_dir = Path(open(here.parent / "settings.txt").readline().strip())

for loader in sorted(here.glob("*.per")):
    copy_strategy(loader, ai_dir)
    (ai_dir / (loader.stem + ".ai")).touch()
    print("installed", loader.stem)
