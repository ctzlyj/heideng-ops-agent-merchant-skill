"""One silent maintenance check, never a business scheduler or login launcher."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from heideng_merchant import update_client
from heideng_merchant.safety import SafetyError
p=argparse.ArgumentParser();p.add_argument("--state",type=Path,required=True);a=p.parse_args()
try:
    update_client.recover_switch(a.state)
    update_client.apply(a.state)
except (SafetyError,OSError,ValueError):
    try:update_client.record_failure(a.state,"automatic-update-deferred")
    except (SafetyError,OSError):pass

finally:
    try:
        value=update_client.settings(a.state);value["scheduledUntil"]=0;update_client.save_settings(a.state,value)
    except (SafetyError,OSError):pass
