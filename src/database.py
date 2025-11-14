"""
MongoDB database module for user management
"""
import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, DuplicateKeyError

import config

logger = logging.getLogger(__name__)


class Database:
    """MongoDB database handler"""
    
    def __init__(self):
        self.client = None
        self.db = None
        self.users_collection = None
    
    def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(config.MONGODB_URL, serverSelectionTimeoutMS=5000)
            # Verify connection
            self.client.admin.command('ping')
            self.db = self.client[config.MONGODB_DB_NAME]
            self.users_collection = self.db['users']
            
            # Create indexes
            self.users_collection.create_index('user_id', unique=True)
            
            logger.info("Successfully connected to MongoDB")
            return True
        except ServerSelectionTimeoutError:
            logger.error("Failed to connect to MongoDB: Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")
    
    def add_user(self, user_id: int, first_name: str = None, last_name: str = None, 
                 username: str = None) -> bool:
        """Add a new user to database"""
        try:
            user_data = {
                'user_id': user_id,
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'joined_at': datetime.utcnow(),
                'last_active': datetime.utcnow(),
                'downloads_count': 0,
            }
            self.users_collection.insert_one(user_data)
            logger.info(f"Added new user: {user_id}")
            return True
        except DuplicateKeyError:
            # User already exists, update last active
            self.update_last_active(user_id)
            return True
        except Exception as e:
            logger.error(f"Error adding user {user_id}: {e}")
            return False
    
    def user_exists(self, user_id: int) -> bool:
        """Check if user exists"""
        try:
            return self.users_collection.find_one({'user_id': user_id}) is not None
        except Exception as e:
            logger.error(f"Error checking user existence: {e}")
            return False
    
    def update_last_active(self, user_id: int) -> bool:
        """Update user's last active timestamp"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$set': {'last_active': datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error updating last active for user {user_id}: {e}")
            return False
    
    def increment_download_count(self, user_id: int) -> bool:
        """Increment user's download count"""
        try:
            self.users_collection.update_one(
                {'user_id': user_id},
                {'$inc': {'downloads_count': 1}},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error incrementing download count for user {user_id}: {e}")
            return False
    
    def get_all_user_ids(self) -> list:
        """Get all user IDs from database"""
        try:
            users = self.users_collection.find({}, {'user_id': 1})
            return [user['user_id'] for user in users]
        except Exception as e:
            logger.error(f"Error fetching all user IDs: {e}")
            return []
    
    def get_user_stats(self, user_id: int) -> dict:
        """Get user statistics"""
        try:
            user = self.users_collection.find_one({'user_id': user_id})
            if user:
                return {
                    'user_id': user.get('user_id'),
                    'joined_at': user.get('joined_at'),
                    'downloads_count': user.get('downloads_count', 0),
                    'last_active': user.get('last_active'),
                }
            return None
        except Exception as e:
            logger.error(f"Error fetching user stats for {user_id}: {e}")
            return None
    
    def get_total_users(self) -> int:
        """Get total number of users"""
        try:
            return self.users_collection.count_documents({})
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0


# Global database instance
db = Database()
