import aiosqlite
import os
from datetime import datetime

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'gpkdex.db')
DB_TIMEOUT = 30  # 30 second timeout for database locks


async def get_db_connection():
    """Get a database connection with proper settings."""
    db = await aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT)
    # Enable WAL mode for better concurrent access
    await db.execute('PRAGMA journal_mode=WAL')
    await db.execute('PRAGMA busy_timeout=30000')  # 30 second busy timeout
    return db


async def init_db():
    """Initialize the database with required tables."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        # Enable WAL mode for better concurrent access
        await db.execute('PRAGMA journal_mode=WAL')
        await db.execute('PRAGMA busy_timeout=30000')
        # Users table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                coins INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                total_cards_collected INTEGER DEFAULT 0,
                total_packs_opened INTEGER DEFAULT 0,
                last_daily TIMESTAMP,
                last_claim TIMESTAMP,
                last_leveled_claim TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Add new columns if they don't exist (for existing databases)
        try:
            await db.execute('ALTER TABLE users ADD COLUMN last_claim TIMESTAMP')
        except:
            pass
        try:
            await db.execute('ALTER TABLE users ADD COLUMN last_leveled_claim TIMESTAMP')
        except:
            pass

        # Cards table - stores all available cards
        await db.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                card_id INTEGER PRIMARY KEY AUTOINCREMENT,
                series TEXT NOT NULL,
                number INTEGER NOT NULL,
                variant TEXT NOT NULL,
                filename TEXT NOT NULL,
                rarity_weight REAL NOT NULL,
                craft_cost INTEGER DEFAULT 0,
                UNIQUE(series, number, variant)
            )
        ''')

        # Inventory table - user card collections
        await db.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                first_obtained TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (card_id) REFERENCES cards(card_id),
                UNIQUE(user_id, card_id)
            )
        ''')

        # Server settings table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id INTEGER PRIMARY KEY,
                spawn_channel_id INTEGER,
                spawn_interval_min INTEGER DEFAULT 10,
                spawn_interval_max INTEGER DEFAULT 30,
                last_spawn_at TIMESTAMP
            )
        ''')

        # Migration: Add last_spawn_at column if it doesn't exist
        try:
            await db.execute('ALTER TABLE server_settings ADD COLUMN last_spawn_at TIMESTAMP')
        except:
            pass

        # Active spawns table (supports both cards and puzzle pieces)
        # Check if we need to migrate the old table (card_id was NOT NULL)
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='active_spawns'")
        row = await cursor.fetchone()

        if row and 'card_id INTEGER NOT NULL' in (row[0] or ''):
            # Need to migrate: recreate table with nullable card_id
            await db.execute('ALTER TABLE active_spawns RENAME TO active_spawns_old')
            await db.execute('''
                CREATE TABLE active_spawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    card_id INTEGER,
                    piece_id INTEGER,
                    message_id INTEGER,
                    spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_by INTEGER,
                    claimed_at TIMESTAMP,
                    FOREIGN KEY (card_id) REFERENCES cards(card_id),
                    FOREIGN KEY (piece_id) REFERENCES puzzle_pieces(piece_id)
                )
            ''')
            await db.execute('''
                INSERT INTO active_spawns (id, guild_id, channel_id, card_id, message_id, spawned_at, claimed_by, claimed_at)
                SELECT id, guild_id, channel_id, card_id, message_id, spawned_at, claimed_by, claimed_at
                FROM active_spawns_old
            ''')
            await db.execute('DROP TABLE active_spawns_old')
            await db.commit()
        elif not row:
            # Table doesn't exist, create it fresh
            await db.execute('''
                CREATE TABLE IF NOT EXISTS active_spawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    card_id INTEGER,
                    piece_id INTEGER,
                    message_id INTEGER,
                    spawned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_by INTEGER,
                    claimed_at TIMESTAMP,
                    FOREIGN KEY (card_id) REFERENCES cards(card_id),
                    FOREIGN KEY (piece_id) REFERENCES puzzle_pieces(piece_id)
                )
            ''')

        # Add piece_id column if it doesn't exist (for tables created between migrations)
        try:
            await db.execute('ALTER TABLE active_spawns ADD COLUMN piece_id INTEGER')
        except:
            pass  # Column already exists

        # Puzzles table - stores puzzle definitions
        await db.execute('''
            CREATE TABLE IF NOT EXISTS puzzles (
                puzzle_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                rarity_weight REAL NOT NULL,
                pieces_required INTEGER DEFAULT 18,
                complete_filename TEXT NOT NULL,
                UNIQUE(name)
            )
        ''')

        # Puzzle pieces table - stores piece definitions
        await db.execute('''
            CREATE TABLE IF NOT EXISTS puzzle_pieces (
                piece_id INTEGER PRIMARY KEY AUTOINCREMENT,
                puzzle_id INTEGER NOT NULL,
                piece_number INTEGER NOT NULL,
                filename TEXT NOT NULL,
                FOREIGN KEY (puzzle_id) REFERENCES puzzles(puzzle_id),
                UNIQUE(puzzle_id, piece_number)
            )
        ''')

        # User puzzle inventory - tracks pieces owned by users
        await db.execute('''
            CREATE TABLE IF NOT EXISTS puzzle_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                piece_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                first_obtained TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (piece_id) REFERENCES puzzle_pieces(piece_id),
                UNIQUE(user_id, piece_id)
            )
        ''')

        # Completed puzzles - tracks which puzzles users have completed
        await db.execute('''
            CREATE TABLE IF NOT EXISTS completed_puzzles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                puzzle_id INTEGER NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                times_completed INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (puzzle_id) REFERENCES puzzles(puzzle_id),
                UNIQUE(user_id, puzzle_id)
            )
        ''')

        # Trades table - tracks trade sessions between users
        # Status: active (both users adding cards), locked (both users locked), completed, cancelled
        await db.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                initiator_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                initiator_locked_at TIMESTAMP,
                partner_locked_at TIMESTAMP,
                initiator_confirmed INTEGER DEFAULT 0,
                partner_confirmed INTEGER DEFAULT 0,
                last_update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (initiator_id) REFERENCES users(user_id),
                FOREIGN KEY (partner_id) REFERENCES users(user_id)
            )
        ''')

        # Migration: Add new trade columns for live trade system
        for col in ['initiator_locked_at', 'partner_locked_at', 'last_update_at']:
            try:
                await db.execute(f'ALTER TABLE trades ADD COLUMN {col} TIMESTAMP')
            except:
                pass
        for col in ['initiator_confirmed', 'partner_confirmed']:
            try:
                await db.execute(f'ALTER TABLE trades ADD COLUMN {col} INTEGER DEFAULT 0')
            except:
                pass

        # Trade items - cards offered in a trade
        await db.execute('''
            CREATE TABLE IF NOT EXISTS trade_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                card_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                FOREIGN KEY (trade_id) REFERENCES trades(trade_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (card_id) REFERENCES cards(card_id)
            )
        ''')

        # Trade puzzle items - puzzle pieces offered in a trade
        await db.execute('''
            CREATE TABLE IF NOT EXISTS trade_puzzle_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                piece_id INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                FOREIGN KEY (trade_id) REFERENCES trades(trade_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (piece_id) REFERENCES puzzle_pieces(piece_id)
            )
        ''')

        await db.commit()
        print("Database initialized successfully!")

async def get_user(user_id: int):
    """Get or create a user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = await cursor.fetchone()

        if not user:
            await db.execute(
                'INSERT INTO users (user_id, coins, xp, level) VALUES (?, 0, 0, 1)',
                (user_id,)
            )
            await db.commit()
            cursor = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = await cursor.fetchone()

        return dict(user)

