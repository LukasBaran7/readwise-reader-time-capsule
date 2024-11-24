from dataclasses import dataclass
from typing import List, Optional, Dict

@dataclass
class Result:
    id: str
    url: str
    title: str
    author: str
    source: str
    category: str
    location: str
    tags: Dict[str, str]
    site_name: str
    word_count: int
    created_at: str
    updated_at: str
    published_date: Optional[int]
    summary: str
    image_url: Optional[str]
    content: Optional[str]
    source_url: str
    notes: str
    parent_id: Optional[str]
    reading_progress: int
    first_opened_at: Optional[str]
    last_opened_at: Optional[str]
    saved_at: Optional[str]
    last_moved_at: Optional[str]

@dataclass
class Page:
    count: int
    nextPageCursor: str
    results: List[Result] 