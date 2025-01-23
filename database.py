import sqlite3
from typing import List, Tuple, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name: str):
        """Initialize database connection"""
        self.conn = sqlite3.connect(db_name)
        self.create_tables()
        logger.info(f"📂 Database initialized: {db_name}")

    def create_tables(self):
        """Create necessary database tables"""
        cursor = self.conn.cursor()
        
        # Main sessions table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            phone TEXT PRIMARY KEY,
            session_string TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            first_name TEXT,
            last_name TEXT,
            status TEXT DEFAULT 'active',
            total_invites INTEGER DEFAULT 0,
            flood_count INTEGER DEFAULT 0,
            last_used DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Invite history table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS invite_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            group_link TEXT,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            flood_time INTEGER DEFAULT 0,
            start_time DATETIME,
            end_time DATETIME,
            FOREIGN KEY (phone) REFERENCES sessions (phone)
        )
        ''')
        
        self.conn.commit()
        logger.info("📝 Database tables created/verified")

    def add_session(self, phone: str, session_string: str, user_id: int, 
                   first_name: str, last_name: str) -> bool:
        """Add new session to database"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            INSERT INTO sessions (
                phone, session_string, user_id, first_name, last_name, 
                last_used
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (phone, session_string, user_id, first_name, last_name, 
                 datetime.now()))
            self.conn.commit()
            logger.info(f"✅ Added new session for {phone}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"⚠️ Session already exists for {phone}")
            return False
        except Exception as e:
            logger.error(f"❌ Error adding session for {phone}: {str(e)}")
            return False

    def get_session(self, phone: str) -> Optional[Tuple]:
        """Get session details by phone number"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM sessions WHERE phone = ?
        ''', (phone,))
        result = cursor.fetchone()
        return result

    def get_all_sessions(self) -> List[Tuple]:
        """Get all active sessions"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM sessions WHERE status = 'active'
        ORDER BY last_used DESC
        ''')
        return cursor.fetchall()

    def update_session_stats(self, phone: str, invited: int, flood_time: int = 0):
        """Update session statistics after invite operation"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
            UPDATE sessions 
            SET total_invites = total_invites + ?,
                flood_count = flood_count + CASE WHEN ? > 0 THEN 1 ELSE 0 END,
                last_used = CURRENT_TIMESTAMP
            WHERE phone = ?
            ''', (invited, flood_time, phone))
            self.conn.commit()
            logger.info(f"📊 Updated stats for {phone}")
        except Exception as e:
            logger.error(f"❌ Error updating stats for {phone}: {str(e)}")

    def log_invite_operation(self, phone: str, group_link: str, 
                           success: int, failed: int, flood_time: int = 0):
        """Log invite operation details"""
        try:
            cursor = self.conn.cursor()
            current_time = datetime.now()
            cursor.execute('''
            INSERT INTO invite_history (
                phone, group_link, success_count, failed_count, 
                flood_time, start_time, end_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (phone, group_link, success, failed, flood_time, 
                 current_time, current_time))
            self.conn.commit()
            logger.info(f"📝 Logged invite operation for {phone}")
        except Exception as e:
            logger.error(f"❌ Error logging invite operation: {str(e)}")

    def delete_session(self, phone: str) -> bool:
        """Delete specific session"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM sessions WHERE phone = ?', (phone,))
            self.conn.commit()
            logger.info(f"🗑️ Deleted session for {phone}")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting session {phone}: {str(e)}")
            return False

    def delete_all_sessions(self) -> bool:
        """Delete all sessions"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM sessions')
            self.conn.commit()
            logger.info("🗑️ Deleted all sessions")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting all sessions: {str(e)}")
            return False

    def get_session_stats(self, phone: str) -> dict:
        """Get detailed statistics for a session"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT 
            total_invites,
            flood_count,
            (SELECT COUNT(*) FROM invite_history WHERE phone = sessions.phone) as operations,
            (SELECT SUM(success_count) FROM invite_history WHERE phone = sessions.phone) as total_success,
            (SELECT SUM(failed_count) FROM invite_history WHERE phone = sessions.phone) as total_failed
        FROM sessions
        WHERE phone = ?
        ''', (phone,))
        row = cursor.fetchone()
        
        if row:
            return {
                "total_invites": row[0],
                "flood_count": row[1],
                "operations": row[2],
                "total_success": row[3] or 0,
                "total_failed": row[4] or 0
            }
        return {}

    def phone_exists(self, phone: str) -> bool:
        """Check if a phone number exists in the sessions table"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT 1 FROM sessions WHERE phone = ?
        ''', (phone,))
        return cursor.fetchone() is not None
    
    def close(self):
        """Close database connection"""
        self.conn.close()