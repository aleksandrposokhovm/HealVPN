"""
HealVPN Payment System — Full Test Suite
Covers: race conditions, idempotency, pending payments, auto-renew, notifications, cleanup.
Run: python tests/test_payment_system.py
"""
import asyncio
import logging
import os
import sys

# Add project root to sys.path to allow imports from bot package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

# Bootstrap the test DB before any bot imports
DB_PATH = "test_payments.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.setdefault("YOOKASSA_SHOP_ID", "test_shop")
os.environ.setdefault("YOOKASSA_SECRET_KEY", "test_secret")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")

from bot import database as db
from bot.models import Base, User, ProcessedPayment, PendingPayment

original_db_engine = db.engine

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

TEST_DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
_results = []


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} — expected {expected!r}, got {actual!r}")


async def setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    db.engine = engine
    db.async_session = async_session


async def teardown():
    await engine.dispose()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


async def clear_tables():
    """Clear all tables between tests."""
    async with async_session() as session:
        for model in [ProcessedPayment, PendingPayment, User]:
            for row in (await session.execute(select(model))).scalars().all():
                await session.delete(row)
        await session.commit()
    db.sub_cache.clear()


def run_test(name):
    """Decorator to register and run a test."""
    def decorator(fn):
        fn._test_name = name
        return fn
    return decorator


# ──────────────────────────────────────────────
# TEST 1: Race condition — same payment_id, 5 concurrent workers
# ──────────────────────────────────────────────
async def test_race_condition_same_payment():
    await clear_tables()
    await db.add_user(1001, "user1", "User One")
    payment_id = "race_pay_001"

    results = await asyncio.gather(*[
        db.activate_subscription(1001, "Standard", 30, "key://test", payment_id, 100.0, "1_month")
        for _ in range(5)
    ])

    successes = sum(1 for r in results if r is True)
    failures = sum(1 for r in results if r is False)
    assert_eq(successes, 1, "Race: successes")
    assert_eq(failures, 4, "Race: failures")

    async with async_session() as session:
        processed = (await session.execute(
            select(ProcessedPayment).where(ProcessedPayment.payment_id == payment_id)
        )).scalars().all()
        assert_eq(len(processed), 1, "Race: processed_payments rows")


# ──────────────────────────────────────────────
# TEST 2: is_payment_processed returns correct values
# ──────────────────────────────────────────────
async def test_is_payment_processed():
    await clear_tables()
    await db.add_user(1002, "user2", "User Two")
    pid = "proc_pay_002"

    assert_eq(await db.is_payment_processed(pid), False, "Before activation")
    await db.activate_subscription(1002, "Standard", 30, "key://x", pid, 88.0, "1_month")
    assert_eq(await db.is_payment_processed(pid), True, "After activation")


# ──────────────────────────────────────────────
# TEST 3: activate_subscription is idempotent
# ──────────────────────────────────────────────
async def test_idempotency():
    await clear_tables()
    await db.add_user(1003, "user3", "User Three")
    pid = "idem_pay_003"

    r1 = await db.activate_subscription(1003, "Standard", 30, "key://a", pid, 88.0, "1_month")
    r2 = await db.activate_subscription(1003, "Standard", 30, "key://b", pid, 88.0, "1_month")
    r3 = await db.activate_subscription(1003, "Standard", 30, "key://c", pid, 88.0, "1_month")

    assert_eq(r1, True, "Idempotency: first call")
    assert_eq(r2, False, "Idempotency: second call")
    assert_eq(r3, False, "Idempotency: third call")

    # Key must be from first call
    sub = await db.get_user_subscription(1003)
    assert_eq(sub[2], "key://a", "Idempotency: vpn_key preserved")


# ──────────────────────────────────────────────
# TEST 4: Subscription extension (active user gets time added from end date)
# ──────────────────────────────────────────────
async def test_subscription_extension():
    await clear_tables()
    await db.add_user(1004, "user4", "User Four")

    future = datetime.now(timezone.utc) + timedelta(days=15)
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == 1004))).scalars().first()
        user.subscription_ends = future
        user.is_active = True
        await session.commit()

    await db.activate_subscription(1004, "Standard", 30, "key://ext", "ext_pay_004", 88.0, "1_month")

    sub = await db.get_user_subscription(1004)
    expected_end = future + timedelta(days=30)
    actual_end = sub[1]
    # Normalize: SQLite may return naive datetimes
    if actual_end.tzinfo is None:
        actual_end = actual_end.replace(tzinfo=timezone.utc)
    if expected_end.tzinfo is None:
        expected_end = expected_end.replace(tzinfo=timezone.utc)
    diff = abs((actual_end - expected_end).total_seconds())
    assert diff < 5, f"Extension: subscription_ends diff too large: {diff}s"


# ──────────────────────────────────────────────
# TEST 5: Trial flag is set for 7-day plan
# ──────────────────────────────────────────────
async def test_trial_flag():
    await clear_tables()
    await db.add_user(1005, "user5", "User Five")
    await db.activate_subscription(1005, "Trial", 7, "key://trial", "trial_pay_005", 11.0, "trial_7_days")

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == 1005))).scalars().first()
        assert user.last_trial_date is not None, "Trial: last_trial_date must be set"

    assert_eq(await db.is_trial_available(1005), False, "Trial: unavailable after use")


