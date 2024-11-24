import os
from dotenv import load_dotenv

from src.api.client import ReadwiseClient
from src.db.mongo_client import MongoDBClient
from src.utils.logger import logger

def validate_environment():
    """Validate that all required environment variables are set"""
    required_vars = [
        'READWISE_TOKEN', 
        'MONGODB_URI',
        'MONGODB_DATABASE',
        'MONGODB_LATER_COLLECTION',
        'MONGODB_ARCHIVE_COLLECTION'
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

def main():
    """Main function to fetch documents and sync with MongoDB"""
    load_dotenv()
    validate_environment()
    
    # Initialize clients
    readwise_client = ReadwiseClient(os.getenv('READWISE_TOKEN'))
    mongo_client = MongoDBClient(os.getenv('MONGODB_URI'))
    
    locations = ['later', 'archive']
    total_documents = 0
    total_added = 0
    total_removed = 0
    
    for location in locations:
        # Fetch documents from Readwise
        documents = readwise_client.fetch_reader_document_list(location)
        logger.info(f"{len(documents)} documents fetched from {location}")
        total_documents += len(documents)
        
        # Sync with MongoDB
        added, removed = mongo_client.sync_documents(location, documents)
        total_added += added
        total_removed += removed
    
    logger.info(f"Sync complete:")
    logger.info(f"Total documents processed: {total_documents}")
    logger.info(f"Total documents added: {total_added}")
    logger.info(f"Total documents removed: {total_removed}")

if __name__ == "__main__":
    main()