async def update_user(user_id: int, **kwargs):
    """Update user fields."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        sets = ', '.join(f'{k} = ?' for k in kwargs.keys())
        values = list(kwargs.values()) + [user_id]
        await db.execute(f'UPDATE users SET {sets} WHERE user_id = ?', values)
        await db.commit()

async def add_coins(user_id: int, amount: int):
    """Add coins to a user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE users SET coins = coins + ? WHERE user_id = ?',
            (amount, user_id)
        )
        await db.commit()

async def add_xp(user_id: int, amount: int):
    """Add XP to a user and check for level up."""
    user = await get_user(user_id)
    new_xp = user['xp'] + amount
    new_level = calculate_level(new_xp)

    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE users SET xp = ?, level = ? WHERE user_id = ?',
            (new_xp, new_level, user_id)
        )
        await db.commit()

    return new_level > user['level'], new_level

def calculate_level(xp: int) -> int:
    """Calculate level from XP. XP thresholds: 0, 500, 1500, 3000, 5000, 7500, 10500..."""
    level = 1
    xp_needed = 0
    increment = 500

    while xp >= xp_needed:
        level += 1
        xp_needed += increment
        increment += 500

    return level - 1

def xp_for_level(level: int) -> int:
    """Calculate total XP needed for a level."""
    if level <= 1:
        return 0
    total = 0
    increment = 500
    for _ in range(1, level):
        total += increment
        increment += 500
    return total