# ──────────────────────────────────────────────
# TEST 6: Pending payment CRUD
# ──────────────────────────────────────────────
async def test_pending_payment_crud():
    await clear_tables()
    pid = "pend_pay_006"

    await db.add_pending_payment(pid, 1006, "1_month", 88.0)
    payments = await db.get_pending_payments(max_age_minutes=60)
    assert_eq(len(payments), 1, "Pending: add")
    assert_eq(payments[0].payment_id, pid, "Pending: correct id")

    await db.remove_pending_payment(pid)
    payments = await db.get_pending_payments(max_age_minutes=60)
    assert_eq(len(payments), 0, "Pending: remove")


# ──────────────────────────────────────────────
# TEST 7: get_pending_payments excludes already-processed
# ──────────────────────────────────────────────
async def test_pending_excludes_processed():
    await clear_tables()
    await db.add_user(1007, "user7", "User Seven")
    pid = "proc_pend_007"

    await db.add_pending_payment(pid, 1007, "1_month", 88.0)
    await db.activate_subscription(1007, "Standard", 30, "key://x", pid, 88.0, "1_month")

    # get_pending_payments must NOT return already-processed payment
    payments = await db.get_pending_payments(max_age_minutes=60)
    pids = [p.payment_id for p in payments]
    assert pid not in pids, f"Pending: processed payment {pid} must not appear in pending list"


# ──────────────────────────────────────────────
# TEST 8: Duplicate add_pending_payment is safe
# ──────────────────────────────────────────────
async def test_pending_no_duplicate():
    await clear_tables()
    pid = "dup_pend_008"

    await db.add_pending_payment(pid, 1008, "1_month", 88.0)
    await db.add_pending_payment(pid, 1008, "1_month", 88.0)  # duplicate

    payments = await db.get_pending_payments(max_age_minutes=60)
    count = sum(1 for p in payments if p.payment_id == pid)
    assert_eq(count, 1, "Pending: no duplicate on double add")


# ──────────────────────────────────────────────
# TEST 9: cleanup_old_pending_payments removes old records
# ──────────────────────────────────────────────
async def test_pending_cleanup():
    await clear_tables()
    pid = "old_pend_009"

    # Inject old pending payment directly
    old_time = datetime.now(timezone.utc) - timedelta(minutes=35)
    async with async_session() as session:
        session.add(PendingPayment(payment_id=pid, user_id=1009, plan="1_month", amount=88.0, created_at=old_time))
        await session.commit()

    await db.cleanup_old_pending_payments(max_age_minutes=30)

    async with async_session() as session:
        result = (await session.execute(select(PendingPayment).where(PendingPayment.payment_id == pid))).scalars().first()
        assert result is None, "Cleanup: old pending payment must be deleted"


# ──────────────────────────────────────────────
# TEST 10: Auto-renew query — correct windows and failed_payments logic
# ──────────────────────────────────────────────
async def test_auto_renew_query():
    await clear_tables()
    now = datetime.now(timezone.utc)

    users = [
        User(id=2001, username="ar1", is_active=True, auto_renew=True, payment_method_id="pm1",
             subscription_ends=now + timedelta(hours=24), failed_payments=0),   # → SHOULD renew (24h window, 0 fails)
        User(id=2002, username="ar2", is_active=True, auto_renew=True, payment_method_id="pm2",
             subscription_ends=now + timedelta(hours=24), failed_payments=1),   # → NO (wrong fail count for 24h)
        User(id=2003, username="ar3", is_active=True, auto_renew=True, payment_method_id="pm3",
             subscription_ends=now + timedelta(hours=12), failed_payments=1),   # → SHOULD renew (12h window, 1 fail)
        User(id=2004, username="ar4", is_active=True, auto_renew=True, payment_method_id="pm4",
             subscription_ends=now + timedelta(hours=12), failed_payments=0),   # → SHOULD renew (12h window, 0 fails — self-healing)
        User(id=2005, username="ar5", is_active=True, auto_renew=True, payment_method_id="pm5",
             subscription_ends=now + timedelta(minutes=30), failed_payments=2), # → SHOULD renew (30m window, 2 fails)
        User(id=2006, username="ar6", is_active=False, auto_renew=True, payment_method_id="pm6",
             subscription_ends=now + timedelta(hours=24), failed_payments=0),   # → NO (inactive)
        User(id=2007, username="ar7", is_active=True, auto_renew=False, payment_method_id="pm7",
             subscription_ends=now + timedelta(hours=24), failed_payments=0),   # → NO (auto_renew=False)
        User(id=2008, username="ar8", is_active=True, auto_renew=True, payment_method_id=None,
             subscription_ends=now + timedelta(hours=24), failed_payments=0),   # → NO (no payment method)
        User(id=2009, username="ar9", is_active=True, auto_renew=True, payment_method_id="pm9",
             subscription_ends=now + timedelta(minutes=30), failed_payments=1), # → SHOULD renew (30m window, 1 fail — self-healing)
        User(id=2010, username="ar10", is_active=True, auto_renew=True, payment_method_id="pm10",
             subscription_ends=now + timedelta(minutes=30), failed_payments=3), # → NO (failed 3 times already)
    ]

    async with async_session() as session:
        session.add_all(users)
        await session.commit()

    found = await db.get_users_for_auto_renew()
    found_ids = {u.id for u in found}

    assert 2001 in found_ids, "AutoRenew: user 2001 (24h, 0 fails) must be included"
    assert 2002 not in found_ids, "AutoRenew: user 2002 (24h, 1 fail) must be excluded"
    assert 2003 in found_ids, "AutoRenew: user 2003 (12h, 1 fail) must be included"
    assert 2004 in found_ids, "AutoRenew: user 2004 (12h, 0 fails — self-healing) must be included"
    assert 2005 in found_ids, "AutoRenew: user 2005 (30m, 2 fails) must be included"
    assert 2006 not in found_ids, "AutoRenew: user 2006 (inactive) must be excluded"
    assert 2007 not in found_ids, "AutoRenew: user 2007 (auto_renew=False) must be excluded"
    assert 2008 not in found_ids, "AutoRenew: user 2008 (no payment method) must be excluded"
    assert 2009 in found_ids, "AutoRenew: user 2009 (30m, 1 fail — self-healing) must be included"
    assert 2010 not in found_ids, "AutoRenew: user 2010 (30m, 3 fails) must be excluded"


