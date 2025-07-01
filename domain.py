"""
Domain entities and business rules
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional
from uuid import UUID


class AuctionStatus(Enum):
    """Possible auction states"""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


@dataclass
class User:
    """User entity representing a registered bot user"""
    user_id: int
    username: str
    telegram_handle: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool = False
    is_blocked: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def display_name(self) -> str:
        """Get display name for user"""
        if self.first_name or self.last_name:
            name_parts = [self.first_name or "", self.last_name or ""]
            full_name = " ".join(part for part in name_parts if part).strip()
            return f"{self.username} ({full_name})" if full_name else self.username
        return self.username


@dataclass
class Bid:
    """Bid entity representing a user's bid on an auction"""
    bid_id: UUID
    auction_id: UUID
    user_id: int
    amount: float
    created_at: datetime
    username: str


@dataclass
class Auction:
    """Auction entity with business logic"""
    auction_id: UUID
    title: str
    description: Optional[str]
    photo_url: Optional[str]
    media_type: str
    custom_message: Optional[str]
    start_price: float
    current_price: float
    status: AuctionStatus
    creator_id: int
    participants: List[int]
    bids: List[Bid]
    created_at: datetime
    end_time: Optional[datetime] = None
    winner_id: Optional[int] = None
    start_time: Optional[datetime] = None

    @property
    def current_leader(self) -> Optional[Bid]:
        """Get the current highest bid"""
        if not self.bids:
            return None
        return max(self.bids, key=lambda b: b.amount)

    @property
    def is_active(self) -> bool:
        """Check if auction is currently active"""
        now = datetime.now()
        return (self.status == AuctionStatus.ACTIVE and 
                (self.end_time is None or now < self.end_time))

    @property
    def is_scheduled(self) -> bool:
        """Check if auction is scheduled for future"""
        return self.status == AuctionStatus.SCHEDULED

    @property
    def time_remaining(self) -> Optional[str]:
        """Get formatted time remaining"""
        if not self.end_time:
            return None
        remaining = self.end_time - datetime.now()
        if remaining.total_seconds() <= 0:
            return "Завершён"
        
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return f"{hours}ч {minutes}м"

    @property
    def time_until_start(self) -> Optional[str]:
        """Get formatted time until auction starts"""
        if not self.start_time:
            return None
        remaining = self.start_time - datetime.now()
        if remaining.total_seconds() <= 0:
            return "Готов к запуску"
        
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return f"{hours}ч {minutes}м"