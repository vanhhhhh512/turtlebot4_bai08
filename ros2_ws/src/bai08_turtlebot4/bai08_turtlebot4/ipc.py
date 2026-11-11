import json, os
from pathlib import Path

def atomic(path, value):
    path=Path(path)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False))
    os.replace(tmp,path)

def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError,ValueError):
        return {}