async def get_inventory(user_id: int):
    """Get a user's card inventory."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT i.*, c.series, c.number, c.variant, c.filename, c.rarity_weight
            FROM inventory i
            JOIN cards c ON i.card_id = c.card_id
            WHERE i.user_id = ?
            ORDER BY c.series, c.number, c.variant
        ''', (user_id,))
        return [dict(row) for row in await cursor.fetchall()]

async def add_card_to_inventory(user_id: int, card_id: int) -> bool:
    """Add a card to user's inventory. Returns True if it's a new card."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        # Check if user already has this card
        cursor = await db.execute(
            'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
            (user_id, card_id)
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                'UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND card_id = ?',
                (user_id, card_id)
            )
            is_new = False
        else:
            await db.execute(
                'INSERT INTO inventory (user_id, card_id, quantity) VALUES (?, ?, 1)',
                (user_id, card_id)
            )
            is_new = True

        await db.execute(
            'UPDATE users SET total_cards_collected = total_cards_collected + 1 WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()
        return is_new

async def remove_cards_from_inventory(user_id: int, card_id: int, amount: int) -> bool:
    """Remove cards from inventory. Returns True if successful."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
            (user_id, card_id)
        )
        row = await cursor.fetchone()

        if not row or row[0] < amount:
            return False

        new_quantity = row[0] - amount
        if new_quantity <= 0:
            await db.execute(
                'DELETE FROM inventory WHERE user_id = ? AND card_id = ?',
                (user_id, card_id)
            )
        else:
            await db.execute(
                'UPDATE inventory SET quantity = ? WHERE user_id = ? AND card_id = ?',
                (new_quantity, user_id, card_id)
            )

        await db.commit()
        return True

async def get_card_by_id(card_id: int):
    """Get a card by ID."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM cards WHERE card_id = ?', (card_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_card_by_name(series: str, number: int, variant: str):
    """Get a card by series, number, and variant."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM cards WHERE series = ? AND number = ? AND variant = ?',
            (series, number, variant)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_cards():
    """Get all cards."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM cards ORDER BY series, number, variant')
        return [dict(row) for row in await cursor.fetchall()]

async def get_server_settings(guild_id: int):
    """Get or create server settings."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM server_settings WHERE guild_id = ?', (guild_id,)
        )
        settings = await cursor.fetchone()

        if not settings:
            await db.execute(
                'INSERT INTO server_settings (guild_id) VALUES (?)',
                (guild_id,)
            )
            await db.commit()
            cursor = await db.execute(
                'SELECT * FROM server_settings WHERE guild_id = ?', (guild_id,)
            )
            settings = await cursor.fetchone()

        return dict(settings)

async def set_spawn_channel(guild_id: int, channel_id: int):
    """Set the spawn channel for a server."""
    await get_server_settings(guild_id)  # Ensure exists
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE server_settings SET spawn_channel_id = ? WHERE guild_id = ?',
            (channel_id, guild_id)
        )
        await db.commit()


async def update_last_spawn_time(guild_id: int):
    """Update the last spawn time for a server."""
    await get_server_settings(guild_id)  # Ensure exists
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE server_settings SET last_spawn_at = ? WHERE guild_id = ?',
            (datetime.utcnow(), guild_id)
        )
        await db.commit()


async def create_spawn(guild_id: int, channel_id: int, card_id: int, message_id: int):
    """Create a new card spawn."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'INSERT INTO active_spawns (guild_id, channel_id, card_id, message_id) VALUES (?, ?, ?, ?)',
            (guild_id, channel_id, card_id, message_id)
        )
        await db.commit()

async def create_puzzle_spawn(guild_id: int, channel_id: int, piece_id: int, message_id: int):
    """Create a new puzzle piece spawn."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'INSERT INTO active_spawns (guild_id, channel_id, piece_id, message_id) VALUES (?, ?, ?, ?)',
            (guild_id, channel_id, piece_id, message_id)
        )
        await db.commit()

async def get_active_spawn(guild_id: int):
    """Get the active spawn for a guild."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM active_spawns WHERE guild_id = ? AND claimed_by IS NULL ORDER BY spawned_at DESC LIMIT 1',
            (guild_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

async def claim_spawn(spawn_id: int, user_id: int):
    """Claim a spawn."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE active_spawns SET claimed_by = ?, claimed_at = ? WHERE id = ?',
            (user_id, datetime.utcnow(), spawn_id)
        )
        await db.commit()

async def get_collection_stats(user_id: int):
    """Get collection completion stats for a user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Total cards available
        cursor = await db.execute('SELECT COUNT(*) FROM cards')
        total_cards = (await cursor.fetchone())[0]

        # Unique cards owned
        cursor = await db.execute(
            'SELECT COUNT(DISTINCT card_id) FROM inventory WHERE user_id = ?',
            (user_id,)
        )
        owned_unique = (await cursor.fetchone())[0]

        # Stats by series
        cursor = await db.execute('''
            SELECT c.series, c.variant, COUNT(*) as total,
                   (SELECT COUNT(*) FROM inventory i
                    JOIN cards c2 ON i.card_id = c2.card_id
                    WHERE i.user_id = ? AND c2.series = c.series AND c2.variant = c.variant) as owned
            FROM cards c
            GROUP BY c.series, c.variant
            ORDER BY c.series, c.variant
        ''', (user_id,))
        series_stats = [dict(row) for row in await cursor.fetchall()]

        return {
            'total_cards': total_cards,
            'owned_unique': owned_unique,
            'completion_percent': (owned_unique / total_cards * 100) if total_cards > 0 else 0,
            'series_stats': series_stats
        }


async def get_series_completion(user_id: int):
    """Get card counts per series for a user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get total cards per series
        cursor = await db.execute('''
            SELECT series, COUNT(*) as total
            FROM cards
            GROUP BY series
        ''')
        totals = {row['series']: row['total'] for row in await cursor.fetchall()}

        # Get owned cards per series for user
        cursor = await db.execute('''
            SELECT c.series, COUNT(DISTINCT i.card_id) as owned
            FROM inventory i
            JOIN cards c ON i.card_id = c.card_id
            WHERE i.user_id = ?
            GROUP BY c.series
        ''', (user_id,))
        owned = {row['series']: row['owned'] for row in await cursor.fetchall()}

        # Combine into result
        result = {}
        for series, total in totals.items():
            result[series] = {
                'total': total,
                'owned': owned.get(series, 0)
            }

        return result


async def get_leaderboard(limit: int = 10):
    """Get top collectors by unique cards."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT u.user_id, u.level, u.xp, u.coins,
                   COUNT(DISTINCT i.card_id) as unique_cards,
                   u.total_cards_collected
            FROM users u
            LEFT JOIN inventory i ON u.user_id = i.user_id
            GROUP BY u.user_id
            ORDER BY unique_cards DESC, u.xp DESC
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in await cursor.fetchall()]