# ──────────────────────────────────────────────
# TEST 11: increment_failed_payments disables auto_renew at 3
# ──────────────────────────────────────────────
async def test_failed_payments_counter():
    await clear_tables()
    async with async_session() as session:
        session.add(User(id=3001, username="fp1", auto_renew=True, failed_payments=0))
        await session.commit()

    c1 = await db.increment_failed_payments(3001)
    c2 = await db.increment_failed_payments(3001)
    c3 = await db.increment_failed_payments(3001)

    assert_eq(c1, 1, "FailedPayments: count after 1st")
    assert_eq(c2, 2, "FailedPayments: count after 2nd")
    assert_eq(c3, 3, "FailedPayments: count after 3rd")

    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == 3001))).scalars().first()
        assert_eq(user.auto_renew, False, "FailedPayments: auto_renew disabled at 3")

    await db.reset_failed_payments(3001)
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == 3001))).scalars().first()
        assert_eq(user.failed_payments, 0, "FailedPayments: reset to 0")


# ──────────────────────────────────────────────
# TEST 12: deactivate_expired_subscriptions
# ──────────────────────────────────────────────
async def test_deactivate_expired():
    await clear_tables()
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        session.add_all([
            User(id=4001, username="ex1", is_active=True, subscription_ends=now - timedelta(hours=1)),  # expired
            User(id=4002, username="ex2", is_active=True, subscription_ends=now + timedelta(hours=1)),  # active
            User(id=4003, username="ex3", is_active=True, subscription_ends=now - timedelta(days=5)),   # expired
        ])
        await session.commit()

    await db.deactivate_expired_subscriptions()

    async with async_session() as session:
        for uid, expected_active in [(4001, False), (4002, True), (4003, False)]:
            user = (await session.execute(select(User).where(User.id == uid))).scalars().first()
            assert_eq(user.is_active, expected_active, f"Deactivate: user {uid}")


# ──────────────────────────────────────────────
# TEST 13: sub_cache is invalidated on activate_subscription
# ──────────────────────────────────────────────
async def test_cache_invalidation():
    await clear_tables()
    await db.add_user(5001, "cache1", "Cache User")
    # Populate cache
    await db.get_user_subscription(5001)
    assert 5001 in db.sub_cache, "Cache: should be populated"

    await db.activate_subscription(5001, "Standard", 30, "key://cache", "cache_pay_001", 88.0, "1_month")
    assert 5001 not in db.sub_cache, "Cache: must be invalidated after activation"


# ──────────────────────────────────────────────
# TEST 14: payment_service.process_successful_payment — background notification sent
# ──────────────────────────────────────────────
async def test_payment_service_background_notification():
    await clear_tables()
    await db.add_user(6001, "ps1", "PS User")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_payment = {
        "metadata": {"plan": "1_month"},
        "amount": {"value": "88.00"},
        "payment_method": {"id": "pm_test_001"},
        "status": "succeeded"
    }

    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/TEST_TOKEN_ABC123",
        "links": [],
        "token": "TEST_TOKEN_ABC123",
        "proxies": {"vless": {}},
        "inbounds": {},
        "data_limit": 0,
        "data_limit_reset_strategy": "no_reset",
        "note": "",
        "on_hold_timeout": None,
        "on_hold_expire_duration": 0,
    }

    with patch("bot.payment_service.marzban_api") as mock_api, \
         patch("bot.payment_service.kb") as mock_kb:

        mock_api.extract_token = MagicMock(return_value="TEST_TOKEN_ABC123")
        mock_api.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        mock_kb.success_payment_menu = MagicMock(return_value=MagicMock())

        from bot.payment_service import process_successful_payment
        result = await process_successful_payment(
            bot=mock_bot,
            user_id=6001,
            payment_id="ps_pay_6001",
            payment=fake_payment,
            is_background=True,
        )

    assert_eq(result, True, "PaymentService: must return True on success")
    assert mock_bot.send_message.called, "PaymentService: send_message must be called for background"

    # Verify subscription was activated in DB
    sub = await db.get_user_subscription(6001)
    assert sub is not None and sub[3] is True, "PaymentService: subscription must be active"


