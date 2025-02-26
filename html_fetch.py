import os
from dotenv import load_dotenv

from src.api.client import ReadwiseClient
from src.db.mongo_client import MongoDBClient
from src.utils.logger import logger

def fetch_html_content():
    """Fetch HTML content for up to 500 articles in the 'later' location"""
    load_dotenv()
    
    # Initialize clients
    readwise_client = ReadwiseClient(os.getenv('READWISE_TOKEN'))
    mongo_client = MongoDBClient(os.getenv('MONGODB_URI'))
    
    # Fetch documents with HTML content from 'later' location, limited to 500
    documents = readwise_client.fetch_reader_document_list(
        location='later', 
        limit=500, 
        with_html_content=True
    )
    
    logger.info(f"Fetched {len(documents)} documents with HTML content from 'later'")
    
    # Store in MongoDB
    added, removed = mongo_client.sync_documents_with_html('later', documents)
    
    logger.info(f"HTML sync complete:")
    logger.info(f"Total documents processed: {len(documents)}")
    logger.info(f"Total documents added/updated: {added}")
    logger.info(f"Total documents removed: {removed}")

if __name__ == "__main__":
    fetch_html_content() 