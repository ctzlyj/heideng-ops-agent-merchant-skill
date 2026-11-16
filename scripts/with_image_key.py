"""Agent launches this after task scope/price approval; user only fills masked input."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heideng_merchant.cli import main
from heideng_merchant.merchant_key_ui import with_key
from heideng_merchant.safety import SafetyError
if __name__ == '__main__':
    try:
        raise SystemExit(with_key(lambda: main(sys.argv[1:])))
    except SafetyError as error:
        print(json.dumps({'status':'blocked','error':str(error)}))
        raise SystemExit(2)