# ──────────────────────────────────────────────
# TEST 15: payment_service — duplicate payment_id returns False, no double notification
# ──────────────────────────────────────────────
async def test_payment_service_duplicate():
    await clear_tables()
    await db.add_user(6002, "ps2", "PS User 2")

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_payment = {
        "metadata": {"plan": "1_month"},
        "amount": {"value": "88.00"},
        "payment_method": {},
        "status": "succeeded"
    }
    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/DUP_TOKEN",
        "links": [], "token": "DUP_TOKEN",
        "proxies": {"vless": {}}, "inbounds": {},
        "data_limit": 0, "data_limit_reset_strategy": "no_reset",
        "note": "", "on_hold_timeout": None, "on_hold_expire_duration": 0,
    }

    with patch("bot.payment_service.marzban_api") as mock_api, \
         patch("bot.payment_service.kb") as mock_kb:

        mock_api.extract_token = MagicMock(return_value="DUP_TOKEN")
        mock_api.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        mock_kb.success_payment_menu = MagicMock(return_value=MagicMock())

        from bot.payment_service import process_successful_payment

        r1 = await process_successful_payment(mock_bot, 6002, "dup_pay_6002", fake_payment, is_background=True)
        r2 = await process_successful_payment(mock_bot, 6002, "dup_pay_6002", fake_payment, is_background=True)

    assert_eq(r1, True, "Duplicate PaymentService: first call True")
    assert_eq(r2, False, "Duplicate PaymentService: second call False")
    assert_eq(mock_bot.send_message.call_count, 1, "Duplicate PaymentService: send_message called once")


# ──────────────────────────────────────────────
# TEST 16: save_payment_method and get_user_auto_renew_status
# ──────────────────────────────────────────────
async def test_save_payment_method():
    await clear_tables()
    await db.add_user(7001, "pm1", "PM User")

    status_before = await db.get_user_auto_renew_status(7001)
    assert_eq(status_before, (False, False), "PaymentMethod: default state")

    await db.save_payment_method(7001, "yookassa_pm_xyz")
    status_after = await db.get_user_auto_renew_status(7001)
    assert_eq(status_after, (True, True), "PaymentMethod: after save")

    await db.set_auto_renew(7001, False)
    status_disabled = await db.get_user_auto_renew_status(7001)
    assert_eq(status_disabled[0], False, "PaymentMethod: auto_renew disabled")
    assert_eq(status_disabled[1], True, "PaymentMethod: payment_method still set")


# ──────────────────────────────────────────────
# TEST 17: marzban_api.extract_token
# ──────────────────────────────────────────────
async def test_extract_token():
    import os
    os.environ["MARZBAN_URL"] = "https://vpn.example.com"
    os.environ["MARZBAN_USERNAME"] = "admin"
    os.environ["MARZBAN_PASSWORD"] = "pass"

    from bot.marzban_api import MarzbanAPI
    api = MarzbanAPI()

    cases = [
        ("https://vpn.example.com/sub/TOKEN123", "TOKEN123"),
        ("https://vpn.example.com/sub/TOKEN123?foo=bar", "TOKEN123"),
        ("https://vpn.example.com/sub/TOKEN123#frag", "TOKEN123"),
        ("https://vpn.example.com/sub/TOKEN123/extra", "TOKEN123"),
        ("vless://uuid@server:port?type=tcp", None),
        ("", None),
        (None, None),
    ]

    for url, expected in cases:
        result = api.extract_token(url)
        assert_eq(result, expected, f"ExtractToken: url={url!r}")


# ──────────────────────────────────────────────
# TEST 18: update_subscription_date
# ──────────────────────────────────────────────
async def test_update_subscription_date():
    await clear_tables()
    await db.add_user(8001, "usd1", "Date User")

    future = datetime.now(timezone.utc) + timedelta(days=10)
    result = await db.update_subscription_date(8001, future)
    assert_eq(result, True, "UpdateDate: returns True")

    sub = await db.get_user_subscription(8001)
    assert sub[3] is True, "UpdateDate: is_active=True for future date"

    past = datetime.now(timezone.utc) - timedelta(days=1)
    await db.update_subscription_date(8001, past)
    db.sub_cache.clear()
    sub2 = await db.get_user_subscription(8001)
    assert sub2[3] is False, "UpdateDate: is_active=False for past date"


