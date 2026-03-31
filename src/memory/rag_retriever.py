"""
RAG 检索模块（Mock 版）
使用 TF-IDF 余弦相似度在本地 JSON 语料库中检索与用户问题最相关的历史条目。
预留 replace_with_vector_db() 接口，后续可无缝替换为 Chroma/Pinecone 等向量数据库。
"""
import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


_DEFAULT_HISTORY_PATH = Path(__file__).parent.parent.parent / "data" / "mock_history.json"


class RAGRetriever:
    """
    本地 TF-IDF RAG 检索器。
    初始化时加载语料库并构建 TF-IDF 索引，retrieve() 返回最相关的历史条目。
    """

    def __init__(self, history_path: str | Path | None = None):
        path = Path(history_path) if history_path else _DEFAULT_HISTORY_PATH
        self._records: list[dict[str, Any]] = self._load(path)
        self._vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3))
        # 拼接所有字段用于索引构建
        corpus = [self._record_to_text(r) for r in self._records]
        if corpus:
            self._tfidf_matrix = self._vectorizer.fit_transform(corpus)
        else:
            self._tfidf_matrix = None

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """
        检索与 query 最相关的 top_k 条历史记录。
        返回包含 context / my_response / source / scene_type 的字典列表。
        """
        if not self._records or self._tfidf_matrix is None:
            return []
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append(self._records[int(idx)])
        return results

    def format_for_prompt(self, query: str, top_k: int = 3) -> str:
        """
        检索后格式化为可直接插入 Prompt 的文本块。
        如果没有相关历史，返回空字符串。
        """
        records = self.retrieve(query, top_k)
        if not records:
            return ""
        parts = []
        for i, r in enumerate(records, 1):
            parts.append(
                f"【历史参考 {i}】\n"
                f"情境：{r.get('context', '')}\n"
                f"我当时的回应：{r.get('my_response', '')}"
            )
        return "\n\n".join(parts)

    def add_record(self, record: dict[str, Any]) -> None:
        """动态追加一条记录并重建索引（小规模语料用）"""
        self._records.append(record)
        self._rebuild_index()

    def replace_with_vector_db(self, vector_db_client: Any) -> None:
        """
        预留接口：替换为向量数据库检索。
        实现时覆盖此方法，保持 retrieve() 签名不变即可。

        示例（Chroma）：
            def retrieve(self, query, top_k=3):
                results = self._db.query(query_texts=[query], n_results=top_k)
                return results["documents"]
        """
        raise NotImplementedError(
            "请继承 RAGRetriever 并实现 retrieve() 方法以接入向量数据库"
        )

    # ------------------------------------------------------------------ #
    # 私有方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []

    @staticmethod
    def _record_to_text(record: dict[str, Any]) -> str:
        """将一条记录的所有文本字段拼接为一个字符串用于索引"""
        parts = [
            record.get("context", ""),
            record.get("my_response", ""),
            " ".join(record.get("keywords", [])),
            record.get("scene_type", ""),
        ]
        return " ".join(filter(None, parts))

    def _rebuild_index(self) -> None:
        corpus = [self._record_to_text(r) for r in self._records]
        if corpus:
            self._tfidf_matrix = self._vectorizer.fit_transform(corpus)


# 全局单例
_instance: RAGRetriever | None = None


def get_retriever(history_path: str | Path | None = None) -> RAGRetriever:
    """获取全局 RAGRetriever 单例"""
    global _instance
    if _instance is None or history_path is not None:
        _instance = RAGRetriever(history_path)
    return _instance
