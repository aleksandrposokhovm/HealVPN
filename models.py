from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Boolean, DateTime, Integer

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_ends: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    vpn_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    available_devices: Mapped[int] = mapped_column(default=0)
    
    # Auto-renewal fields
    payment_method_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_payments: Mapped[int] = mapped_column(Integer, default=0)
    
    last_payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