# ──────────────────────────────────────────────
# TEST 19: Auto-renew background resilience (pending registration + check_pending retry)
# ──────────────────────────────────────────────
async def test_auto_renew_background_resilience():
    await clear_tables()
    
    # 1. Setup an eligible user who is active and auto_renew=True
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        user = User(
            id=9001,
            username="ar_res",
            is_active=True,
            auto_renew=True,
            payment_method_id="pm_res_001",
            subscription_ends=now + timedelta(hours=24),
            failed_payments=0,
            vpn_key="https://vpn.example.com/sub/TOKEN_XYZ"
        )
        session.add(user)
        await session.commit()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_pending_payment = {
        "id": "pay_res_pending_001",
        "status": "pending",
        "amount": {"value": "88.00"},
        "payment_method": {"id": "pm_res_001"}
    }

    fake_succeeded_payment = {
        "id": "pay_res_pending_001",
        "status": "succeeded",
        "metadata": {"user_id": "9001", "plan": "auto_renew"},
        "amount": {"value": "88.00"},
        "payment_method": {"id": "pm_res_001"}
    }

    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/TOKEN_XYZ",
        "links": [],
        "token": "TOKEN_XYZ",
        "proxies": {"vless": {}},
        "inbounds": {},
        "data_limit": 0,
        "data_limit_reset_strategy": "no_reset",
        "note": "",
        "on_hold_timeout": None,
        "on_hold_expire_duration": 0,
    }

    # Patch the create_auto_payment and httpx/marzban calls
    with patch("bot.scheduler.create_auto_payment", AsyncMock(return_value=fake_pending_payment)), \
         patch("bot.payment_service.marzban_api") as mock_marzban, \
         patch("bot.scheduler.marzban_api") as mock_marzban_sched:

        # Mock marzban api behavior
        mock_marzban.extract_token = MagicMock(return_value="TOKEN_XYZ")
        mock_marzban.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        
        mock_marzban_sched.get_token = AsyncMock(return_value="token123")
        mock_marzban_sched.extract_token = MagicMock(return_value="TOKEN_XYZ")

        # 2. Trigger auto_renew_subscriptions (simulate background scheduler job)
        from bot.scheduler import auto_renew_subscriptions
        await auto_renew_subscriptions(mock_bot)

        # 3. Verify that the payment was registered in PendingPayment table!
        async with async_session() as session:
            pending = (await session.execute(
                select(PendingPayment).where(PendingPayment.payment_id == "pay_res_pending_001")
            )).scalars().first()
            assert pending is not None, "Resilience: Payment must be registered in pending table"
            assert_eq(pending.user_id, 9001, "Resilience: correct user ID")
            
            # The subscription ends must NOT have changed yet (still naive/original future time)
            user_db = (await session.execute(select(User).where(User.id == 9001))).scalars().first()
            assert abs((user_db.subscription_ends.replace(tzinfo=timezone.utc) - (now + timedelta(hours=24))).total_seconds()) < 5

        # 4. Mock YooKassa's GET call inside check_pending_payments to return status=succeeded
        class FakeResponse:
            def __init__(self, json_data, status_code=200):
                self.json_data = json_data
                self.status_code = status_code
            def json(self):
                return self.json_data

        async def fake_get(url, headers=None, timeout=None):
            if "pay_res_pending_001" in url:
                return FakeResponse(fake_succeeded_payment)
            return FakeResponse({}, 404)

        # 5. Patch httpx.AsyncClient.get to return succeeded payment and call check_pending_payments
        with patch("httpx.AsyncClient.get", side_effect=fake_get):
            from bot.scheduler import check_pending_payments
            await check_pending_payments(mock_bot)

        # 6. Verify payment is removed from PendingPayment and subscription is extended!
        async with async_session() as session:
            pending_after = (await session.execute(
                select(PendingPayment).where(PendingPayment.payment_id == "pay_res_pending_001")
            )).scalars().first()
            assert pending_after is None, "Resilience: Succeeded payment must be removed from pending table"

            # Check subscription is extended in DB
            user_extended = (await session.execute(select(User).where(User.id == 9001))).scalars().first()
            expected_new_end = now + timedelta(hours=24) + timedelta(days=30)
            actual_new_end = user_extended.subscription_ends.replace(tzinfo=timezone.utc)
            assert abs((actual_new_end - expected_new_end).total_seconds()) < 5
            
            # Check user notification was sent
            assert mock_bot.send_message.called, "Resilience: User notification message must be sent"


# ──────────────────────────────────────────────
# TEST 20: payment_service safely handles missing/None metadata
# ──────────────────────────────────────────────
async def test_payment_service_missing_metadata():
    await clear_tables()
    await db.add_user(10020, "ps_meta", "PS Meta User")
    
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_payment = {
        "metadata": None,
        "amount": {"value": "88.00"},
        "payment_method": {"id": "pm_meta_test"},
        "status": "succeeded"
    }

    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/TOKEN_META",
        "links": [],
        "token": "TOKEN_META",
        "proxies": {"vless": {}},
        "inbounds": {},
        "data_limit": 0,
        "data_limit_reset_strategy": "no_reset",
        "note": "",
        "on_hold_timeout": None,
        "on_hold_expire_duration": 0,
    }

    with patch("bot.payment_service.marzban_api") as mock_api, \
         patch("bot.payment_service.kb") as mock_kb:

        mock_api.extract_token = MagicMock(return_value="TOKEN_META")
        mock_api.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        mock_kb.success_payment_menu = MagicMock(return_value=MagicMock())

        from bot.payment_service import process_successful_payment
        result = await process_successful_payment(
            bot=mock_bot,
            user_id=10020,
            payment_id="pay_meta_001",
            payment=fake_payment,
            is_background=True,
        )

    assert_eq(result, True, "MissingMetadata: must return True on success")
    sub = await db.get_user_subscription(10020)
    assert sub is not None and sub[3] is True, "MissingMetadata: subscription active"


