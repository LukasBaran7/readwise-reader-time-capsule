from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, ConfigDict


class ComponentScores(BaseModel):
    quality: float = 7.0
    information_density: float = 5.0
    readability: float = 5.0
    topic_relevance: float = 5.0
    freshness: float = 5.0
    engagement_potential: float = 5.0


class ReadabilityMetrics(BaseModel):
    flesch_reading_ease: float
    smog_index: float
    coleman_liau_index: float
    automated_readability_index: float
    complexity_level: str
    normalized_score: float


class InformationDensityMetrics(BaseModel):
    lexical_diversity: float
    fact_density: float
    concept_density: float
    key_concepts: List[str]
    normalized_score: float


class TopicRelevanceMetrics(BaseModel):
    top_topics: List[str]
    topic_matches: Dict[str, float]
    normalized_score: float


class FreshnessMetrics(BaseModel):
    age_days: int
    temporal_references_count: int
    decay_rate: int
    is_recent: bool
    normalized_score: float


class EmotionCounts(BaseModel):
    positive: int = 0
    negative: int = 0
    surprise: int = 0


class EngagementMetrics(BaseModel):
    emotional_score: float
    narrative_score: float
    visual_score: float
    interactive_score: float
    emotion_counts: EmotionCounts
    normalized_score: float
    language: str = "en"


class Article(BaseModel):
    """
    Article model that matches MongoDB document structure.
    """

    model_config = ConfigDict(
        populate_by_name=True, json_encoders={datetime: lambda v: v.isoformat()}
    )

    id: str = Field(default=None, alias="_id")
    readwise_id: str = Field(..., alias="id")
    url: str
    title: str
    author: str
    source: Optional[str] = None
    category: str
    location: str
    tags: Dict[str, Any] = Field(default_factory=dict)
    site_name: str
    word_count: int = Field(default=0, alias="word_count")
    created_at: datetime
    updated_at: datetime
    published_date: Optional[int] = Field(
        None, description="Unix timestamp in milliseconds"
    )
    summary: Optional[str] = None
    image_url: Optional[str] = None
    content: Optional[str] = None
    source_url: Optional[str] = None
    notes: str = ""
    parent_id: Optional[str] = None
    reading_progress: float
    first_opened_at: Optional[datetime] = None
    last_opened_at: Optional[datetime] = None
    saved_at: datetime
    last_moved_at: datetime
    html_content: Optional[str] = None
    
    # Analysis fields
    analyzed_at: Optional[datetime] = None
    priority_score: Optional[float] = None
    component_scores: Optional[ComponentScores] = None
    readability: Optional[ReadabilityMetrics] = None
    information_density: Optional[InformationDensityMetrics] = None
    topic_relevance: Optional[TopicRelevanceMetrics] = None
    freshness: Optional[FreshnessMetrics] = None
    engagement_potential: Optional[EngagementMetrics] = None
    extracted_content: Optional[str] = None
