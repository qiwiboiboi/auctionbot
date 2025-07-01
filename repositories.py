"""
Data access layer - repositories for domain entities with SQLite database
"""

import aiosqlite
import json
from typing import Dict, List, Optional, Protocol
from uuid import UUID
from datetime import datetime
from domain import User, Auction, Bid, AuctionStatus


class UserRepository(Protocol):
    """User repository interface"""
    async def save_user(self, user: User) -> None: ...
    async def get_user(self, user_id: int) -> Optional[User]: ...
    async def get_user_by_username(self, username: str) -> Optional[User]: ...


class AuctionRepository(Protocol):
    """Auction repository interface"""
    async def save_auction(self, auction: Auction) -> None: ...
    async def get_auction(self, auction_id: UUID) -> Optional[Auction]: ...
    async def get_active_auctions(self) -> List[Auction]: ...
    async def get_scheduled_auctions(self) -> List[Auction]: ...
    async def update_auction(self, auction: Auction) -> None: ...


class SQLiteUserRepository:
    """SQLite implementation of user repository"""
    
    def __init__(self, db_path: str = "auction_bot.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initialize database tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    telegram_handle TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def save_user(self, user: User) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, username, telegram_handle, first_name, last_name, is_admin, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user.user_id, user.username, user.telegram_handle,
                user.first_name, user.last_name, user.is_admin,
                user.created_at.isoformat()
            ))
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(
                        user_id=row['user_id'],
                        username=row['username'],
                        telegram_handle=row['telegram_handle'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        is_admin=bool(row['is_admin']),
                        created_at=datetime.fromisoformat(row['created_at'])
                    )
                return None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE username = ?", (username,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return User(
                        user_id=row['user_id'],
                        username=row['username'],
                        telegram_handle=row['telegram_handle'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        is_admin=bool(row['is_admin']),
                        created_at=datetime.fromisoformat(row['created_at'])
                    )
                return None


class SQLiteAuctionRepository:
    """SQLite implementation of auction repository"""
    
    def __init__(self, db_path: str = "auction_bot.db"):
        self.db_path = db_path

    async def init_db(self):
        """Initialize database tables"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS auctions (
                    auction_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    photo_url TEXT,
                    start_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    status TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    participants TEXT DEFAULT '[]',
                    bids TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    winner_id INTEGER,
                    initial_leader_username TEXT
                )
            """)
            await db.commit()

    async def save_auction(self, auction: Auction) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO auctions 
                (auction_id, title, description, photo_url, start_price, current_price, 
                 status, creator_id, participants, bids, created_at, start_time, end_time, 
                 winner_id, initial_leader_username)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(auction.auction_id), auction.title, auction.description, auction.photo_url,
                auction.start_price, auction.current_price, auction.status.value,
                auction.creator_id, json.dumps(auction.participants),
                json.dumps([{
                    'bid_id': str(bid.bid_id),
                    'auction_id': str(bid.auction_id),
                    'user_id': bid.user_id,
                    'amount': bid.amount,
                    'created_at': bid.created_at.isoformat(),
                    'username': bid.username
                } for bid in auction.bids]),
                auction.created_at.isoformat(),
                auction.start_time.isoformat() if auction.start_time else None,
                auction.end_time.isoformat() if auction.end_time else None,
                auction.winner_id, auction.initial_leader_username
            ))
            await db.commit()

    async def get_auction(self, auction_id: UUID) -> Optional[Auction]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM auctions WHERE auction_id = ?", (str(auction_id),)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return self._row_to_auction(row)
                return None

    async def get_active_auctions(self) -> List[Auction]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM auctions WHERE status = ?", (AuctionStatus.ACTIVE.value,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_auction(row) for row in rows]

    async def get_scheduled_auctions(self) -> List[Auction]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM auctions WHERE status = ? ORDER BY start_time", (AuctionStatus.SCHEDULED.value,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_auction(row) for row in rows]

    async def update_auction(self, auction: Auction) -> None:
        await self.save_auction(auction)

    def _row_to_auction(self, row) -> Auction:
        """Convert database row to Auction object"""
        bids_data = json.loads(row['bids'])
        bids = [
            Bid(
                bid_id=UUID(bid['bid_id']),
                auction_id=UUID(bid['auction_id']),
                user_id=bid['user_id'],
                amount=bid['amount'],
                created_at=datetime.fromisoformat(bid['created_at']),
                username=bid['username']
            ) for bid in bids_data
        ]
        
        return Auction(
            auction_id=UUID(row['auction_id']),
            title=row['title'],
            description=row['description'],
            photo_url=row['photo_url'],
            start_price=row['start_price'],
            current_price=row['current_price'],
            status=AuctionStatus(row['status']),
            creator_id=row['creator_id'],
            participants=json.loads(row['participants']),
            bids=bids,
            created_at=datetime.fromisoformat(row['created_at']),
            start_time=datetime.fromisoformat(row['start_time']) if row['start_time'] else None,
            end_time=datetime.fromisoformat(row['end_time']) if row['end_time'] else None,
            winner_id=row['winner_id'],
            initial_leader_username=row['initial_leader_username']
        )


# Legacy in-memory repositories for backwards compatibility
class InMemoryUserRepository:
    """In-memory implementation of user repository"""
    
    def __init__(self):
        self._users: Dict[int, User] = {}
        self._usernames: Dict[str, int] = {}

    async def save_user(self, user: User) -> None:
        self._users[user.user_id] = user
        self._usernames[user.username] = user.user_id

    async def get_user(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    async def get_user_by_username(self, username: str) -> Optional[User]:
        user_id = self._usernames.get(username)
        return self._users.get(user_id) if user_id else None


class InMemoryAuctionRepository:
    """In-memory implementation of auction repository"""
    
    def __init__(self):
        self._auctions: Dict[UUID, Auction] = {}

    async def save_auction(self, auction: Auction) -> None:
        self._auctions[auction.auction_id] = auction

    async def get_auction(self, auction_id: UUID) -> Optional[Auction]:
        return self._auctions.get(auction_id)

    async def get_active_auctions(self) -> List[Auction]:
        return [a for a in self._auctions.values() if a.status == AuctionStatus.ACTIVE]

    async def get_scheduled_auctions(self) -> List[Auction]:
        return [a for a in self._auctions.values() if a.status == AuctionStatus.SCHEDULED]

    async def update_auction(self, auction: Auction) -> None:
        self._auctions[auction.auction_id] = auction