# ──────────────────────────────────────────────
# TEST 21: payment_service safely handles missing/None amount
# ──────────────────────────────────────────────
async def test_payment_service_missing_amount():
    await clear_tables()
    await db.add_user(10021, "ps_amt", "PS Amt User")
    
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_payment = {
        "metadata": {"plan": "1_month"},
        "amount": None,
        "payment_method": {"id": "pm_amt_test"},
        "status": "succeeded"
    }

    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/TOKEN_AMT",
        "links": [],
        "token": "TOKEN_AMT",
        "proxies": {"vless": {}},
        "inbounds": {},
        "data_limit": 0,
        "data_limit_reset_strategy": "no_reset",
        "note": "",
        "on_hold_timeout": None,
        "on_hold_expire_duration": 0,
    }

    with patch("bot.payment_service.marzban_api") as mock_api, \
         patch("bot.payment_service.kb") as mock_kb:

        mock_api.extract_token = MagicMock(return_value="TOKEN_AMT")
        mock_api.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        mock_kb.success_payment_menu = MagicMock(return_value=MagicMock())

        from bot.payment_service import process_successful_payment
        result = await process_successful_payment(
            bot=mock_bot,
            user_id=10021,
            payment_id="pay_amt_001",
            payment=fake_payment,
            is_background=True,
        )

    assert_eq(result, True, "MissingAmount: must return True on success")
    sub = await db.get_user_subscription(10021)
    assert sub is not None and sub[3] is True, "MissingAmount: subscription active"


# ──────────────────────────────────────────────
# TEST 22: Auto-renew failed payments lifecycle
# ──────────────────────────────────────────────
async def test_failed_payments_lifecycle():
    await clear_tables()
    
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        user = User(
            id=10022,
            username="failed_lifecycle",
            is_active=True,
            auto_renew=True,
            payment_method_id="pm_fail_life",
            subscription_ends=now + timedelta(hours=24),
            failed_payments=0,
            vpn_key="https://vpn.example.com/sub/TOKEN_FAIL"
        )
        session.add(user)
        await session.commit()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_canceled_payment = {
        "id": "pay_canceled_001",
        "status": "canceled",
        "amount": {"value": "88.00"}
    }

    with patch("bot.scheduler.create_auto_payment", AsyncMock(return_value=fake_canceled_payment)), \
         patch("bot.scheduler.marzban_api") as mock_marzban:

        mock_marzban.get_token = AsyncMock(return_value="token123")
        
        # 1. First attempt (24h window, failed_payments = 0)
        from bot.scheduler import auto_renew_subscriptions
        await auto_renew_subscriptions(mock_bot)

        # Check: failed_payments = 1, auto_renew is still True, 24h warning sent
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == 10022))).scalars().first()
            assert_eq(u.failed_payments, 1, "Lifecycle: failed_payments count")
            assert_eq(u.auto_renew, True, "Lifecycle: auto_renew should remain True")
        
        assert mock_bot.send_message.called
        assert "24 часа" in mock_bot.send_message.call_args[0][1], "Lifecycle: 24h warning"
        mock_bot.send_message.reset_mock()

        # Update user to 12h window
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == 10022))).scalars().first()
            u.subscription_ends = now + timedelta(hours=12)
            await session.commit()

        # 2. Second attempt (12h window, failed_payments = 1)
        await auto_renew_subscriptions(mock_bot)

        # Check: failed_payments = 2, auto_renew is still True, 12h warning sent
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == 10022))).scalars().first()
            assert_eq(u.failed_payments, 2, "Lifecycle: failed_payments count")
            assert_eq(u.auto_renew, True, "Lifecycle: auto_renew should remain True")
        
        assert "12 часов" in mock_bot.send_message.call_args[0][1], "Lifecycle: 12h warning"
        mock_bot.send_message.reset_mock()

        # Update user to 30m window
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == 10022))).scalars().first()
            u.subscription_ends = now + timedelta(minutes=30)
            await session.commit()

        # 3. Third attempt (30m window, failed_payments = 2)
        await auto_renew_subscriptions(mock_bot)

        # Check: failed_payments = 3, auto_renew becomes False, 30m warning sent
        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == 10022))).scalars().first()
            assert_eq(u.failed_payments, 3, "Lifecycle: failed_payments count")
            assert_eq(u.auto_renew, False, "Lifecycle: auto_renew must be disabled")
        
        assert "30 минут" in mock_bot.send_message.call_args[0][1], "Lifecycle: 30m warning"


