"""Diagnose premium review model without revealing secrets or customer messages."""
from __future__ import annotations
import logging
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config import Settings
s=Settings.load()
print("ANTHROPIC_KEY_PRESENT",bool(s.anthropic_api_key))
if s.anthropic_api_key:
    try:
        import anthropic
        client=anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=20, max_retries=0)
        result=client.messages.create(
            model="claude-opus-4-6",max_tokens=45,
            messages=[{"role":"user","content":"「確認しました」とだけ返答してください。"}],
        )
        print("OPUS_API_TEST",len(result.content),str(result.model))
    except Exception as err:
        print("OPUS_API_ERROR",type(err).__name__,getattr(err,"status_code",None),
              str(err)[:160].replace(s.anthropic_api_key,"[REDACTED]"))
else:
    print("OPUS_API_NO_KEY")
