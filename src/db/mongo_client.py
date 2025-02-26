from typing import List, Dict, Tuple
from pymongo import MongoClient
import os
from ..utils.logger import logger

class MongoDBClient:
    def __init__(self, connection_string: str):
        self.client = MongoClient(connection_string)
        self.db = self.client[os.getenv('MONGODB_DATABASE', 'readwise_reader')]
        self.collections = {
            'later': os.getenv('MONGODB_LATER_COLLECTION', 'later'),
            'archive': os.getenv('MONGODB_ARCHIVE_COLLECTION', 'archive')
        }
    
    def sync_documents(self, location: str, documents: List[Dict]):
        """Sync documents with MongoDB collection"""
        collection = self.db[self.collections[location]]
        
        # Get existing document IDs
        existing_ids = {doc['id'] for doc in collection.find({}, {'id': 1})}
        new_ids = {doc['id'] for doc in documents}
        
        # Calculate changes
        to_insert = [doc for doc in documents if doc['id'] not in existing_ids]
        to_delete = [doc_id for doc_id in existing_ids if doc_id not in new_ids]
        
        # Apply changes
        if to_insert:
            collection.insert_many(to_insert)
            logger.info(f"Added {len(to_insert)} new documents to {location}")
            
        if to_delete:
            collection.delete_many({'id': {'$in': to_delete}})
            logger.info(f"Removed {len(to_delete)} documents from {location}")
            
        return len(to_insert), len(to_delete)

    def get_collection_stats(self, collection_name: str) -> Dict:
        """Get statistics for a collection"""
        if collection_name not in self.collections:
            collection_name = os.getenv(f'MONGODB_{collection_name.upper()}_COLLECTION', collection_name)
        
        collection = self.db[collection_name]
        
        stats = {
            'document_count': collection.count_documents({}),
            'size': self.db.command('collstats', collection_name).get('size', 0),
            'avg_document_size': self.db.command('collstats', collection_name).get('avgObjSize', 0)
        }
        
        return stats 

    def get_document_count(self, collection_name: str) -> int:
        """Get the number of documents in a collection"""
        if collection_name not in self.collections:
            collection_name = os.getenv(f'MONGODB_{collection_name.upper()}_COLLECTION', collection_name)
        
        collection = self.db[collection_name]
        return collection.count_documents({}) 