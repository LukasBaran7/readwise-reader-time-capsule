import os
from dotenv import load_dotenv

from src.api.client import ReadwiseClient
from src.utils.logger import logger

def validate_environment():
    """Validate that all required environment variables are set"""
    if not os.getenv('READWISE_TOKEN'):
        raise ValueError("READWISE_TOKEN environment variable is not set. Please set it in .env file")

def main():
    """Main function to fetch documents from different locations"""
    load_dotenv()
    validate_environment()
    
    client = ReadwiseClient(os.getenv('READWISE_TOKEN'))
    locations = ['later', 'archive']
    total_documents = 0
    
    for location in locations:
        documents = client.fetch_reader_document_list(location)
        logger.info(f"{len(documents)} documents fetched from {location}")
        total_documents += len(documents)
        
    logger.info(f"Total documents fetched: {total_documents}")

if __name__ == "__main__":
    main()