import os
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timezone
from typing import List, Dict, Any

from src.api.client import ReadwiseClient
from src.db.mongo_client import MongoDBClient
from src.utils.logger import logger
from src.relevance.content_extractor import ContentExtractor
from src.relevance.readability_analyzer import ReadabilityAnalyzer
from src.relevance.information_density_analyzer import InformationDensityAnalyzer
from src.relevance.topic_relevance_analyzer import TopicRelevanceAnalyzer
from src.relevance.freshness_analyzer import FreshnessAnalyzer
from src.relevance.engagement_analyzer import EngagementAnalyzer
from src.relevance.article import Article

# Component weights for priority score calculation
COMPONENT_WEIGHTS = {
    "quality": 0.25,
    "information_density": 0.15,
    "readability": 0.15,
    "topic_relevance": 0.20,
    "freshness": 0.10,
    "engagement_potential": 0.15,
}

async def fetch_and_analyze():
    """Fetch articles from API, analyze them, and save results to MongoDB"""
    load_dotenv()
    
    # Initialize clients
    readwise_client = ReadwiseClient(os.getenv('READWISE_TOKEN'))
    mongo_client = MongoDBClient(os.getenv('MONGODB_URI'))
    
    # Initialize analyzers
    content_extractor = ContentExtractor()
    readability_analyzer = ReadabilityAnalyzer()
    information_density_analyzer = InformationDensityAnalyzer()
    topic_relevance_analyzer = TopicRelevanceAnalyzer()
    freshness_analyzer = FreshnessAnalyzer()
    engagement_analyzer = EngagementAnalyzer()
    
    # Log database information
    db_name = os.getenv('MONGODB_DATABASE', 'readwise_reader')
    later_collection = os.getenv('MONGODB_LATER_COLLECTION', 'later')
    
    logger.info(f"Using database: {db_name}")
    logger.info(f"Later collection: {later_collection}")
    
    # Get batch size for analysis
    batch_size = int(os.getenv('ANALYSIS_BATCH_SIZE', '25000'))
    logger.info(f"Analysis batch size: {batch_size}")
    
    # Fetch documents from Readwise API with HTML content
    logger.info("Fetching articles from Readwise API...")
    documents = readwise_client.fetch_reader_document_list(
        location='later', 
        limit=batch_size,
        with_html_content=True
    )
    
    logger.info(f"Fetched {len(documents)} articles from Readwise API")
    
    # Check if HTML content is present
    html_count = sum(1 for doc in documents if doc.get('html_content'))
    logger.info(f"Articles with HTML content: {html_count}/{len(documents)}")
    
    # Check which articles already have analysis in MongoDB
    collection = mongo_client.db[later_collection]
    article_ids = [doc['id'] for doc in documents]
    existing_articles = list(collection.find(
        {"id": {"$in": article_ids}, "priority_score": {"$exists": True}},
        {"id": 1, "priority_score": 1, "analyzed_at": 1}
    ))
    
    existing_ids = {article['id'] for article in existing_articles}
    logger.info(f"Found {len(existing_ids)} articles that already have analysis scores")
    
    # Now analyze the articles
    logger.info("Starting article analysis...")
    analyzed_count = 0
    skipped_count = 0
    
    for doc in documents:
        try:
            # Check if article already has analysis
            if doc['id'] in existing_ids:
                existing = next(a for a in existing_articles if a['id'] == doc['id'])
                analyzed_at = existing.get('analyzed_at')
                analyzed_time = analyzed_at.strftime('%Y-%m-%d %H:%M:%S') if analyzed_at else 'unknown time'
                logger.info(f"Skipping article {doc['id']} - {doc.get('title', 'No title')}: "
                           f"Already analyzed (score: {existing.get('priority_score')}) at {analyzed_time}")
                skipped_count += 1
                continue
            
            # Ensure word_count is an integer
            word_count = 0
            if 'word_count' in doc and doc['word_count'] is not None:
                try:
                    word_count = int(doc['word_count'])
                except (ValueError, TypeError):
                    word_count = 0
            
            # Create Article object with validated word_count
            article = Article(
                id=doc['id'],
                readwise_id=doc['id'],
                url=doc.get('url', ''),
                title=doc.get('title', ''),
                author=doc.get('author', ''),
                source=doc.get('source'),
                category=doc.get('category', 'default'),
                location=doc.get('location', 'later'),
                tags=doc.get('tags', {}),
                site_name=doc.get('site_name', ''),
                word_count=word_count,  # Use the validated word_count
                created_at=datetime.fromisoformat(doc.get('created_at')) if isinstance(doc.get('created_at'), str) else doc.get('created_at', datetime.now(timezone.utc)),
                updated_at=datetime.fromisoformat(doc.get('updated_at')) if isinstance(doc.get('updated_at'), str) else doc.get('updated_at', datetime.now(timezone.utc)),
                published_date=doc.get('published_date'),
                summary=doc.get('summary'),
                image_url=doc.get('image_url'),
                content=doc.get('content'),
                source_url=doc.get('source_url'),
                notes=doc.get('notes', ''),
                parent_id=doc.get('parent_id'),
                reading_progress=doc.get('reading_progress', 0.0),
                first_opened_at=datetime.fromisoformat(doc['first_opened_at']) if isinstance(doc.get('first_opened_at'), str) and doc.get('first_opened_at') else doc.get('first_opened_at'),
                last_opened_at=datetime.fromisoformat(doc['last_opened_at']) if isinstance(doc.get('last_opened_at'), str) and doc.get('last_opened_at') else doc.get('last_opened_at'),
                saved_at=datetime.fromisoformat(doc['saved_at']) if isinstance(doc.get('saved_at'), str) and doc.get('saved_at') else doc.get('saved_at', datetime.now(timezone.utc)),
                last_moved_at=datetime.fromisoformat(doc['last_moved_at']) if isinstance(doc.get('last_moved_at'), str) and doc.get('last_moved_at') else doc.get('last_moved_at', datetime.now(timezone.utc)),
            )
            
            # Add HTML content if available
            if 'html_content' in doc and doc['html_content']:
                article.html_content = doc['html_content']
            
            # Extract content
            extracted_content = await content_extractor.extract_content(article)
            if not extracted_content:
                logger.warning(f"Could not extract content for article {article.id}")
                continue
            
            # Run all analysis components
            readability_metrics = readability_analyzer.analyze(extracted_content)
            density_metrics = information_density_analyzer.analyze(extracted_content)
            topic_metrics = topic_relevance_analyzer.analyze(extracted_content)
            
            # Get publication date if available
            published_date = None
            if article.published_date:
                try:
                    # Handle millisecond timestamp
                    if isinstance(article.published_date, int):
                        published_date = datetime.fromtimestamp(article.published_date / 1000)
                except Exception as e:
                    logger.warning(f"Error parsing published_date: {str(e)}")
            
            # Determine category for freshness analysis
            category = article.category if article.category else "default"
            if topic_metrics.get("top_topics"):
                top_topic = topic_metrics["top_topics"][0] if topic_metrics["top_topics"] else None
                if top_topic == "technology":
                    category = "technology"
                elif top_topic == "science":
                    category = "science"
                elif top_topic in ["politics", "business", "finance"]:
                    category = "news"
                elif top_topic in ["education", "health"]:
                    category = "evergreen"
            
            freshness_metrics = freshness_analyzer.analyze(
                extracted_content, published_date, category
            )
            
            engagement_metrics = engagement_analyzer.analyze(
                extracted_content, article.title
            )
            
            # Calculate priority score
            component_scores = {
                "quality": 7.0,  # Default quality score
                "information_density": density_metrics.get("normalized_score", 5.0),
                "readability": readability_metrics.get("normalized_score", 5.0),
                "topic_relevance": topic_metrics.get("normalized_score", 5.0),
                "freshness": freshness_metrics.get("normalized_score", 5.0),
                "engagement_potential": engagement_metrics.get("normalized_score", 5.0),
            }
            
            priority_score = sum(
                score * COMPONENT_WEIGHTS[component]
                for component, score in component_scores.items()
            ) * 10  # Scale to 0-100
            
            # When creating the update data, exclude extracted_content
            update_data = {
                "priority_score": round(priority_score, 1),
                "component_scores": component_scores,
                "readability": readability_metrics,
                "information_density": density_metrics,
                "topic_relevance": topic_metrics,
                "freshness": freshness_metrics,
                "engagement_potential": engagement_metrics,
                "analyzed_at": datetime.now(timezone.utc)
            }
            
            # Create a clean copy of the document without html_content and extracted_content
            clean_doc = {k: v for k, v in doc.items() if k != 'html_content'}
            clean_doc.update(update_data)
            
            # Save or update the document in MongoDB
            collection.update_one(
                {"id": article.id},
                {"$set": clean_doc},
                upsert=True
            )
            
            analyzed_count += 1
            logger.info(f"Analyzed and saved article: {article.id} - {article.title} (score: {round(priority_score, 1)})")
            
        except Exception as e:
            logger.error(f"Error analyzing article {doc.get('id')}: {str(e)}")
    
    logger.info(f"Analysis complete: {analyzed_count} articles analyzed and saved to MongoDB, {skipped_count} skipped")

if __name__ == "__main__":
    asyncio.run(fetch_and_analyze()) 