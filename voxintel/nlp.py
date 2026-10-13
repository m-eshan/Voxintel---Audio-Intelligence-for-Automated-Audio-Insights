from __future__ import annotations

import difflib
import re
from collections import Counter

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "for",
    "from",
    "had",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "let",
    "lets",
    "may",
    "more",
    "need",
    "not",
    "of",
    "on",
    "or",
    "our",
    "please",
    "so",
    "some",
    "that",
    "the",
    "their",
    "them",
    "there",
    "this",
    "to",
    "up",
    "use",
    "we",
    "will",
    "with",
    "you",
    "your",
    # Contraction tails
    "ve",
    "ll",
    "re",
    "d",
    "m",
    "s",
    "t",
}

FILLER_WORDS = {"um", "uh", "hmm", "like", "you know", "basically", "actually", "right"}
LOW_SIGNAL_WORDS = {
    "lets",
    "let's",
    "were",
    "we're",
    "ill",
    "i'll",
    "ive",
    "i've",
    "im",
    "i'm",
    "cant",
    "can't",
    "dont",
    "don't",
    "could",
    "would",
    "should",
    "really",
    "still",
    "majority",
    "thing",
    "things",
    "make",
    "sure",
    "team",
    "today",
    "yeah",
    "okay",
    "good",
    "great",
    "thanks",
    "everyone",
    "absolutely",
    "perfect",
    "work",
    "just",
    "also",
    "kind",
    "sort",
    "thing",
    "really",
    "maybe",
    "probably",
}

COMMON_FIXES = {
    "log in": "login",
    "logan": "login",
    "colour schemes": "color schemes",
    "colour scenes": "color schemes",
    "educators": "edge cases",
    "fancations": "functions",
    "dog fooding": "dogfooding",
    "ue ": "ui ",
    "ua ": "ui ",
}

COMMON_WORDS = {
    "about","agenda","align","aligned","analysis","anonymous","approach","authentication","backend","balance",
    "board","book","bugs","candidate","cases","change","changes","channel","charts","check","clear","club","color",
    "communication","confirm","consistency","contacts","core","critical","customer","customers","deadline","decided",
    "decision","demo","deployment","design","discuss","discussion","documentation","edge","elements","email","feedback",
    "final","fix","flow","focus","follow","frontend","goals","group","hiring","interviews","issue","issues","known",
    "language","launch","link","login","management","meeting","meetings","monitoring","notes","onboarding","opinion",
    "phase","plan","planning","priority","product","progress","project","question","release","reminder","review",
    "schedule","screens","spreadsheet","stable","stage","support","survey","task","tasks","team","testing","timeline",
    "tracking","trend","trends","update","updates","users","week","weeks","workaround",
}

DOMAIN_WORDS = {
    "api","auth","authentication","backend","chart","charts","customer","dashboard","demo","deployment","dogfooding",
    "edge","frontend","handbook","interview","login","okr","pdf","pm","release","report","sprint","streamlit","survey",
    "testing","tfidf","textrank","ui","vad","voxintel","whisper",
}

ALLOWED_WORDS = COMMON_WORDS | DOMAIN_WORDS | STOPWORDS | FILLER_WORDS | LOW_SIGNAL_WORDS


def _heuristic_sentence_chunks(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []

    boundaries = {
        "however",
        "meanwhile",
        "because",
        "tomorrow",
        "today",
        "agreed",
        "decided",
        "approved",
        "action",
        "issue",
        "issues",
        "priority",
        "update",
        "progress",
        "authentication",
        "design",
        "release",
        "testing",
        "review",
        "deadline",
        "fix",
        "bugs",
        "task",
        "tasks",
        "prepare",
        "share",
        "complete",
    }

    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        cleaned = re.sub(r"[^a-z']", "", word.lower())
        if current and len(current) >= 18 and cleaned in boundaries:
            chunks.append(" ".join(current).strip())
            current = [word]
            continue

        current.append(word)
        if len(current) >= 28:
            chunks.append(" ".join(current).strip())
            current = []

    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    parts = [part.strip() for part in parts if part.strip()]
    if len(parts) <= 1 or max((len(part.split()) for part in parts), default=0) > 45:
        return _heuristic_sentence_chunks(normalized)
    return parts


def clean_sentences(sentences: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned_sentences: list[str] = []
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).strip(" ,.-")
        if len(normalized) < 5:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_sentences.append(normalized)
    return cleaned_sentences


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text.lower())


def clean_transcript(text: str) -> tuple[str, list[str], list[str]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "", [], []

    cleaned = normalized
    for source, target in COMMON_FIXES.items():
        cleaned = re.sub(rf"\b{re.escape(source)}\b", target, cleaned, flags=re.IGNORECASE)
    for filler in sorted(FILLER_WORDS, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(filler)}\b", "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    sentences = clean_sentences(split_sentences(cleaned))
    tokens = [token for token in tokenize(cleaned) if token not in STOPWORDS and token not in FILLER_WORDS]
    return cleaned, sentences, tokens


def extract_keywords(text_or_tokens: str | list[str], top_n: int = 10) -> pd.DataFrame:
    if isinstance(text_or_tokens, str):
        tokens = tokenize(text_or_tokens)
    else:
        tokens = [token.replace("'", "") for token in text_or_tokens]

    filtered = [
        token
        for token in tokens
        if len(token) > 3 and token not in STOPWORDS and token not in LOW_SIGNAL_WORDS and token not in FILLER_WORDS
    ]
    if not filtered:
        return pd.DataFrame(columns=["keyword", "count"])

    # Build small token windows so TF-IDF can still rank terms in a single transcript.
    windows = [" ".join(filtered[index : index + 40]) for index in range(0, len(filtered), 20)]
    windows = [window for window in windows if window.strip()]
    if not windows:
        windows = [" ".join(filtered)]

    all_stops = list(STOPWORDS | LOW_SIGNAL_WORDS | FILLER_WORDS)
    vectorizer = TfidfVectorizer(
        stop_words=all_stops,
        ngram_range=(1, 2),
        max_features=max(top_n * 3, 15),
    )
    matrix = vectorizer.fit_transform(windows)
    scores = matrix.sum(axis=0).A1
    features = vectorizer.get_feature_names_out()
    ranked = sorted(zip(features, scores), key=lambda item: item[1], reverse=True)[:top_n]
    return pd.DataFrame(
        [{"keyword": keyword, "count": round(float(score), 3)} for keyword, score in ranked],
        columns=["keyword", "count"],
    )