# ============== PUZZLE FUNCTIONS ==============

async def get_all_puzzles():
    """Get all puzzles."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM puzzles ORDER BY rarity_weight')
        return [dict(row) for row in await cursor.fetchall()]

async def get_puzzle_by_id(puzzle_id: int):
    """Get a puzzle by ID."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM puzzles WHERE puzzle_id = ?', (puzzle_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_puzzle_pieces(puzzle_id: int):
    """Get all pieces for a puzzle."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            'SELECT * FROM puzzle_pieces WHERE puzzle_id = ? ORDER BY piece_number',
            (puzzle_id,)
        )
        return [dict(row) for row in await cursor.fetchall()]

async def get_random_puzzle_piece():
    """Get a random puzzle piece based on puzzle rarity weights."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get all puzzles with their weights
        cursor = await db.execute('SELECT * FROM puzzles')
        puzzles = [dict(row) for row in await cursor.fetchall()]

        if not puzzles:
            return None, None

        # Weighted random selection for puzzle
        import random
        total_weight = sum(p['rarity_weight'] for p in puzzles)
        r = random.uniform(0, total_weight)
        cumulative = 0

        selected_puzzle = puzzles[-1]
        for puzzle in puzzles:
            cumulative += puzzle['rarity_weight']
            if r <= cumulative:
                selected_puzzle = puzzle
                break

        # Get a random piece from the selected puzzle
        cursor = await db.execute(
            'SELECT * FROM puzzle_pieces WHERE puzzle_id = ?',
            (selected_puzzle['puzzle_id'],)
        )
        pieces = [dict(row) for row in await cursor.fetchall()]

        if not pieces:
            return None, None

        selected_piece = random.choice(pieces)
        return selected_puzzle, selected_piece

async def add_puzzle_piece_to_inventory(user_id: int, piece_id: int) -> bool:
    """Add a puzzle piece to user's inventory. Returns True if it's a new piece."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
            (user_id, piece_id)
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                'UPDATE puzzle_inventory SET quantity = quantity + 1 WHERE user_id = ? AND piece_id = ?',
                (user_id, piece_id)
            )
            is_new = False
        else:
            await db.execute(
                'INSERT INTO puzzle_inventory (user_id, piece_id, quantity) VALUES (?, ?, 1)',
                (user_id, piece_id)
            )
            is_new = True

        await db.commit()
        return is_new

async def get_user_puzzle_pieces(user_id: int, puzzle_id: int = None):
    """Get a user's puzzle pieces, optionally filtered by puzzle."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        if puzzle_id:
            cursor = await db.execute('''
                SELECT pi.*, pp.puzzle_id, pp.piece_number, pp.filename, p.name as puzzle_name
                FROM puzzle_inventory pi
                JOIN puzzle_pieces pp ON pi.piece_id = pp.piece_id
                JOIN puzzles p ON pp.puzzle_id = p.puzzle_id
                WHERE pi.user_id = ? AND pp.puzzle_id = ?
                ORDER BY pp.piece_number
            ''', (user_id, puzzle_id))
        else:
            cursor = await db.execute('''
                SELECT pi.*, pp.puzzle_id, pp.piece_number, pp.filename, p.name as puzzle_name
                FROM puzzle_inventory pi
                JOIN puzzle_pieces pp ON pi.piece_id = pp.piece_id
                JOIN puzzles p ON pp.puzzle_id = p.puzzle_id
                WHERE pi.user_id = ?
                ORDER BY pp.puzzle_id, pp.piece_number
            ''', (user_id,))

        return [dict(row) for row in await cursor.fetchall()]