# ──────────────────────────────────────────────
# TEST 23: Race Condition — Manual vs Background payment processing
# ──────────────────────────────────────────────
async def test_race_condition_manual_vs_background():
    await clear_tables()
    await db.add_user(10023, "race_m_bg", "Race M BG User")
    payment_id = "race_m_bg_pay_id"

    # Add to pending payments
    await db.add_pending_payment(payment_id, 10023, "1_month", 88.0)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=True)

    fake_succeeded_payment = {
        "id": payment_id,
        "status": "succeeded",
        "metadata": {"user_id": "10023", "plan": "1_month"},
        "amount": {"value": "88.00"},
        "payment_method": {"id": "pm_race_m_bg"}
    }

    mock_marzban_response = {
        "subscription_url": "https://vpn.example.com/sub/TOKEN_RACE",
        "links": [],
        "token": "TOKEN_RACE",
        "proxies": {"vless": {}},
        "inbounds": {},
        "data_limit": 0,
        "data_limit_reset_strategy": "no_reset",
        "note": "",
        "on_hold_timeout": None,
        "on_hold_expire_duration": 0,
    }

    with patch("bot.payment_service.marzban_api") as mock_api, \
         patch("bot.payment_service.kb") as mock_kb:

        mock_api.extract_token = MagicMock(return_value="TOKEN_RACE")
        mock_api.sync_user_subscription = AsyncMock(return_value=mock_marzban_response)
        mock_kb.success_payment_menu = MagicMock(return_value=MagicMock())

        from bot.payment_service import process_successful_payment
        
        # Concurrent processing of the exact same payment
        results = await asyncio.gather(
            process_successful_payment(mock_bot, 10023, payment_id, fake_succeeded_payment, is_background=False),
            process_successful_payment(mock_bot, 10023, payment_id, fake_succeeded_payment, is_background=True)
        )

        successes = sum(1 for r in results if r is True)
        failures = sum(1 for r in results if r is False)

        assert_eq(successes, 1, "RaceManualBg: successes")
        assert_eq(failures, 1, "RaceManualBg: failures")


# ──────────────────────────────────────────────
# TEST 24: Marzban API get_user returns None silently on 404
# ──────────────────────────────────────────────
async def test_marzban_404_silent():
    from bot.marzban_api import MarzbanAPI
    api = MarzbanAPI()
    api.base_url = "https://vpn.example.com"
    api.username = "admin"
    api.password = "pass"
    api.token = "fake_token"
    
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.text = "Not Found"
            
    async def fake_get(url, headers=None, timeout=None):
        return FakeResponse(404)
        
    with patch.object(api, "get_client") as mock_client:
        mock_client.return_value.get = AsyncMock(side_effect=fake_get)
        with patch("logging.error") as mock_log_err:
            res = await api.get_user("nonexistent_user")
            assert_eq(res, None, "Marzban 404: result should be None")
            assert_eq(mock_log_err.called, False, "Marzban 404: error log should NOT be called")


# ──────────────────────────────────────────────
# TEST 25: SQLite WAL mode and timeout are active in bot/database
# ──────────────────────────────────────────────
async def test_sqlite_wal_and_timeout():
    assert_eq(original_db_engine.url.drivername, "sqlite+aiosqlite", "SQLite driver")
    
    # Extract timeout from engine pool creator closure
    timeout = None
    if hasattr(original_db_engine.pool._creator, "__closure__") and original_db_engine.pool._creator.__closure__:
        for cell in original_db_engine.pool._creator.__closure__:
            val = cell.cell_contents
            if isinstance(val, dict) or (hasattr(val, "keys") and "timeout" in val):
                timeout = val.get("timeout")
                break
                
    assert_eq(timeout, 30.0, "SQLite timeout must be 30.0")
    
    from sqlalchemy import text
    async with original_db_engine.connect() as conn:
        journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar()
        
    assert_eq(journal_mode.lower(), "wal", "SQLite WAL mode")
    assert_eq(synchronous, 1, "SQLite synchronous NORMAL mode")


# ──────────────────────────────────────────────
# TEST 26: get_users_for_trial_reminder eligibility query
# ──────────────────────────────────────────────
async def test_trial_reminder_query():
    await clear_tables()
    now = datetime.now(timezone.utc)
    
    # 90 days ago is the pivot.
    # 90.5 days ago -> SHOULD be notified (within the 24h window [90, 91] days ago)
    # 89 days ago -> NO (too recent)
    # 92 days ago -> NO (older than the 24h window)
    # 90.5 days ago but IS ACTIVE -> NO (already active)
    async with async_session() as session:
        session.add_all([
            User(id=26001, username="tr1", is_active=False, last_trial_date=now - timedelta(days=90, hours=12)),
            User(id=26002, username="tr2", is_active=False, last_trial_date=now - timedelta(days=89)),
            User(id=26003, username="tr3", is_active=False, last_trial_date=now - timedelta(days=92)),
            User(id=26004, username="tr4", is_active=True, last_trial_date=now - timedelta(days=90, hours=12)),
        ])
        await session.commit()

    users = await db.get_users_for_trial_reminder()
    uids = {u.id for u in users}
    
    assert 26001 in uids, "TrialReminder: eligible user must be included"
    assert 26002 not in uids, "TrialReminder: recent trial must be excluded"
    assert 26003 not in uids, "TrialReminder: older trial must be excluded"
    assert 26004 not in uids, "TrialReminder: active user must be excluded"


# ──────────────────────────────────────────────
# TEST 27: sub_cache invalidation in deactivate_expired_subscriptions
# ──────────────────────────────────────────────
async def test_deactivate_expired_cache_invalidation():
    await clear_tables()
    now = datetime.now(timezone.utc)
    
    # Create an expired user
    await db.add_user(27001, "exp_c1", "Expired Cache User")
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == 27001))).scalars().first()
        user.subscription_ends = now - timedelta(hours=2)
        user.is_active = True
        await session.commit()
        
    # Populate the cache
    await db.get_user_subscription(27001)
    assert 27001 in db.sub_cache, "Cache: populated before deactivation"
    
    # Deactivate expired
    await db.deactivate_expired_subscriptions()
    
    # Verify cache invalidation
    assert 27001 not in db.sub_cache, "Cache: must be invalidated after deactivation"


