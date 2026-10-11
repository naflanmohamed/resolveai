"""Zero-cost local retrieval baseline. All knowledge is scoped to the demo org."""
import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .models import Chunk, Document


def chunk_text(text: str, chunk_words: int = 175, overlap: int = 35) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = chunk_words - overlap
    for start in range(0, len(words), step):
        part = words[start:start + chunk_words]
        if not part:
            break
        chunks.append(" ".join(part))
        if start + chunk_words >= len(words):
            break
    return chunks


def add_document(db: Session, title: str, content: str, source_type: str = "text") -> Document:
    cleaned = re.sub(r"\s+", " ", content).strip()
    document = Document(title=title.strip(), content=cleaned, source_type=source_type)
    db.add(document)
    db.flush()
    for idx, chunk in enumerate(chunk_text(cleaned)):
        db.add(Chunk(document_id=document.id, content=chunk, ordinal=idx))
    db.commit()
    db.refresh(document)
    return document


def retrieve(db: Session, query: str, limit: int = 3) -> list[dict]:
    records = db.execute(select(Chunk, Document.title).join(Document)).all()
    if not records:
        return []
    texts = [record[0].content for record in records]
    corpus = texts + [query]
    matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform(corpus)
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ordering = scores.argsort()[::-1][:limit]
    return [
        {"document_id": records[int(i)][0].document_id,
         "chunk_id": records[int(i)][0].id,
         "title": records[int(i)][1],
         "excerpt": texts[int(i)][:700],
         "score": round(float(scores[int(i)]), 3)}
        for i in ordering if scores[int(i)] >= 0.045
    ]
