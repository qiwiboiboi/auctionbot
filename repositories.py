"""
Repository implementations for data persistence
"""

import sqlite3
import aiosqlite
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from domain import User, Auction, AuctionStatus, Bid


class UserRepository:
    """Abstract base class for user repository"""
    
    async def init_db(self):
        pass
    
    async def create_user(self, user: User) -> bool:
        pass
    
    async def get_user(self, user_id: int) -> Optional[User]:
        pass
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        pass
    
    async def update_user_status(self, user_id: int, is_blocked: bool) -> bool:
        pass
    
    async def get_all_users(self) -> List[User]:
        pass


class AuctionRepository:
    """Abstract base class for auction repository"""
    
    async def init_db(self):
        pass
    
    async def create_auction(self, auction: Auction) -> UUID:
        pass
    
    async def get_auction(self, auction_id: UUID) -> Optional[Auction]:
        pass
    
    async def update_auction_status(self, auction_id: UUID, status: AuctionStatus) -> bool:
        pass
    
    async def get_active_auctions(self) -> List[Auction]:
        pass
    
    async def get_scheduled_auctions(self) -> List[Auction]:
        pass
    
    async def get_completed_auctions(self) -> List[Auction]:
        pass
    
    async def add_participant(self, auction_id: UUID, user_id: int) -> bool:
        pass
    
    async def add_bid(self, bid: Bid) -> bool:
        pass
    
    async def get_auction_bids(self, auction_id: UUID) -> List[Bid]:
        pass


