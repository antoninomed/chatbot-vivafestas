# app/storage/memory.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

@dataclass
class MemoryMsg:
    role: str          # "user" | "assistant"
    content: str
    ts: datetime

_HISTORY: Dict[str, List[MemoryMsg]] = {}
_STATE: Dict[str, dict] = {}

HISTORY_LIMIT = 12
STATE_TTL_MIN = 60

def add_message(user_id: str, role: str, content: str) -> None:
    msgs = _HISTORY.setdefault(user_id, [])
    msgs.append(MemoryMsg(role=role, content=content, ts=datetime.utcnow()))
    if len(msgs) > HISTORY_LIMIT:
        del msgs[:-HISTORY_LIMIT]

def recent_history(user_id: str) -> List[MemoryMsg]:
    return _HISTORY.get(user_id, [])

def get_state(user_id: str) -> dict:
    st = _STATE.get(user_id)
    if not st:
        st = {"state": "MENU", "data": {}, "updated_at": datetime.utcnow()}
        _STATE[user_id] = st
        return st

    if datetime.utcnow() - st["updated_at"] > timedelta(minutes=STATE_TTL_MIN):
        st = {"state": "MENU", "data": {}, "updated_at": datetime.utcnow()}
        _STATE[user_id] = st
        return st

    return st

def set_state(user_id: str, state: str, data: Optional[dict] = None) -> None:
    st = _STATE.get(user_id) or {"state": "MENU", "data": {}, "updated_at": datetime.utcnow()}
    st["state"] = state
    if data is not None:
        st["data"] = data
    st["updated_at"] = datetime.utcnow()
    _STATE[user_id] = st