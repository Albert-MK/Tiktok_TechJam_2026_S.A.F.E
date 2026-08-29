"""目录索引：把 5 万件商品预处理成「可做贝叶斯推理的假设集合」。

对每件商品，我们离线算好三样东西：

1. **意图卡**（`user_model.intent_card`）——如果它是目标，顾客会依次说出哪些约束。
2. **先验概率**——它成为目标的可能性有多大。
3. **倒排索引**——听到一句话后，怎么在毫秒级取回可能的候选。

## 关于先验：为什么用评论数

目标商品来自真实的 Amazon 购买记录，也就是「从所有评论里抽一条，看它评的是哪件商品」。
因此某商品被抽中的概率天然正比于它的评论条数：

    P(target = p) ∝ rating_number(p)

这不是拍脑袋的启发式加权，而是抽样过程本身决定的。
实测也印证了：公开集 200 个目标的评论数中位数是 **6846**，
而整个目录的中位数只有 **12**——差了近 600 倍。

先验用对数形式参与打分，证据一旦出现就会迅速盖过它，因此即便
私有集的抽样方式略有不同，也只会损失一点效率，不会导致系统性错误。
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path

from .user_model import (
    classify_constraint,
    coarse_category,
    intent_card,
    searchable_text,
)

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the to with
    this you your our their they we will can not no s t d ll m o re ve y""".split()
)
# 出现在过多商品里的词对定位目标几乎没有帮助，建索引时直接丢掉以控制内存。
MAX_DOC_FREQ_RATIO = 0.12
BLOB_LIMIT = 1400


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


class CatalogIndex:
    """全目录的只读索引。一个进程只需构建一次。"""

    def __init__(self, catalog_path: str | Path) -> None:
        self.asins: list[str] = []
        self.cats: list[str] = []
        self.constraints: list[tuple[str, ...]] = []
        self.ctypes: list[tuple[str, ...]] = []
        self.n_hard: list[int] = []
        self.log_prior: list[float] = []
        self.blobs: list[str] = []

        self.by_cat: dict[str, list[int]] = defaultdict(list)
        self.by_constraint: dict[str, list[int]] = defaultdict(list)
        self.pid_of: dict[str, int] = {}
        self._cat_by_lower: dict[str, str] = {}
        self._token_postings: dict[str, list[int]] = {}
        self.idf: dict[str, float] = {}

        self._load(catalog_path)

    # -- 构建 ---------------------------------------------------------------

    def _load(self, catalog_path: str | Path) -> None:
        raw_tokens: dict[str, list[int]] = defaultdict(list)
        with Path(catalog_path).open(encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                if not line.strip():
                    continue
                product = json.loads(line)
                asin = str(product.get("parent_asin") or "")
                if not asin:
                    continue

                hard, soft = intent_card(product)
                values = tuple(hard) + tuple(soft)
                cat = coarse_category([str(v) for v in product.get("categories") or []])

                self.asins.append(asin)
                self.cats.append(cat)
                self.constraints.append(values)
                self.ctypes.append(tuple(classify_constraint(v) for v in values))
                self.n_hard.append(len(hard))
                self.log_prior.append(self._prior(product))

                blob = searchable_text(product).lower()
                self.blobs.append(blob[:BLOB_LIMIT])

                pid = len(self.asins) - 1
                self.pid_of[asin] = pid
                self.by_cat[cat].append(pid)
                for value in set(values):
                    self.by_constraint[value.lower()].append(pid)

                # 回退检索的词面索引。除了模拟器直接引用的表面文本，也收进商品正文，
                # 这样即便主办方换了意图卡的取材字段，仍然搜得到目标。
                # 高频词在下面按文档频率剪掉，内存不会失控。
                surface = " ".join((str(product.get("title") or ""), cat, str(product.get("store") or ""), *values))
                for tok in set(tokenize(surface)) | set(tokenize(blob[:BLOB_LIMIT])):
                    raw_tokens[tok].append(pid)

        total = len(self.asins)
        cutoff = max(50, int(total * MAX_DOC_FREQ_RATIO))
        for tok, postings in raw_tokens.items():
            if len(postings) > cutoff:
                continue
            self._token_postings[tok] = postings
            self.idf[tok] = math.log(1.0 + total / len(postings))

    @staticmethod
    def _prior(product: dict) -> float:
        """log P(target = p)，未归一化。"""
        reviews = product.get("rating_number")
        try:
            reviews = float(reviews)
        except (TypeError, ValueError):
            reviews = 0.0
        rating = product.get("average_rating")
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            rating = 0.0
        # 评论数决定量级；平均分只做极轻微的偏好修正。
        return math.log1p(max(reviews, 0.0)) + 0.05 * rating

    # -- 候选召回 -----------------------------------------------------------

    def category_pool(self, cat: str) -> list[int]:
        return self.by_cat.get(cat, [])

    def find_category(self, message: str) -> str:
        """从一句自由文本里反查出目录中已知的粗类目。

        模板解析失败时（措辞被改写）用这条通道：类目名本身是从目录推导出来的，
        改写不会动它，所以直接在消息里找「最长的已知类目名」即可。
        只有约一千个类目，逐个子串匹配的开销可以忽略。
        """
        if not self._cat_by_lower:
            self._cat_by_lower = {cat.lower(): cat for cat in self.by_cat}
        lowered = message.lower()
        best = ""
        for key in self._cat_by_lower:
            if len(key) > len(best) and key in lowered:
                best = key
        return self._cat_by_lower[best] if best else ""

    def constraint_pool(self, value: str) -> list[int]:
        return self.by_constraint.get(value.lower(), [])

    def lexical_pool(self, phrases: list[str], limit: int) -> list[int]:
        """词面回退召回：意图卡对不上时（改写、私有意图卡）保证仍有候选。

        用 IDF 加权的词袋打分，取分数最高的 `limit` 个商品。
        """
        scores: dict[int, float] = defaultdict(float)
        for phrase in phrases:
            for tok in set(tokenize(phrase)):
                postings = self._token_postings.get(tok)
                if not postings:
                    continue
                weight = self.idf.get(tok, 0.0)
                for pid in postings:
                    scores[pid] += weight
        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -self.log_prior[kv[0]]))
        return [pid for pid, _ in ranked[:limit]]

    def popular(self, limit: int) -> list[int]:
        order = sorted(range(len(self.asins)), key=lambda pid: -self.log_prior[pid])
        return order[:limit]

    def __len__(self) -> int:
        return len(self.asins)
