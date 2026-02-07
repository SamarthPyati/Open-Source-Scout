"""
Text chunking utilities for LLM context management.
"""
from typing import List, Tuple
import re


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a text string.
    Uses rough heuristic: ~4 characters per token for English text.
    
    Args:
        text: Input text
        
    Returns:
        Estimated token count
    """
    return len(text) // 4


def chunk_text(
    text: str,
    max_tokens: int = 2000,
    overlap_tokens: int = 100
) -> List[str]:
    """
    Split text into chunks with overlap.
    
    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk
        overlap_tokens: Overlap between chunks
        
    Returns:
        List of text chunks
    """
    max_chars = max_tokens * 4
    overlap_chars = overlap_tokens * 4
    
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        # Find a good break point
        if end < len(text):
            # Try to break at paragraph
            para_break = text.rfind("\n\n", start, end)
            if para_break > start + max_chars // 2:
                end = para_break + 2
            else:
                # Try to break at sentence
                sentence_break = text.rfind(". ", start, end)
                if sentence_break > start + max_chars // 2:
                    end = sentence_break + 2
                else:
                    # Break at word
                    word_break = text.rfind(" ", start, end)
                    if word_break > start:
                        end = word_break + 1
        
        chunks.append(text[start:end].strip())
        start = end - overlap_chars
        
        if start >= len(text):
            break
    
    return chunks


def chunk_code(
    code: str,
    max_lines: int = 100,
    overlap_lines: int = 10
) -> List[str]:
    """
    Split code into chunks by lines.
    
    Args:
        code: Source code to chunk
        max_lines: Maximum lines per chunk
        overlap_lines: Overlap between chunks
        
    Returns:
        List of code chunks
    """
    lines = code.split("\n")
    
    if len(lines) <= max_lines:
        return [code]
    
    chunks = []
    start = 0
    
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        chunk_lines = lines[start:end]
        chunks.append("\n".join(chunk_lines))
        
        start = end - overlap_lines
        if start >= len(lines):
            break
    
    return chunks


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within token limit.
    
    Args:
        text: Input text
        max_tokens: Maximum tokens
        
    Returns:
        Truncated text
    """
    max_chars = max_tokens * 4
    
    if len(text) <= max_chars:
        return text
    
    # Find a clean break point
    truncated = text[:max_chars]
    
    # Try to end at paragraph
    para_break = truncated.rfind("\n\n")
    if para_break > max_chars * 0.8:
        return truncated[:para_break] + "\n\n[... truncated]"
    
    # Try to end at sentence
    sentence_break = truncated.rfind(". ")
    if sentence_break > max_chars * 0.8:
        return truncated[:sentence_break + 1] + "\n\n[... truncated]"
    
    return truncated + "\n\n[... truncated]"


def format_code_context(
    file_path: str,
    content: str,
    start_line: int = 1,
    highlight_lines: List[int] = None
) -> str:
    """
    Format code content with file path and line numbers.
    
    Args:
        file_path: Path to the file
        content: Code content
        start_line: Starting line number
        highlight_lines: Lines to highlight with markers
        
    Returns:
        Formatted code block
    """
    lines = content.split("\n")
    highlight_lines = highlight_lines or []
    
    formatted_lines = [f"## {file_path}"]
    formatted_lines.append("```")
    
    for i, line in enumerate(lines):
        line_num = start_line + i
        marker = ">>> " if line_num in highlight_lines else "    "
        formatted_lines.append(f"{marker}{line_num:4d} | {line}")
    
    formatted_lines.append("```")
    
    return "\n".join(formatted_lines)


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """
    Extract potential search keywords from text.
    
    Args:
        text: Input text (e.g., issue title and body)
        max_keywords: Maximum number of keywords
        
    Returns:
        List of keywords
    """
    # Common stopwords to filter
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after",
        "above", "below", "between", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "each",
        "few", "more", "most", "other", "some", "such", "no", "nor", "not",
        "only", "own", "same", "so", "than", "too", "very", "just", "and",
        "but", "if", "or", "because", "as", "until", "while", "it", "this",
        "that", "these", "those", "i", "we", "you", "he", "she", "they",
        "what", "which", "who", "whom", "this", "that", "am", "been", "being"
    }
    
    # Extract words (alphanumeric with underscores)
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text.lower())
    
    # Filter and count
    word_counts = {}
    for word in words:
        if word not in stopwords and len(word) > 2:
            word_counts[word] = word_counts.get(word, 0) + 1
    
    # Sort by frequency and return top keywords
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    
    return [word for word, count in sorted_words[:max_keywords]]
