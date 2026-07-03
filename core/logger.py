"""Buffered JSONL logger."""

import atexit
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Windows consoles default to a legacy code page (e.g. cp1252) that can't encode
# the emoji in the log lines below; force UTF-8 so they don't raise
# UnicodeEncodeError. No-op on POSIX, where stdout is already UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


class JsonlLogger:
    """Buffered JSONL logger. Fast (batched writes) and correct (real JSON)."""

    def __init__(self, enabled: bool = False, log_dir: str = "runs",
                 file_name: str = None, buffer_size: int = 500,
                 flush_interval: float = 1.0):
        self.enabled = enabled
        self.entries_logged = 0
        if not enabled:
            return

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / (file_name or f"trace_{self.session_id}.jsonl")
        self.file_handle = open(self.log_file, "w", encoding="utf-8", buffering=8192)

        self.buffer: List[str] = []
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.last_flush = time.time()

        atexit.register(self.close)
        print(f"🚀 LOGGING ENABLED - Session: {self.session_id}")
        print(f"📁 Log File: {self.log_file}")

    def log(self, event_type: str, content: str = "", **metadata) -> None:
        if not self.enabled:
            return
        record: Dict[str, object] = {
            "timestamp": time.time(),
            "event_type": event_type,
            "session_id": self.session_id,
        }
        if content:
            record["content"] = content
        record.update(metadata)
        self.buffer.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        self.entries_logged += 1

        if (len(self.buffer) >= self.buffer_size or
                time.time() - self.last_flush > self.flush_interval):
            self._flush_buffer()

    def log_token(self, token: str, life: int, ctx_pressure: float) -> None:
        self.log("token", content=token, life=life, ctx_pressure=round(ctx_pressure, 1))

    def _flush_buffer(self) -> None:
        if not self.enabled or not self.buffer:
            return
        self.file_handle.write("\n".join(self.buffer) + "\n")
        self.buffer.clear()
        self.last_flush = time.time()

    def flush(self) -> None:
        if self.enabled:
            self._flush_buffer()
            self.file_handle.flush()

    def close(self) -> None:
        if not self.enabled or not hasattr(self, "file_handle") or self.file_handle.closed:
            return
        self._flush_buffer()
        self.file_handle.close()
        print(f"🚀 LOGGER CLOSED - {self.entries_logged} entries saved")
        print(f"📁 Log: {self.log_file}")