async def check_puzzle_completion(user_id: int, puzzle_id: int) -> bool:
    """Check if a user has all pieces to complete a puzzle."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get puzzle info
        cursor = await db.execute('SELECT pieces_required FROM puzzles WHERE puzzle_id = ?', (puzzle_id,))
        puzzle = await cursor.fetchone()
        if not puzzle:
            return False

        pieces_required = puzzle['pieces_required']

        # Count unique pieces owned (with at least 1 quantity)
        cursor = await db.execute('''
            SELECT COUNT(DISTINCT pp.piece_number) as owned_pieces
            FROM puzzle_inventory pi
            JOIN puzzle_pieces pp ON pi.piece_id = pp.piece_id
            WHERE pi.user_id = ? AND pp.puzzle_id = ? AND pi.quantity >= 1
        ''', (user_id, puzzle_id))

        result = await cursor.fetchone()
        return result['owned_pieces'] >= pieces_required

async def complete_puzzle(user_id: int, puzzle_id: int) -> bool:
    """Complete a puzzle - consume one of each piece and award completion."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get all pieces for this puzzle
        cursor = await db.execute(
            'SELECT piece_id FROM puzzle_pieces WHERE puzzle_id = ?',
            (puzzle_id,)
        )
        pieces = await cursor.fetchall()

        # Remove one of each piece from inventory
        for piece in pieces:
            piece_id = piece['piece_id']

            # Get current quantity
            cursor = await db.execute(
                'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                (user_id, piece_id)
            )
            row = await cursor.fetchone()

            if not row or row['quantity'] < 1:
                return False  # Missing a piece

            new_quantity = row['quantity'] - 1
            if new_quantity <= 0:
                await db.execute(
                    'DELETE FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                    (user_id, piece_id)
                )
            else:
                await db.execute(
                    'UPDATE puzzle_inventory SET quantity = ? WHERE user_id = ? AND piece_id = ?',
                    (new_quantity, user_id, piece_id)
                )

        # Record the completion
        cursor = await db.execute(
            'SELECT times_completed FROM completed_puzzles WHERE user_id = ? AND puzzle_id = ?',
            (user_id, puzzle_id)
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                'UPDATE completed_puzzles SET times_completed = times_completed + 1, completed_at = ? WHERE user_id = ? AND puzzle_id = ?',
                (datetime.utcnow(), user_id, puzzle_id)
            )
        else:
            await db.execute(
                'INSERT INTO completed_puzzles (user_id, puzzle_id) VALUES (?, ?)',
                (user_id, puzzle_id)
            )

        await db.commit()
        return True

async def get_user_completed_puzzles(user_id: int):
    """Get all puzzles a user has completed."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT cp.*, p.name, p.description, p.complete_filename
            FROM completed_puzzles cp
            JOIN puzzles p ON cp.puzzle_id = p.puzzle_id
            WHERE cp.user_id = ?
            ORDER BY cp.completed_at DESC
        ''', (user_id,))
        return [dict(row) for row in await cursor.fetchall()]

async def get_puzzle_progress(user_id: int):
    """Get progress on all puzzles for a user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get all puzzles
        cursor = await db.execute('SELECT * FROM puzzles ORDER BY rarity_weight')
        puzzles = [dict(row) for row in await cursor.fetchall()]

        progress = []
        for puzzle in puzzles:
            # Count pieces owned
            cursor = await db.execute('''
                SELECT COUNT(DISTINCT pp.piece_number) as owned,
                       GROUP_CONCAT(pp.piece_number) as owned_pieces
                FROM puzzle_inventory pi
                JOIN puzzle_pieces pp ON pi.piece_id = pp.piece_id
                WHERE pi.user_id = ? AND pp.puzzle_id = ? AND pi.quantity >= 1
            ''', (user_id, puzzle['puzzle_id']))
            result = await cursor.fetchone()

            # Check if completed
            cursor = await db.execute(
                'SELECT times_completed FROM completed_puzzles WHERE user_id = ? AND puzzle_id = ?',
                (user_id, puzzle['puzzle_id'])
            )
            completed = await cursor.fetchone()

            progress.append({
                'puzzle': puzzle,
                'owned_pieces': result['owned'] or 0,
                'total_pieces': puzzle['pieces_required'],
                'owned_piece_numbers': result['owned_pieces'].split(',') if result['owned_pieces'] else [],
                'times_completed': completed['times_completed'] if completed else 0
            })

        return progress


# ============== TRADE FUNCTIONS ==============

