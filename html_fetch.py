import os
from dotenv import load_dotenv

from src.api.client import ReadwiseClient
from src.db.mongo_client import MongoDBClient
from src.utils.logger import logger

def fetch_html_content():
    """Fetch HTML content for up to 50 articles in the 'later' location"""
    load_dotenv()
    
    # Initialize clients
    readwise_client = ReadwiseClient(os.getenv('READWISE_TOKEN'))
    mongo_client = MongoDBClient(os.getenv('MONGODB_URI'))
    
    # Log database and collection information
    db_name = os.getenv('MONGODB_DATABASE', 'readwise_reader')
    collection_name = os.getenv('MONGODB_LATER_HTML_COLLECTION', 'later_html')
    logger.info(f"Using database: {db_name}, collection: {collection_name}")
    
    # Get the maximum number of documents to keep (default to 6000 if not specified)
    max_documents = int(os.getenv('MAX_HTML_DOCUMENTS', '6000'))
    logger.info(f"Maximum documents to keep: {max_documents}")
    
    # Log initial collection stats
    try:
        initial_count = mongo_client.get_document_count('later_html')
        logger.info(f"Initial document count in {collection_name}: {initial_count}")
        
        initial_stats = mongo_client.get_collection_stats('later_html')
        logger.info(f"Initial collection stats: {initial_stats}")
    except Exception as e:
        logger.error(f"Error getting initial collection stats: {e}")
        initial_count = 0
    
    # Fetch documents with HTML content from 'later' location, limited to 50
    logger.info("Starting to fetch documents with HTML content...")
    documents = readwise_client.fetch_reader_document_list(
        location='later', 
        limit=5000, 
        with_html_content=True
    )
    
    logger.info(f"Fetched {len(documents)} documents with HTML content from 'later'")
    
    # Check if HTML content is present
    html_count = sum(1 for doc in documents if doc.get('html_content'))
    logger.info(f"Documents with HTML content: {html_count}/{len(documents)}")
    
    # Sample HTML content length for the first document (if available)
    if documents and 'html_content' in documents[0] and documents[0]['html_content']:
        html_length = len(documents[0]['html_content'])
        logger.info(f"Sample HTML content length (first document): {html_length} characters")
        logger.info(f"Sample document title: '{documents[0].get('title', 'No title')}'")
    
    # Store in MongoDB
    logger.info(f"Storing documents in MongoDB collection: {collection_name}")
    added, removed = mongo_client.sync_documents_with_html('later', documents)
    
    # Trim collection if needed
    trimmed = mongo_client.trim_collection_to_size('later_html', max_documents)
    if trimmed > 0:
        logger.info(f"Trimmed {trimmed} old documents to stay under the {max_documents} document limit")
    
    logger.info(f"HTML sync complete:")
    logger.info(f"Total documents processed: {len(documents)}")
    logger.info(f"Total documents added/updated: {added}")
    logger.info(f"Total documents removed during sync: {removed}")
    logger.info(f"Total documents trimmed to stay under limit: {trimmed}")
    
    # Log final collection stats
    try:
        final_count = mongo_client.get_document_count('later_html')
        logger.info(f"Final document count in {collection_name}: {final_count}")
        logger.info(f"Net change in document count: {final_count - initial_count}")
        
        final_stats = mongo_client.get_collection_stats('later_html')
        logger.info(f"Final collection stats: {final_stats}")
    except Exception as e:
        logger.error(f"Error getting final collection stats: {e}")

if __name__ == "__main__":
    fetch_html_content() 