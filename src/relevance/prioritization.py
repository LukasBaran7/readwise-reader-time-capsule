from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.article import Article
from app.core.config import get_database
from app.services.content_extractor import ContentExtractor
from app.services.readability_analyzer import ReadabilityAnalyzer
from app.services.information_density_analyzer import InformationDensityAnalyzer
from app.services.topic_relevance_analyzer import TopicRelevanceAnalyzer
from app.services.freshness_analyzer import FreshnessAnalyzer
from app.services.engagement_analyzer import EngagementAnalyzer
from bson import ObjectId
from datetime import datetime, timezone, timedelta
import logging
import os

router = APIRouter(prefix="/prioritization", tags=["prioritization"])
logger = logging.getLogger(__name__)


class PrioritizationService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.content_extractor = ContentExtractor()
        self.readability_analyzer = ReadabilityAnalyzer()
        self.information_density_analyzer = InformationDensityAnalyzer()
        self.topic_relevance_analyzer = TopicRelevanceAnalyzer()
        self.freshness_analyzer = FreshnessAnalyzer()
        self.engagement_analyzer = EngagementAnalyzer()

        # Define component weights according to the spec
        self.component_weights = {
            "quality": 0.25,
            "information_density": 0.15,
            "readability": 0.15,
            "topic_relevance": 0.20,
            "freshness": 0.10,
            "engagement_potential": 0.15,
        }

    async def get_random_articles_for_prioritization(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve random articles from the 'later' collection for prioritization.
        Prefer articles that already have priority scores.

        Args:
            limit: Maximum number of articles to retrieve

        Returns:
            List of article documents
        """
        # First try to get articles that already have priority scores
        pipeline = [
            {"$match": {"priority_score": {"$exists": True}}},  # Articles with priority scores
            {"$sample": {"size": limit}},  # Get random articles
        ]

        cursor = self.db.later.aggregate(pipeline)
        articles = await cursor.to_list(length=None)
        
        # If we don't have enough articles with scores, get some without scores
        if len(articles) < limit:
            remaining = limit - len(articles)
            pipeline = [
                {"$match": {"priority_score": {"$exists": False}}},  # Articles without priority scores
                {"$match": {"content": {"$exists": True}}},  # Ensure content field exists
                {"$sample": {"size": remaining}},  # Get random articles
            ]
            
            cursor = self.db.later.aggregate(pipeline)
            additional_articles = await cursor.to_list(length=None)
            articles.extend(additional_articles)

        return articles

    async def get_article_analysis(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Get pre-calculated analysis for an article.
        
        Args:
            article_id: The ID of the article
            
        Returns:
            Analysis document or None if not found
        """
        analysis = await self.db[self.analysis_collection].find_one({"article_id": article_id})
        return analysis
        
    async def enrich_articles_with_analysis(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Enrich articles with pre-calculated analysis data.
        
        Args:
            articles: List of article documents
            
        Returns:
            List of articles with analysis data
        """
        # Get all article IDs
        article_ids = [article["id"] for article in articles if "id" in article]
        
        # Fetch all analysis documents in one query
        analysis_cursor = self.db[self.analysis_collection].find(
            {"article_id": {"$in": article_ids}}
        )
        
        # Create a mapping of article_id to analysis
        analysis_map = {}
        async for analysis in analysis_cursor:
            analysis_map[analysis["article_id"]] = analysis
        
        # Enrich articles with analysis data
        for article in articles:
            article_id = article.get("id")
            if article_id and article_id in analysis_map:
                analysis = analysis_map[article_id]
                
                # Add analysis data to article
                article["priority_score"] = analysis.get("priority_score")
                article["component_scores"] = analysis.get("component_scores")
                article["readability"] = analysis.get("readability")
                article["information_density"] = analysis.get("information_density")
                article["topic_relevance"] = analysis.get("topic_relevance")
                article["freshness"] = analysis.get("freshness")
                article["engagement_potential"] = analysis.get("engagement_potential")
                article["extracted_content"] = analysis.get("extracted_content")
                article["analyzed_at"] = analysis.get("analyzed_at")
        
        return articles

    async def extract_content_for_articles(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract content for a list of articles.

        Args:
            articles: List of article documents

        Returns:
            List of articles with extracted content
        """
        result = []

        # Collect all article IDs
        article_ids = []
        article_id_map = {}

        for article_doc in articles:
            article_copy = article_doc.copy()
            if "_id" in article_copy and isinstance(article_copy["_id"], ObjectId):
                article_copy["_id"] = str(article_copy["_id"])

            # Convert MongoDB document to Article model
            try:
                article = Article.model_validate(article_copy)
                if article.id:
                    article_ids.append(article.id)
                    article_id_map[article.id] = article
                    article_doc["article_model"] = article
            except Exception as e:
                logger.error(
                    f"Error validating article {article_copy.get('_id')}: {str(e)}"
                )

        # Batch retrieve HTML content for all articles
        html_docs = {}
        if article_ids:
            cursor = self.db.later_html.find({"article_id": {"$in": article_ids}})
            async for html_doc in cursor:
                if "article_id" in html_doc and "html" in html_doc and html_doc["html"]:
                    html_docs[html_doc["article_id"]] = html_doc["html"]

            logger.info(
                f"Retrieved {len(html_docs)} HTML documents from later_html collection"
            )

        # Process each article with the retrieved HTML content
        for article_doc in articles:
            try:
                if "article_model" not in article_doc:
                    continue

                article = article_doc["article_model"]

                # Assign HTML content if available
                if article.id in html_docs:
                    logger.info(
                        f"Using HTML content from later_html for article {article.id}"
                    )
                    article.html_content = html_docs[article.id]

                # Extract content
                extracted_content = await self.content_extractor.extract_content(
                    article
                )

                # Add extracted content to the article document
                article_doc["extracted_content"] = extracted_content

                # Remove the temporary article_model field
                del article_doc["article_model"]

                # Add to result if content was successfully extracted
                if extracted_content:
                    result.append(article_doc)

            except Exception as e:
                logger.error(
                    f"Error processing article {article_doc.get('_id')}: {str(e)}"
                )
                # Remove the temporary article_model field if it exists
                if "article_model" in article_doc:
                    del article_doc["article_model"]

        return result

    async def analyze_readability(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Use pre-calculated readability metrics if available, otherwise calculate them.
        """
        for article in articles:
            # Check if readability metrics already exist
            if "readability" in article and article["readability"]:
                continue
                
            # Otherwise, calculate them
            content = article.get("extracted_content", "")
            if content:
                # Analyze readability
                readability_metrics = self.readability_analyzer.analyze(content)
                # Add readability metrics to article
                article["readability"] = readability_metrics
            else:
                # Default metrics for articles without content
                article["readability"] = {
                    "flesch_reading_ease": 0,
                    "smog_index": 0,
                    "coleman_liau_index": 0,
                    "automated_readability_index": 0,
                    "complexity_level": "Unknown",
                    "normalized_score": 5.0,
                }

        return articles

    async def analyze_information_density(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze information density for a list of articles with extracted content.

        Args:
            articles: List of article documents with extracted content

        Returns:
            List of articles with information density metrics
        """
        for article in articles:
            content = article.get("extracted_content", "")
            if content:
                # Analyze information density
                density_metrics = self.information_density_analyzer.analyze(content)

                # Add information density metrics to article
                article["information_density"] = density_metrics
            else:
                # Default metrics for articles without content
                article["information_density"] = {
                    "lexical_diversity": 0,
                    "fact_density": 0,
                    "concept_density": 0,
                    "key_concepts": [],
                    "normalized_score": 5.0,
                }

        return articles

    async def analyze_topic_relevance(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze topic relevance for a list of articles with extracted content.

        Args:
            articles: List of article documents with extracted content

        Returns:
            List of articles with topic relevance metrics
        """
        for article in articles:
            content = article.get("extracted_content", "")
            if content:
                # Analyze topic relevance
                topic_relevance_metrics = self.topic_relevance_analyzer.analyze(content)

                # Add topic relevance metrics to article
                article["topic_relevance"] = topic_relevance_metrics
            else:
                # Default metrics for articles without content
                article["topic_relevance"] = {
                    "top_topics": [],
                    "topic_matches": {},
                    "normalized_score": 5.0,
                }

        return articles

    async def analyze_freshness(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze content freshness for a list of articles.

        Args:
            articles: List of article documents with extracted content

        Returns:
            List of articles with freshness metrics
        """
        for article in articles:
            content = article.get("extracted_content", "")
            if content:
                # Get publication date if available
                published_date = None
                if "published_date" in article and article["published_date"]:
                    try:
                        # Handle millisecond timestamp
                        if isinstance(article["published_date"], int):
                            published_date = datetime.fromtimestamp(
                                article["published_date"] / 1000
                            )
                        # Handle datetime object
                        elif isinstance(article["published_date"], datetime):
                            published_date = article["published_date"]
                    except Exception as e:
                        logger.warning(f"Error parsing published_date: {str(e)}")

                # Determine category based on article metadata or topic relevance
                category = "default"
                if "category" in article and article["category"]:
                    category = article["category"]
                elif "topic_relevance" in article and article["topic_relevance"].get(
                    "top_topics"
                ):
                    # Map top topic to a category if possible
                    top_topic = (
                        article["topic_relevance"]["top_topics"][0]
                        if article["topic_relevance"]["top_topics"]
                        else None
                    )
                    if top_topic == "technology":
                        category = "technology"
                    elif top_topic == "science":
                        category = "science"
                    elif top_topic in ["politics", "business", "finance"]:
                        category = "news"
                    elif top_topic in ["education", "health"]:
                        category = "evergreen"

                # Analyze freshness
                freshness_metrics = self.freshness_analyzer.analyze(
                    content, published_date, category
                )

                # Add freshness metrics to article
                article["freshness"] = freshness_metrics
            else:
                # Default metrics for articles without content
                article["freshness"] = {
                    "age_days": 0,
                    "temporal_references_count": 0,
                    "decay_rate": 180,  # Default decay rate
                    "is_recent": False,
                    "normalized_score": 5.0,
                }

        return articles

    async def analyze_engagement_potential(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Analyze engagement potential for a list of articles.

        Args:
            articles: List of article documents with extracted content

        Returns:
            List of articles with engagement potential metrics
        """
        for article in articles:
            content = article.get("extracted_content", "")
            title = article.get("title", "")

            if content:
                # Analyze engagement potential
                engagement_metrics = self.engagement_analyzer.analyze(content, title)

                # Add engagement metrics to article
                article["engagement_potential"] = engagement_metrics
            else:
                # Default metrics for articles without content
                article["engagement_potential"] = {
                    "emotional_score": 0,
                    "narrative_score": 0,
                    "visual_score": 0,
                    "interactive_score": 0,
                    "emotion_counts": {"positive": 0, "negative": 0, "surprise": 0},
                    "normalized_score": 5.0,
                }

        return articles

    async def calculate_priority_scores(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Use pre-calculated priority scores if available, otherwise calculate them.
        """
        for article in articles:
            # Check if priority score already exists
            if "priority_score" in article and article["priority_score"] is not None:
                continue
                
            # Initialize component scores dictionary
            component_scores = {}

            # Get quality score (placeholder - to be implemented)
            # For now, use a default value of 7.0
            component_scores["quality"] = 7.0

            # Get information density score
            if "information_density" in article:
                component_scores["information_density"] = article[
                    "information_density"
                ].get("normalized_score", 5.0)
            else:
                component_scores["information_density"] = 5.0

            # Get readability score
            if "readability" in article:
                component_scores["readability"] = article["readability"].get(
                    "normalized_score", 5.0
                )
            else:
                component_scores["readability"] = 5.0

            # Get topic relevance score
            if "topic_relevance" in article:
                component_scores["topic_relevance"] = article["topic_relevance"].get(
                    "normalized_score", 5.0
                )
            else:
                component_scores["topic_relevance"] = 5.0

            # Get freshness score
            if "freshness" in article:
                component_scores["freshness"] = article["freshness"].get(
                    "normalized_score", 5.0
                )
            else:
                component_scores["freshness"] = 5.0

            # Get engagement potential score
            if "engagement_potential" in article:
                component_scores["engagement_potential"] = article[
                    "engagement_potential"
                ].get("normalized_score", 5.0)
            else:
                component_scores["engagement_potential"] = 5.0

            # Calculate weighted sum according to the formula in the spec
            priority_score = (
                sum(
                    score * self.component_weights[component]
                    for component, score in component_scores.items()
                )
                * 10
            )  # Scale to 0-100

            # Add priority score and component scores to article
            article["priority_score"] = round(priority_score, 1)
            article["component_scores"] = component_scores

        return articles

    async def format_prioritized_articles(
        self, articles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Format the prioritized articles according to the output format in the spec.

        Args:
            articles: List of article documents with priority scores

        Returns:
            List of formatted article results
        """
        formatted_articles = []

        for article in articles:
            # Convert ObjectId to string if present
            article_id = str(article.get("_id", "")) if article.get("_id") else ""

            # Ensure tags is always a dictionary
            tags = article.get("tags", {})
            if tags is None:
                tags = {}

            formatted_article = {
                # Original MongoDB fields
                "_id": article_id,
                "id": article.get("id", ""),
                "url": article.get("url", ""),
                "title": article.get("title", ""),
                "author": article.get("author", ""),
                "source": article.get("source", ""),
                "category": article.get("category", ""),
                "location": article.get("location", ""),
                "tags": tags,  # Use the validated tags value
                "site_name": article.get("site_name", ""),
                "word_count": article.get("word_count", 0),
                "created_at": article.get("created_at", None),
                "updated_at": article.get("updated_at", None),
                "published_date": article.get("published_date", 0),
                "summary": article.get("summary", ""),
                "image_url": article.get("image_url", ""),
                "content": article.get("content", ""),
                "source_url": article.get("source_url", ""),
                "notes": article.get("notes", ""),
                "parent_id": article.get("parent_id", None),
                "reading_progress": article.get("reading_progress", 0),
                "first_opened_at": article.get("first_opened_at", None),
                "last_opened_at": article.get("last_opened_at", None),
                "saved_at": article.get("saved_at", None),
                "last_moved_at": article.get("last_moved_at", None),
                # Prioritization fields
                "article_id": article_id,  # Duplicate for backward compatibility
                "priority_score": article.get("priority_score", 0),
                "component_scores": article.get("component_scores", {}),
            }

            formatted_articles.append(formatted_article)

        # Sort articles by priority score in descending order
        formatted_articles.sort(key=lambda x: x["priority_score"], reverse=True)

        return formatted_articles

    async def save_prioritization_results(self, articles: List[Dict[str, Any]]) -> None:
        """
        Save prioritization results back to the database.

        Args:
            articles: List of article documents with priority scores
        """
        for article in articles:
            article_id = article.get("_id")
            if not article_id:
                continue

            # Prepare update data - only include prioritization fields
            update_data = {
                "priority_score": article.get("priority_score", 0),
                "component_scores": article.get("component_scores", {}),
                "priority_score_updated_at": datetime.now(timezone.utc),
            }

            # Add analysis results if they exist
            if "readability" in article:
                update_data["readability"] = article["readability"]
            if "information_density" in article:
                update_data["information_density"] = article["information_density"]
            if "topic_relevance" in article:
                update_data["topic_relevance"] = article["topic_relevance"]
            if "freshness" in article:
                update_data["freshness"] = article["freshness"]
            if "engagement_potential" in article:
                update_data["engagement_potential"] = article["engagement_potential"]

            try:
                # Update the article in the database
                await self.db.later.update_one(
                    {"_id": article_id}, {"$set": update_data}
                )
            except Exception as e:
                logger.error(
                    f"Error saving prioritization results for article {article_id}: {str(e)}"
                )

    async def check_existing_scores(
        self, articles: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Check for existing scores and separate articles that need processing from those that don't.

        Args:
            articles: List of article documents

        Returns:
            Dictionary with 'to_process' and 'already_scored' lists
        """
        to_process = []
        already_scored = []

        for article in articles:
            # Check if article already has priority score
            if "priority_score" in article and article["priority_score"] is not None:
                already_scored.append(article)
            else:
                to_process.append(article)

        return {"to_process": to_process, "already_scored": already_scored}

    async def process_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process articles for prioritization, using pre-calculated analysis when available.
        
        Args:
            articles: List of article documents
            
        Returns:
            List of processed articles with priority scores
        """
        # Separate articles with and without analysis
        articles_without_analysis = [
            article for article in articles 
            if "priority_score" not in article or article["priority_score"] is None
        ]
        
        if articles_without_analysis:
            # Extract content for articles without analysis
            processed_articles = await self.extract_content_for_articles(articles_without_analysis)
            
            # Run all analysis steps
            analyzed_articles = await self.analyze_readability(processed_articles)
            analyzed_articles = await self.analyze_information_density(analyzed_articles)
            analyzed_articles = await self.analyze_topic_relevance(analyzed_articles)
            analyzed_articles = await self.analyze_freshness(analyzed_articles)
            analyzed_articles = await self.analyze_engagement_potential(analyzed_articles)
            
            # Calculate priority scores
            prioritized_articles = await self.calculate_priority_scores(analyzed_articles)
            
            # Replace the original articles without analysis with the analyzed ones
            articles_with_analysis = [
                article for article in articles 
                if "priority_score" in article and article["priority_score"] is not None
            ]
            
            articles = articles_with_analysis + prioritized_articles
        
        return articles


@router.get("/prioritized", response_model=List[Dict[str, Any]])
async def get_prioritized_articles(
    limit: int = Query(
        default=10, ge=1, le=50, description="Number of articles to return"
    ),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Get prioritized articles based on quality, relevance, and other factors.
    """
    try:
        service = PrioritizationService(db)

        # Get random articles for prioritization
        articles = await service.get_random_articles_for_prioritization(limit)

        # Process articles (using pre-calculated analysis when available)
        processed_articles = await service.process_articles(articles)

        # Format articles for output
        formatted_articles = await service.format_prioritized_articles(processed_articles)

        # Sort by priority score (descending)
        formatted_articles.sort(key=lambda x: x["priority_score"], reverse=True)

        # Return top N articles
        return formatted_articles[:limit]

    except Exception as e:
        logger.error(f"Error in get_prioritized_articles: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving prioritized articles: {str(e)}"
        )


@router.get("/sample", response_model=Dict[str, Any])
async def get_prioritization_sample(
    limit: int = Query(
        default=10, ge=1, le=20, description="Number of articles to return"
    ),
    sample_size: int = Query(
        default=25,
        ge=10,
        le=200,
        description="Number of articles to sample and process",
    ),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Get a sample of articles with prioritization scores.

    Processes a larger sample of articles and returns the top N (default 10)
    with highest priority scores. Also includes metadata about min/max scores.
    """
    try:
        service = PrioritizationService(db)

        # Get random articles (larger sample)
        articles = await service.get_random_articles_for_prioritization(sample_size)

        # Separate articles with and without scores
        articles_with_scores = []
        articles_without_scores = []

        for article in articles:
            if "priority_score" in article and article["priority_score"] is not None:
                articles_with_scores.append(article)
            else:
                articles_without_scores.append(article)

        # Log counts
        logger.info(f"Found {len(articles_with_scores)} articles with existing scores")
        logger.info(
            f"Processing {len(articles_without_scores)} articles without scores"
        )

        # Process only articles without scores
        if articles_without_scores:
            # Extract content for articles
            processed_articles = await service.extract_content_for_articles(
                articles_without_scores
            )

            # Analyze readability
            analyzed_articles = await service.analyze_readability(processed_articles)

            # Analyze information density
            analyzed_articles = await service.analyze_information_density(
                analyzed_articles
            )

            # Analyze topic relevance
            analyzed_articles = await service.analyze_topic_relevance(analyzed_articles)

            # Analyze freshness
            analyzed_articles = await service.analyze_freshness(analyzed_articles)

            # Analyze engagement potential
            analyzed_articles = await service.analyze_engagement_potential(
                analyzed_articles
            )

            # Calculate priority scores
            prioritized_articles = await service.calculate_priority_scores(
                analyzed_articles
            )

            # Save results to database
            await service.save_prioritization_results(prioritized_articles)
            logger.info(
                f"Saved prioritization results for {len(prioritized_articles)} articles"
            )

            # Combine with articles that already had scores
            all_articles = articles_with_scores + prioritized_articles
        else:
            all_articles = articles_with_scores

        # Format articles for output
        formatted_articles = await service.format_prioritized_articles(all_articles)

        # Get min and max scores from all processed articles
        all_scores = [article["priority_score"] for article in formatted_articles]
        min_score = min(all_scores) if all_scores else 0
        max_score = max(all_scores) if all_scores else 0

        # Take only the top N articles
        top_articles = formatted_articles[:limit]

        # Add metadata about scores
        response = {
            "articles": top_articles,
            "metadata": {
                "total_processed": len(formatted_articles),
                "min_score": min_score,
                "max_score": max_score,
                "returned_count": len(top_articles),
            },
        }

        return response

    except Exception as e:
        logger.error(f"Error in get_prioritization_sample: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving prioritization sample: {str(e)}"
        )


@router.get("/low-priority", response_model=Dict[str, Any])
async def get_low_priority_articles(
    limit: int = Query(
        default=10, ge=1, le=50, description="Number of articles to return"
    ),
    min_age_days: int = Query(
        default=1095, ge=0, description="Minimum age of articles in days"
    ),
    db: AsyncIOMotorDatabase = Depends(get_database),
):
    """
    Get articles that are candidates for archiving without reading.

    Identifies articles with low priority scores, old publication dates,
    failed content extraction, or other indicators that suggest they
    may not be worth reading.
    """
    try:
        service = PrioritizationService(db)

        # Calculate the cutoff date based on min_age_days
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=min_age_days)
        cutoff_timestamp = int(
            cutoff_date.timestamp() * 1000
        )  # Convert to milliseconds

        # Query for low priority articles with specific criteria
        pipeline = [
            {
                "$match": {
                    "$or": [
                        # Articles with low priority scores (using a fixed threshold)
                        {"priority_score": {"$lte": 30.0}},
                        # Articles with old publication dates
                        {"published_date": {"$lt": cutoff_timestamp, "$ne": None}},
                        # Articles with failed content extraction
                        {"content_extraction_failed": True},
                        # Articles with very low component scores
                        {"component_scores.readability": {"$lte": 3.0}},
                        {"component_scores.information_density": {"$lte": 3.0}},
                        {"component_scores.topic_relevance": {"$lte": 3.0}},
                        # Articles with broken URLs or missing content
                        {"content": {"$in": [None, "", "<html>", "<body>"]}},
                        # Minimal content length
                        {"word_count": {"$lt": 300, "$ne": None}},
                        # Long-term neglect (saved over 6 months ago, never opened)
                        {
                            "saved_at": {
                                "$lt": datetime.now(timezone.utc) - timedelta(days=180)
                            },
                            "first_opened_at": None,
                        },
                        # Stale interest (not opened in over a year)
                        {
                            "last_opened_at": {
                                "$lt": datetime.now(timezone.utc) - timedelta(days=365)
                            }
                        },
                        # Multiple abandoned attempts (opened multiple times but low progress)
                        {
                            "reading_progress": {"$lt": 0.2},
                            "first_opened_at": {"$ne": None},
                            "last_opened_at": {"$ne": None, "$ne": "$first_opened_at"},
                        },
                        # Missing critical metadata
                        {
                            "$or": [
                                {"title": {"$in": [None, ""]}},
                                {"author": {"$in": [None, ""]}},
                                {"url": {"$in": [None, ""]}},
                            ]
                        },
                        # Empty tags
                        {"tags": {"$in": [None, {}, []]}},
                    ]
                }
            },
            {"$sort": {"priority_score": 1}},  # Sort by priority score ascending
            {"$limit": limit * 2},  # Get more than needed for processing
        ]

        cursor = db.later.aggregate(pipeline)
        articles = await cursor.to_list(length=None)

        # Process articles without scores if needed
        articles_with_scores = []
        articles_without_scores = []

        for article in articles:
            if "priority_score" in article and article["priority_score"] is not None:
                articles_with_scores.append(article)
            else:
                articles_without_scores.append(article)

        # Process articles without scores
        if articles_without_scores:
            # Extract content for articles
            processed_articles = await service.extract_content_for_articles(
                articles_without_scores
            )

            # Run all analysis steps
            analyzed_articles = await service.analyze_readability(processed_articles)
            analyzed_articles = await service.analyze_information_density(
                analyzed_articles
            )
            analyzed_articles = await service.analyze_topic_relevance(analyzed_articles)
            analyzed_articles = await service.analyze_freshness(analyzed_articles)
            analyzed_articles = await service.analyze_engagement_potential(
                analyzed_articles
            )

            # Calculate priority scores
            prioritized_articles = await service.calculate_priority_scores(
                analyzed_articles
            )

            # Save results to database
            await service.save_prioritization_results(prioritized_articles)

            # Combine with articles that already had scores
            all_articles = articles_with_scores + prioritized_articles
        else:
            all_articles = articles_with_scores

        # Format articles for output
        formatted_articles = await service.format_prioritized_articles(all_articles)

        # Sort by priority score (ascending) to get the lowest scores first
        formatted_articles.sort(key=lambda x: x["priority_score"])

        # Add archive recommendation reason
        for article in formatted_articles:
            reasons = []

            # Check for low priority score (using fixed threshold of 30.0)
            if article.get("priority_score", 100) <= 30.0:
                reasons.append("low_priority_score")

            # Check for old publication date
            pub_date = article.get("published_date")
            if pub_date and (isinstance(pub_date, int) and pub_date < cutoff_timestamp):
                reasons.append("old_publication_date")

            # Check for failed content extraction
            if article.get("content_extraction_failed") or not article.get("content"):
                reasons.append("content_extraction_failed")

            # Check for low component scores
            component_scores = article.get("component_scores", {})
            if component_scores.get("readability", 10) <= 3.0:
                reasons.append("low_readability")
            if component_scores.get("information_density", 10) <= 3.0:
                reasons.append("low_information_density")
            if component_scores.get("topic_relevance", 10) <= 3.0:
                reasons.append("low_topic_relevance")

            # Check for long-term neglect
            saved_at = article.get("saved_at")
            first_opened_at = article.get("first_opened_at")
            if (
                saved_at
                and not first_opened_at
                and isinstance(saved_at, datetime)
                and (datetime.now(timezone.utc) - saved_at).days > 180
            ):
                reasons.append("long_term_neglect")

            # Check for stale interest
            last_opened_at = article.get("last_opened_at")
            if (
                last_opened_at
                and isinstance(last_opened_at, datetime)
                and (datetime.now(timezone.utc) - last_opened_at).days > 365
            ):
                reasons.append("stale_interest")

            # Check for abandoned reading attempts
            reading_progress = article.get("reading_progress", 1.0)
            if (
                reading_progress < 0.2
                and first_opened_at
                and last_opened_at
                and first_opened_at != last_opened_at
            ):
                reasons.append("abandoned_reading")

            # Check for missing critical metadata
            if (
                not article.get("title")
                or not article.get("author")
                or not article.get("url")
            ):
                reasons.append("missing_critical_metadata")

            # Add reasons to article
            article["archive_reasons"] = reasons

        # Take only the top N articles
        top_low_priority = formatted_articles[:limit]

        # Add metadata about scores
        response = {
            "articles": top_low_priority,
            "metadata": {
                "total_processed": len(formatted_articles),
                "returned_count": len(top_low_priority),
                "criteria": {
                    "min_age_days": min_age_days,
                },
            },
        }

        return response

    except Exception as e:
        logger.error(f"Error in get_low_priority_articles: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving low priority articles: {str(e)}"
        )