async def create_trade(initiator_id: int, partner_id: int, guild_id: int) -> int:
    """Create a new trade between two users. Returns the trade_id."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'INSERT INTO trades (initiator_id, partner_id, guild_id) VALUES (?, ?, ?)',
            (initiator_id, partner_id, guild_id)
        )
        trade_id = cursor.lastrowid
        await db.commit()
        return trade_id


async def get_trade(trade_id: int):
    """Get a trade by ID."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_active_trade_for_user(user_id: int, guild_id: int):
    """Get active trade for a user in a guild (as initiator or partner)."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT * FROM trades
            WHERE guild_id = ?
            AND (initiator_id = ? OR partner_id = ?)
            AND status NOT IN ('completed', 'cancelled')
            ORDER BY created_at DESC LIMIT 1
        ''', (guild_id, user_id, user_id))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_trade_items(trade_id: int, user_id: int = None):
    """Get items in a trade, optionally filtered by user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        if user_id:
            cursor = await db.execute('''
                SELECT ti.*, c.series, c.number, c.variant, c.filename, c.rarity_weight
                FROM trade_items ti
                JOIN cards c ON ti.card_id = c.card_id
                WHERE ti.trade_id = ? AND ti.user_id = ?
                ORDER BY c.series, c.number, c.variant
            ''', (trade_id, user_id))
        else:
            cursor = await db.execute('''
                SELECT ti.*, c.series, c.number, c.variant, c.filename, c.rarity_weight
                FROM trade_items ti
                JOIN cards c ON ti.card_id = c.card_id
                WHERE ti.trade_id = ?
                ORDER BY ti.user_id, c.series, c.number, c.variant
            ''', (trade_id,))
        return [dict(row) for row in await cursor.fetchall()]


async def add_trade_item(trade_id: int, user_id: int, card_id: int, quantity: int = 1):
    """Add a card to a trade offer."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        # Check if item already exists
        cursor = await db.execute(
            'SELECT id, quantity FROM trade_items WHERE trade_id = ? AND user_id = ? AND card_id = ?',
            (trade_id, user_id, card_id)
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                'UPDATE trade_items SET quantity = quantity + ? WHERE id = ?',
                (quantity, existing[0])
            )
        else:
            await db.execute(
                'INSERT INTO trade_items (trade_id, user_id, card_id, quantity) VALUES (?, ?, ?, ?)',
                (trade_id, user_id, card_id, quantity)
            )

        await db.execute(
            'UPDATE trades SET updated_at = ? WHERE trade_id = ?',
            (datetime.utcnow(), trade_id)
        )
        await db.commit()


async def remove_trade_item(trade_id: int, user_id: int, card_id: int, quantity: int = 1):
    """Remove a card from a trade offer."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT id, quantity FROM trade_items WHERE trade_id = ? AND user_id = ? AND card_id = ?',
            (trade_id, user_id, card_id)
        )
        existing = await cursor.fetchone()

        if existing:
            new_qty = existing[1] - quantity
            if new_qty <= 0:
                await db.execute('DELETE FROM trade_items WHERE id = ?', (existing[0],))
            else:
                await db.execute('UPDATE trade_items SET quantity = ? WHERE id = ?', (new_qty, existing[0]))

        await db.execute(
            'UPDATE trades SET updated_at = ? WHERE trade_id = ?',
            (datetime.utcnow(), trade_id)
        )
        await db.commit()


async def clear_trade_items(trade_id: int, user_id: int):
    """Clear all items from a user's trade offer."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'DELETE FROM trade_items WHERE trade_id = ? AND user_id = ?',
            (trade_id, user_id)
        )
        await db.commit()


async def update_trade_status(trade_id: int, status: str):
    """Update the status of a trade."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE trades SET status = ?, updated_at = ? WHERE trade_id = ?',
            (status, datetime.utcnow(), trade_id)
        )
        await db.commit()


async def lock_trade_proposal(trade_id: int, user_id: int) -> dict:
    """Lock a user's proposal. Returns trade info with lock status."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        trade = await cursor.fetchone()
        if not trade:
            return None

        now = datetime.utcnow()
        is_initiator = user_id == trade['initiator_id']

        if is_initiator:
            await db.execute(
                'UPDATE trades SET initiator_locked_at = ?, last_update_at = ?, updated_at = ? WHERE trade_id = ?',
                (now, now, now, trade_id)
            )
        else:
            await db.execute(
                'UPDATE trades SET partner_locked_at = ?, last_update_at = ?, updated_at = ? WHERE trade_id = ?',
                (now, now, now, trade_id)
            )
        await db.commit()

        # Fetch updated trade
        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        trade = await cursor.fetchone()

        # Check if both locked - update status to 'locked'
        if trade['initiator_locked_at'] and trade['partner_locked_at']:
            await db.execute(
                'UPDATE trades SET status = ? WHERE trade_id = ?',
                ('locked', trade_id)
            )
            await db.commit()
            cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
            trade = await cursor.fetchone()

        return dict(trade)


async def confirm_trade(trade_id: int, user_id: int) -> dict:
    """Confirm the trade for a user. Returns updated trade info."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        trade = await cursor.fetchone()
        if not trade:
            return None

        now = datetime.utcnow()
        is_initiator = user_id == trade['initiator_id']

        if is_initiator:
            await db.execute(
                'UPDATE trades SET initiator_confirmed = 1, updated_at = ? WHERE trade_id = ?',
                (now, trade_id)
            )
        else:
            await db.execute(
                'UPDATE trades SET partner_confirmed = 1, updated_at = ? WHERE trade_id = ?',
                (now, trade_id)
            )
        await db.commit()

        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        return dict(await cursor.fetchone())