class SQLiteUserRepository(UserRepository):
    """SQLite implementation of user repository"""
    
    def __init__(self, db_path: str = "auction.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initialize user table"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    telegram_username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    display_name TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_blocked BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def create_user(self, user: User) -> bool:
        """Create a new user"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO users (user_id, username, telegram_username, first_name, last_name, display_name, is_admin, is_blocked, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user.user_id, user.username, user.telegram_username, user.first_name, user.last_name, user.display_name, user.is_admin, user.is_blocked, user.created_at))
                await db.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(
                        user_id=row['user_id'],
                        username=row['username'],
                        telegram_username=row['telegram_username'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        display_name=row['display_name'],
                        is_admin=bool(row['is_admin']),
                        is_blocked=bool(row['is_blocked']),
                        created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now()
                    )
                return None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE username = ?", (username,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(
                        user_id=row['user_id'],
                        username=row['username'],
                        telegram_username=row['telegram_username'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        display_name=row['display_name'],
                        is_admin=bool(row['is_admin']),
                        is_blocked=bool(row['is_blocked']),
                        created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now()
                    )
                return None

    async def update_user_status(self, user_id: int, is_blocked: bool) -> bool:
        """Update user blocked status"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (is_blocked, user_id))
                await db.commit()
                return True
        except Exception:
            return False

    async def get_all_users(self) -> List[User]:
        """Get all users"""
        users = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY created_at DESC") as cursor:
                async for row in cursor:
                    users.append(User(
                        user_id=row['user_id'],
                        username=row['username'],
                        telegram_username=row['telegram_username'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        display_name=row['display_name'],
                        is_admin=bool(row['is_admin']),
                        is_blocked=bool(row['is_blocked']),
                        created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now()
                    ))
        return users


class SQLiteAuctionRepository(AuctionRepository):
    """SQLite implementation of auction repository"""
    
    def __init__(self, db_path: str = "auction.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initialize auction and bid tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS auctions (
                    auction_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    start_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    status TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    photo_url TEXT,
                    media_type TEXT DEFAULT 'photo',
                    custom_message TEXT,
                    duration_hours INTEGER DEFAULT 0,
                    end_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (creator_id) REFERENCES users (user_id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bids (
                    bid_id TEXT PRIMARY KEY,
                    auction_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    amount REAL NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (auction_id) REFERENCES auctions (auction_id),
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS auction_participants (
                    auction_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (auction_id, user_id),
                    FOREIGN KEY (auction_id) REFERENCES auctions (auction_id),
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            await db.commit()

    async def create_auction(self, auction: Auction) -> UUID:
        """Create a new auction"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO auctions (auction_id, title, description, start_price, current_price, status, creator_id, photo_url, media_type, custom_message, duration_hours, end_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(auction.auction_id), auction.title, auction.description, auction.start_price, auction.current_price, auction.status.value, auction.creator_id, auction.photo_url, auction.media_type, auction.custom_message, auction.duration_hours, auction.end_time, auction.created_at))
            await db.commit()
            return auction.auction_id

    async def get_auction(self, auction_id: UUID) -> Optional[Auction]:
        """Get auction by ID with all related data"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Get auction data
            async with db.execute("SELECT * FROM auctions WHERE auction_id = ?", (str(auction_id),)) as cursor:
                auction_row = await cursor.fetchone()
                if not auction_row:
                    return None
            
            # Get participants
            participants = set()
            async with db.execute("SELECT user_id FROM auction_participants WHERE auction_id = ?", (str(auction_id),)) as cursor:
                async for row in cursor:
                    participants.add(row['user_id'])
            
            # Get bids
            bids = []
            async with db.execute("SELECT * FROM bids WHERE auction_id = ? ORDER BY timestamp", (str(auction_id),)) as cursor:
                async for row in cursor:
                    bids.append(Bid(
                        bid_id=UUID(row['bid_id']),
                        auction_id=UUID(row['auction_id']),
                        user_id=row['user_id'],
                        username=row['username'],
                        amount=row['amount'],
                        timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else datetime.now()
                    ))
            
            # Find current leader
            current_leader = bids[-1] if bids else None
            
            return Auction(
                auction_id=UUID(auction_row['auction_id']),
                title=auction_row['title'],
                description=auction_row['description'],
                start_price=auction_row['start_price'],
                current_price=auction_row['current_price'],
                status=AuctionStatus(auction_row['status']),
                creator_id=auction_row['creator_id'],
                photo_url=auction_row['photo_url'],
                media_type=auction_row['media_type'] or 'photo',
                custom_message=auction_row['custom_message'],
                duration_hours=auction_row['duration_hours'] or 0,
                end_time=datetime.fromisoformat(auction_row['end_time']) if auction_row['end_time'] else None,
                created_at=datetime.fromisoformat(auction_row['created_at']) if auction_row['created_at'] else datetime.now(),
                participants=participants,
                bids=bids,
                current_leader=current_leader
            )

    async def update_auction_status(self, auction_id: UUID, status: AuctionStatus) -> bool:
        """Update auction status"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE auctions SET status = ? WHERE auction_id = ?", (status.value, str(auction_id)))
                await db.commit()
                return True
        except Exception:
            return False

    async def get_active_auctions(self) -> List[Auction]:
        """Get all active auctions"""
        auctions = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT auction_id FROM auctions WHERE status = ? ORDER BY created_at", (AuctionStatus.ACTIVE.value,)) as cursor:
                async for row in cursor:
                    auction = await self.get_auction(UUID(row['auction_id']))
                    if auction:
                        auctions.append(auction)
        return auctions

    async def get_scheduled_auctions(self) -> List[Auction]:
        """Get all scheduled auctions"""
        auctions = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT auction_id FROM auctions WHERE status = ? ORDER BY created_at", (AuctionStatus.SCHEDULED.value,)) as cursor:
                async for row in cursor:
                    auction = await self.get_auction(UUID(row['auction_id']))
                    if auction:
                        auctions.append(auction)
        return auctions

    async def get_completed_auctions(self) -> List[Auction]:
        """Get all completed auctions"""
        auctions = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT auction_id FROM auctions WHERE status = ? ORDER BY created_at DESC LIMIT 10", (AuctionStatus.COMPLETED.value,)) as cursor:
                async for row in cursor:
                    auction = await self.get_auction(UUID(row['auction_id']))
                    if auction:
                        auctions.append(auction)
        return auctions

    async def add_participant(self, auction_id: UUID, user_id: int) -> bool:
        """Add participant to auction"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO auction_participants (auction_id, user_id)
                    VALUES (?, ?)
                """, (str(auction_id), user_id))
                await db.commit()
                return True
        except Exception:
            return False

    async def add_bid(self, bid: Bid) -> bool:
        """Add bid to auction and update current price"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Add bid
                await db.execute("""
                    INSERT INTO bids (bid_id, auction_id, user_id, username, amount, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (str(bid.bid_id), str(bid.auction_id), bid.user_id, bid.username, bid.amount, bid.timestamp))
                
                # Update auction current price
                await db.execute("UPDATE auctions SET current_price = ? WHERE auction_id = ?", (bid.amount, str(bid.auction_id)))
                
                await db.commit()
                return True
        except Exception:
            return False

    async def get_auction_bids(self, auction_id: UUID) -> List[Bid]:
        """Get all bids for an auction"""
        bids = []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bids WHERE auction_id = ? ORDER BY timestamp", (str(auction_id),)) as cursor:
                async for row in cursor:
                    bids.append(Bid(
                        bid_id=UUID(row['bid_id']),
                        auction_id=UUID(row['auction_id']),
                        user_id=row['user_id'],
                        username=row['username'],
                        amount=row['amount'],
                        timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else datetime.now()
                    ))
        return bids