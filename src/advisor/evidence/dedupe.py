"""来源独立性：转载数不等于证据数。按原始来源与内容指纹聚成事件簇。"""
import hashlib
import re
from urllib.parse import urlparse

from advisor.contracts import SearchHit

_PUBLISHER = re.compile(r"来源[:：]\s*([一-龥A-Za-z]{2,12})")


def origin_id(url: str) -> str:
    p = urlparse(url)
    host = re.sub(r"^(www|m|wap)\.", "", p.netloc.lower())
    return f"{host}{p.path.rstrip('/')}"


def extract_publisher(text: str, fallback: str | None) -> str | None:
    m = _PUBLISHER.search(text or "")
    return m.group(1) if m else fallback


def simhash(text: str, bits: int = 64) -> int:
    text = re.sub(r"\s+", "", text)
    grams = [text[i:i + 2] for i in range(max(len(text) - 1, 1))]
    vec = [0] * bits
    for g in grams:
        h = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "big")
        for i in range(bits):
            vec[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(bits) if vec[i] > 0)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _norm_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", title.split("_")[0].split("|")[0])


def assign_clusters(hits: list[SearchHit], threshold: int = 10) -> dict[str, str]:
    """返回 url -> cluster_id。标题相同或正文指纹接近视为同一事件。"""
    reps: list[tuple[str, str, int]] = []   # (cluster_id, norm_title, simhash)
    result: dict[str, str] = {}
    for hit in sorted(hits, key=lambda h: (-h.authority, -h.rerank_score)):
        title = _norm_title(hit.title)
        sh = simhash((hit.summary or hit.snippet)[:400])
        for cid, t, s in reps:
            if title == t or hamming(sh, s) <= threshold:
                result[hit.url] = cid
                break
        else:
            cid = "cl_" + hashlib.sha1(hit.url.encode()).hexdigest()[:8]
            reps.append((cid, title, sh))
            result[hit.url] = cid
    return result
