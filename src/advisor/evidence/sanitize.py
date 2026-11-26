"""外部网页只是数据：去掉脚本与疑似指令文本，防止提示注入经检索进入推理。"""
import html
import re

_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_INJECTION = re.compile(
    r"(忽略(之前|以上|上述|前面)|无视(之前|以上)|ignore (all |the )?(previous|above|prior)|system prompt|"
    r"你现在是|你是一个|you are now|developer mode|<\|im_start\|>|###\s*(system|instruction)|请(将|把)(以下|上述).{0,10}(发送|输出))",
    re.I,
)


def sanitize(text: str, max_chars: int = 4000) -> tuple[str, bool]:
    """返回（清洗后文本，是否发现疑似注入）。"""
    text = _SCRIPT.sub(" ", text or "")
    text = _MD_IMAGE.sub(" ", text)
    text = html.unescape(_TAG.sub(" ", text))
    kept, suspicious = [], False
    for line in text.splitlines():
        line = re.sub(r"[ \t　]+", " ", line).strip()
        if not line:
            continue
        if _INJECTION.search(line):
            suspicious = True
            continue
        kept.append(line)
    return "\n".join(kept)[:max_chars], suspicious
