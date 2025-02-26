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

    def sync_documents_with_html(self, location: str, documents: List[Dict]) -> Tuple[int, int]:
        """Sync documents with HTML content to a dedicated MongoDB collection (append-only mode)"""
        collection_name = f"{location}_html"
        if collection_name not in self.collections:
            self.collections[collection_name] = os.getenv(f'MONGODB_{location.upper()}_HTML_COLLECTION', f'{location}_html')
        
        collection = self.db[self.collections[collection_name]]
        
        # Get existing document IDs
        existing_ids = {doc['id'] for doc in collection.find({}, {'id': 1})}
        
        # Calculate changes (only additions/updates, no removals)
        to_upsert = documents  # We'll use upsert for all documents to handle updates
        
        # Apply changes
        for doc in to_upsert:
            collection.update_one(
                {'id': doc['id']},
                {'$set': doc},
                upsert=True
            )
        
        # Count how many were actually new vs updates
        new_docs = sum(1 for doc in documents if doc['id'] not in existing_ids)
        updated_docs = len(documents) - new_docs
        
        logger.info(f"Added {new_docs} new documents to {collection_name}")
        logger.info(f"Updated {updated_docs} existing documents in {collection_name}")
        
        return new_docs, 0  # Return new docs count and 0 for removed

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

    def trim_collection_to_size(self, collection_name: str, max_documents: int = 6000) -> int:
        """Trim a collection to keep only the most recent documents
        
        Args:
            collection_name: Name of the collection to trim
            max_documents: Maximum number of documents to keep
            
        Returns:
            Number of documents removed
        """
        if collection_name not in self.collections:
            collection_name = os.getenv(f'MONGODB_{collection_name.upper()}_COLLECTION', collection_name)
        
        collection = self.db[collection_name]
        
        # Count documents in the collection
        total_docs = collection.count_documents({})
        
        # If we're under the limit, no need to remove anything
        if total_docs <= max_documents:
            return 0
        
        # Calculate how many documents to remove
        docs_to_remove = total_docs - max_documents
        
        # Find the oldest documents based on saved_at or created_at field
        # We'll try saved_at first, then fall back to created_at
        try:
            # Find the oldest documents by saved_at
            oldest_docs = list(collection.find(
                {"saved_at": {"$ne": None}}, 
                {"_id": 1}
            ).sort("saved_at", 1).limit(docs_to_remove))
            
            if len(oldest_docs) < docs_to_remove:
                # If we don't have enough documents with saved_at, use created_at for the rest
                remaining = docs_to_remove - len(oldest_docs)
                oldest_by_created = list(collection.find(
                    {"_id": {"$nin": [doc["_id"] for doc in oldest_docs]}}, 
                    {"_id": 1}
                ).sort("created_at", 1).limit(remaining))
                
                oldest_docs.extend(oldest_by_created)
        except Exception:
            # If there was an error with the above approach, simply sort by _id
            # (MongoDB ObjectIDs have a timestamp component)
            oldest_docs = list(collection.find({}, {"_id": 1}).sort("_id", 1).limit(docs_to_remove))
        
        # Remove the oldest documents
        if oldest_docs:
            collection.delete_many({"_id": {"$in": [doc["_id"] for doc in oldest_docs]}})
            logger.info(f"Removed {len(oldest_docs)} oldest documents from {collection_name} to stay under size limit")
            return len(oldest_docs)
        
        return 0 