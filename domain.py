"""
Domain entities and business rules
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Set
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
    telegram_username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: str = ""
    is_admin: bool = False
    is_blocked: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Set display name if not provided"""
        if not self.display_name:
            if self.first_name or self.last_name:
                name_parts = [self.first_name or "", self.last_name or ""]
                full_name = " ".join(part for part in name_parts if part).strip()
                self.display_name = f"{self.username} ({full_name})" if full_name else self.username
            else:
                self.display_name = self.username


@dataclass
class Bid:
    """Bid entity representing a user's bid on an auction"""
    bid_id: UUID
    auction_id: UUID
    user_id: int
    username: str
    amount: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Auction:
    """Auction entity with business logic"""
    auction_id: UUID
    title: str
    description: Optional[str]
    start_price: float
    current_price: float
    status: AuctionStatus
    creator_id: int
    photo_url: Optional[str] = None
    media_type: str = "photo"
    custom_message: Optional[str] = None
    duration_hours: int = 1  # Minimum 1 hour, no more infinite auctions
    end_time: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    participants: Set[int] = field(default_factory=set)
    bids: List[Bid] = field(default_factory=list)
    current_leader: Optional[Bid] = None

    def __post_init__(self):
        """Ensure all auctions have proper duration and end time"""
        # Ensure minimum duration
        if self.duration_hours < 1:
            self.duration_hours = 1
        
        # Set end_time if not set and auction is active
        if self.status == AuctionStatus.ACTIVE and self.end_time is None:
            self.end_time = self.created_at + timedelta(hours=self.duration_hours)

    @property
    def is_active(self) -> bool:
        """Check if auction is currently active"""
        now = datetime.now()
        return (self.status == AuctionStatus.ACTIVE and 
                self.end_time is not None and now < self.end_time)

    @property
    def is_scheduled(self) -> bool:
        """Check if auction is scheduled for future"""
        return self.status == AuctionStatus.SCHEDULED

    @property
    def time_remaining(self) -> Optional[str]:
        """Get formatted time remaining"""
        if not self.end_time or self.status != AuctionStatus.ACTIVE:
            return None
        remaining = self.end_time - datetime.now()
        if remaining.total_seconds() <= 0:
            return "Завершён"
        
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        if hours > 0:
            return f"{hours}ч {minutes}м"
        else:
            return f"{minutes}м"

    @property
    def time_until_start(self) -> Optional[str]:
        """Get formatted time until auction starts"""
        if self.status != AuctionStatus.SCHEDULED:
            return None
        # For scheduled auctions, we calculate from creation time + delay
        start_time = self.created_at + timedelta(minutes=1)
        remaining = start_time - datetime.now()
        if remaining.total_seconds() <= 0:
            return "Готов к запуску"
        
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        if hours > 0:
            return f"{hours}ч {minutes}м"
        else:
            return f"{minutes}м"