# ──────────────────────────────────────────────
# TEST 28: check_pending_payments resilience (waiting_for_capture & network errors)
# ──────────────────────────────────────────────
async def test_check_pending_payments_resilience():
    await clear_tables()
    
    # Add two pending payments
    await db.add_pending_payment("pay_res_28_1", 28001, "1_month", 88.0)
    await db.add_pending_payment("pay_res_28_2", 28002, "1_month", 88.0)
    
    # Simulate YooKassa returning waiting_for_capture and an HTTP error
    class FakeResponse:
        def __init__(self, json_data, status_code=200):
            self.json_data = json_data
            self.status_code = status_code
        def json(self):
            return self.json_data
            
    async def fake_get(url, headers=None, timeout=None):
        if "pay_res_28_1" in url:
            # First payment is waiting for capture (2-stage payment)
            return FakeResponse({"status": "waiting_for_capture"})
        elif "pay_res_28_2" in url:
            # Second payment triggers HTTP 500 error from YooKassa
            return FakeResponse({}, 500)
        return FakeResponse({}, 404)
        
    mock_bot = MagicMock()
    
    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        from bot.scheduler import check_pending_payments
        # Should execute successfully without throwing exceptions
        await check_pending_payments(mock_bot)
        
    # Verify that BOTH payments are still in the PendingPayment queue
    async with async_session() as session:
        p1 = (await session.execute(select(PendingPayment).where(PendingPayment.payment_id == "pay_res_28_1"))).scalars().first()
        p2 = (await session.execute(select(PendingPayment).where(PendingPayment.payment_id == "pay_res_28_2"))).scalars().first()
        
        assert p1 is not None, "Pending check resilience: waiting_for_capture must remain in queue"
        assert p2 is not None, "Pending check resilience: payment that failed with API error must remain in queue"


# ──────────────────────────────────────────────
# RUNNER
# ──────────────────────────────────────────────
TESTS = [
    ("Race condition (5 concurrent workers, same payment_id)", test_race_condition_same_payment),
    ("is_payment_processed correctness", test_is_payment_processed),
    ("activate_subscription idempotency", test_idempotency),
    ("Subscription extension from active end date", test_subscription_extension),
    ("Trial flag set + trial unavailable after use", test_trial_flag),
    ("Pending payment CRUD (add/get/remove)", test_pending_payment_crud),
    ("get_pending_payments excludes already-processed", test_pending_excludes_processed),
    ("add_pending_payment is idempotent (no duplicates)", test_pending_no_duplicate),
    ("cleanup_old_pending_payments removes old records", test_pending_cleanup),
    ("get_users_for_auto_renew — window and fail_count logic", test_auto_renew_query),
    ("increment_failed_payments + auto_renew disabled at 3", test_failed_payments_counter),
    ("deactivate_expired_subscriptions", test_deactivate_expired),
    ("sub_cache invalidation after activation", test_cache_invalidation),
    ("payment_service background notification sent", test_payment_service_background_notification),
    ("payment_service duplicate payment returns False", test_payment_service_duplicate),
    ("save_payment_method + get/set auto_renew", test_save_payment_method),
    ("marzban_api.extract_token all cases", test_extract_token),
    ("update_subscription_date sets is_active correctly", test_update_subscription_date),
    ("Auto-renew background resilience (pending registration + check_pending retry)", test_auto_renew_background_resilience),
    ("Defensive programming: payment_service handles missing/None metadata", test_payment_service_missing_metadata),
    ("Defensive programming: payment_service handles missing/None amount", test_payment_service_missing_amount),
    ("Failed payments auto-renew lifecycle (24h -> 12h -> 30m -> disabled)", test_failed_payments_lifecycle),
    ("Race condition: concurrent manual vs background payment processing", test_race_condition_manual_vs_background),
    ("Defensive programming: Marzban API get_user returns None silently on 404", test_marzban_404_silent),
    ("Database connectivity: SQLite engine configured with 30.0s timeout and WAL mode", test_sqlite_wal_and_timeout),
    ("Trial reminders: eligible query includes only users with trial ended [90-91] days ago", test_trial_reminder_query),
    ("Cache resilience: deactivating expired subscriptions invalidates the subscription ends cache", test_deactivate_expired_cache_invalidation),
    ("Defensive checking: check_pending_payments is resilient to waiting_for_capture and API errors", test_check_pending_payments_resilience),
]


async def main():
    await setup()
    passed = 0
    failed = 0

    print("\n" + "═" * 65)
    print("  HealVPN Payment System — Test Suite")
    print("═" * 65)

    for name, fn in TESTS:
        try:
            await fn()
            print(f"  {PASS}  {name}")
            passed += 1
        except Exception as e:
            print(f"  {FAIL}  {name}")
            print(f"         {e}")
            failed += 1

    print("═" * 65)
    total = passed + failed
    if failed == 0:
        print(f"\n  \033[92m🎉 ALL {total} TESTS PASSED\033[0m\n")
    else:
        print(f"\n  \033[92m✅ {passed} passed\033[0m  |  \033[91m❌ {failed} failed\033[0m  (total: {total})\n")

    await teardown()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