async def update_trade_last_update(trade_id: int):
    """Update the last_update_at timestamp for a trade."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        now = datetime.utcnow()
        await db.execute(
            'UPDATE trades SET last_update_at = ?, updated_at = ? WHERE trade_id = ?',
            (now, now, trade_id)
        )
        await db.commit()


async def unlock_trade(trade_id: int):
    """Unlock both users' proposals (reset locks and confirmations)."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute('''
            UPDATE trades
            SET initiator_locked_at = NULL, partner_locked_at = NULL,
                initiator_confirmed = 0, partner_confirmed = 0,
                status = 'active', updated_at = ?
            WHERE trade_id = ?
        ''', (datetime.utcnow(), trade_id))
        await db.commit()


async def execute_trade(trade_id: int) -> bool:
    """Execute a trade - transfer cards and puzzle pieces between users. Returns True if successful."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row

        # Get trade info
        cursor = await db.execute('SELECT * FROM trades WHERE trade_id = ?', (trade_id,))
        trade = await cursor.fetchone()
        if not trade:
            return False

        initiator_id = trade['initiator_id']
        partner_id = trade['partner_id']

        # Get all card trade items
        cursor = await db.execute('''
            SELECT ti.*, c.series, c.number, c.variant
            FROM trade_items ti
            JOIN cards c ON ti.card_id = c.card_id
            WHERE ti.trade_id = ?
        ''', (trade_id,))
        card_items = [dict(row) for row in await cursor.fetchall()]

        # Get all puzzle piece trade items
        cursor = await db.execute('''
            SELECT tpi.*, pp.puzzle_id, pp.piece_number
            FROM trade_puzzle_items tpi
            JOIN puzzle_pieces pp ON tpi.piece_id = pp.piece_id
            WHERE tpi.trade_id = ?
        ''', (trade_id,))
        puzzle_items = [dict(row) for row in await cursor.fetchall()]

        # Verify both users have the cards they're offering
        for item in card_items:
            cursor = await db.execute(
                'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
                (item['user_id'], item['card_id'])
            )
            inv = await cursor.fetchone()
            if not inv or inv['quantity'] < item['quantity']:
                return False  # User doesn't have enough of this card

        # Verify both users have the puzzle pieces they're offering
        for item in puzzle_items:
            cursor = await db.execute(
                'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                (item['user_id'], item['piece_id'])
            )
            inv = await cursor.fetchone()
            if not inv or inv['quantity'] < item['quantity']:
                return False  # User doesn't have enough of this piece

        # Execute the card trades
        for item in card_items:
            from_user = item['user_id']
            to_user = partner_id if from_user == initiator_id else initiator_id

            # Remove from sender
            cursor = await db.execute(
                'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
                (from_user, item['card_id'])
            )
            current = await cursor.fetchone()
            new_qty = current['quantity'] - item['quantity']

            if new_qty <= 0:
                await db.execute(
                    'DELETE FROM inventory WHERE user_id = ? AND card_id = ?',
                    (from_user, item['card_id'])
                )
            else:
                await db.execute(
                    'UPDATE inventory SET quantity = ? WHERE user_id = ? AND card_id = ?',
                    (new_qty, from_user, item['card_id'])
                )

            # Add to receiver
            cursor = await db.execute(
                'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
                (to_user, item['card_id'])
            )
            existing = await cursor.fetchone()

            if existing:
                await db.execute(
                    'UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND card_id = ?',
                    (item['quantity'], to_user, item['card_id'])
                )
            else:
                await db.execute(
                    'INSERT INTO inventory (user_id, card_id, quantity) VALUES (?, ?, ?)',
                    (to_user, item['card_id'], item['quantity'])
                )

        # Execute the puzzle piece trades
        for item in puzzle_items:
            from_user = item['user_id']
            to_user = partner_id if from_user == initiator_id else initiator_id

            # Remove from sender
            cursor = await db.execute(
                'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                (from_user, item['piece_id'])
            )
            current = await cursor.fetchone()
            new_qty = current['quantity'] - item['quantity']

            if new_qty <= 0:
                await db.execute(
                    'DELETE FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                    (from_user, item['piece_id'])
                )
            else:
                await db.execute(
                    'UPDATE puzzle_inventory SET quantity = ? WHERE user_id = ? AND piece_id = ?',
                    (new_qty, from_user, item['piece_id'])
                )

            # Add to receiver
            cursor = await db.execute(
                'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
                (to_user, item['piece_id'])
            )
            existing = await cursor.fetchone()

            if existing:
                await db.execute(
                    'UPDATE puzzle_inventory SET quantity = quantity + ? WHERE user_id = ? AND piece_id = ?',
                    (item['quantity'], to_user, item['piece_id'])
                )
            else:
                await db.execute(
                    'INSERT INTO puzzle_inventory (user_id, piece_id, quantity) VALUES (?, ?, ?)',
                    (to_user, item['piece_id'], item['quantity'])
                )

        # Mark trade as completed
        await db.execute(
            'UPDATE trades SET status = ?, updated_at = ? WHERE trade_id = ?',
            ('completed', datetime.utcnow(), trade_id)
        )

        await db.commit()
        return True


async def cancel_trade(trade_id: int):
    """Cancel a trade."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        await db.execute(
            'UPDATE trades SET status = ?, updated_at = ? WHERE trade_id = ?',
            ('cancelled', datetime.utcnow(), trade_id)
        )
        # Clean up trade items (cards and puzzle pieces)
        await db.execute('DELETE FROM trade_items WHERE trade_id = ?', (trade_id,))
        await db.execute('DELETE FROM trade_puzzle_items WHERE trade_id = ?', (trade_id,))
        await db.commit()


async def get_user_card_quantity(user_id: int, card_id: int) -> int:
    """Get the quantity of a specific card a user owns."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT quantity FROM inventory WHERE user_id = ? AND card_id = ?',
            (user_id, card_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


# ============== PUZZLE PIECE TRADE FUNCTIONS ==============

async def get_trade_puzzle_items(trade_id: int, user_id: int = None):
    """Get puzzle pieces in a trade, optionally filtered by user."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        if user_id:
            cursor = await db.execute('''
                SELECT tpi.*, pp.puzzle_id, pp.piece_number, pp.filename, p.name as puzzle_name
                FROM trade_puzzle_items tpi
                JOIN puzzle_pieces pp ON tpi.piece_id = pp.piece_id
                JOIN puzzles p ON pp.puzzle_id = p.puzzle_id
                WHERE tpi.trade_id = ? AND tpi.user_id = ?
                ORDER BY p.name, pp.piece_number
            ''', (trade_id, user_id))
        else:
            cursor = await db.execute('''
                SELECT tpi.*, pp.puzzle_id, pp.piece_number, pp.filename, p.name as puzzle_name
                FROM trade_puzzle_items tpi
                JOIN puzzle_pieces pp ON tpi.piece_id = pp.piece_id
                JOIN puzzles p ON pp.puzzle_id = p.puzzle_id
                WHERE tpi.trade_id = ?
                ORDER BY tpi.user_id, p.name, pp.piece_number
            ''', (trade_id,))
        return [dict(row) for row in await cursor.fetchall()]


async def add_trade_puzzle_item(trade_id: int, user_id: int, piece_id: int, quantity: int = 1):
    """Add a puzzle piece to a trade offer."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT id, quantity FROM trade_puzzle_items WHERE trade_id = ? AND user_id = ? AND piece_id = ?',
            (trade_id, user_id, piece_id)
        )
        existing = await cursor.fetchone()

        if existing:
            await db.execute(
                'UPDATE trade_puzzle_items SET quantity = quantity + ? WHERE id = ?',
                (quantity, existing[0])
            )
        else:
            await db.execute(
                'INSERT INTO trade_puzzle_items (trade_id, user_id, piece_id, quantity) VALUES (?, ?, ?, ?)',
                (trade_id, user_id, piece_id, quantity)
            )

        await db.execute(
            'UPDATE trades SET updated_at = ? WHERE trade_id = ?',
            (datetime.utcnow(), trade_id)
        )
        await db.commit()


async def remove_trade_puzzle_item(trade_id: int, user_id: int, piece_id: int, quantity: int = 1):
    """Remove a puzzle piece from a trade offer."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT id, quantity FROM trade_puzzle_items WHERE trade_id = ? AND user_id = ? AND piece_id = ?',
            (trade_id, user_id, piece_id)
        )
        existing = await cursor.fetchone()

        if existing:
            new_qty = existing[1] - quantity
            if new_qty <= 0:
                await db.execute('DELETE FROM trade_puzzle_items WHERE id = ?', (existing[0],))
            else:
                await db.execute('UPDATE trade_puzzle_items SET quantity = ? WHERE id = ?', (new_qty, existing[0]))

        await db.execute(
            'UPDATE trades SET updated_at = ? WHERE trade_id = ?',
            (datetime.utcnow(), trade_id)
        )
        await db.commit()


async def get_user_puzzle_piece_quantity(user_id: int, piece_id: int) -> int:
    """Get the quantity of a specific puzzle piece a user owns."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        cursor = await db.execute(
            'SELECT quantity FROM puzzle_inventory WHERE user_id = ? AND piece_id = ?',
            (user_id, piece_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_puzzle_piece_by_id(piece_id: int):
    """Get a puzzle piece by ID with puzzle info."""
    async with aiosqlite.connect(DATABASE_PATH, timeout=DB_TIMEOUT) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT pp.*, p.name as puzzle_name
            FROM puzzle_pieces pp
            JOIN puzzles p ON pp.puzzle_id = p.puzzle_id
            WHERE pp.piece_id = ?
        ''', (piece_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
