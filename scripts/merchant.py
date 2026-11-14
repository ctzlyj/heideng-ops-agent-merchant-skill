"""Entry point kept inside the single installed Skill."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli import main
if __name__=='__main__':raise SystemExit(main())
