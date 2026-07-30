"""解析/写回 GitHub issue 正文中的 ```json loop``` 围栏块；该块是 Card 真源。"""
import json


def extract_block(body):
    m = "```json loop"
    if m not in (body or ""): return None
    seg = body.split(m,1)[1].split("```",1)[0]
    try: return json.loads(seg)
    except Exception: return None


def inject_block(body, blk):
    m = "```json loop"
    if m not in (body or ""):
        return (body or "") + "\n\n" + m + "\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```\n"
    head, rest = body.split(m,1); tail = rest.split("```",1)[1]
    return head + m + "\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```" + tail
