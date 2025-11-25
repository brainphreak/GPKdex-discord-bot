# Database Schema Documentation

The GPK Dex Bot uses SQLite with Write-Ahead Logging (WAL) mode for concurrent access.

## Database Configuration

- **File**: `gpkdex.db`
- **Mode**: WAL (Write-Ahead Logging)
- **Timeout**: 30 seconds
- **Busy Timeout**: 30000ms

## Tables

### users
Stores player profile information.

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Discord user ID (Primary Key) |
| coins | INTEGER | Current coin balance (Default: 1000) |
| xp | INTEGER | Total experience points (Default: 0) |
| level | INTEGER | Current player level (Default: 1) |
| created_at | TIMESTAMP | Account creation time |

### cards
Master list of all available cards in the game.

| Column | Type | Description |
|--------|------|-------------|
| card_id | TEXT | Unique card identifier (Primary Key) |
| series | TEXT | Series code (os1, fb1, wb, tv_drama, etc.) |
| number | INTEGER | Card number within series |
| variant | TEXT | Card variant ('a' or 'b') |
| name | TEXT | Card name |
| image_path | TEXT | Path to card image file |

**Card ID Format**: `{series}-{number}{variant}`
- Examples: `os1-1a`, `fb2-25b`, `wb-40a`, `tv_drama-15b`

### inventory
Tracks which cards each player owns and quantity.

| Column | Type | Description |
|--------|------|-------------|
| inventory_id | INTEGER | Auto-increment primary key |
| user_id | INTEGER | Discord user ID (Foreign Key → users) |
| card_id | TEXT | Card identifier (Foreign Key → cards) |
| quantity | INTEGER | Number owned (Default: 1) |
| obtained_at | TIMESTAMP | When first obtained |

**Indexes**: 
- `idx_inventory_user` on (user_id)
- `idx_inventory_card` on (card_id)

### puzzles
Master list of all puzzle sets.

| Column | Type | Description |
|--------|------|-------------|
| puzzle_id | TEXT | Unique puzzle identifier (Primary Key) |
| series | TEXT | Associated series |
| name | TEXT | Puzzle name |
| pieces | INTEGER | Total pieces needed (Always 9) |

**Puzzle ID Format**: `{series}_puzzle`
- Examples: `os1_puzzle`, `fb1_puzzle`, `tv_drama_puzzle`

### puzzle_inventory
Tracks puzzle pieces owned by players.

| Column | Type | Description |
|--------|------|-------------|
| piece_id | INTEGER | Auto-increment primary key |
| user_id | INTEGER | Discord user ID (Foreign Key → users) |
| puzzle_id | TEXT | Puzzle identifier (Foreign Key → puzzles) |
| piece_number | INTEGER | Piece number (1-9) |
| quantity | INTEGER | Number owned (Default: 1) |
| obtained_at | TIMESTAMP | When first obtained |

**Indexes**:
- `idx_puzzle_inventory_user` on (user_id)
- `idx_puzzle_inventory_puzzle` on (puzzle_id)

### trades
Active trading sessions between players.

| Column | Type | Description |
|--------|------|-------------|
| trade_id | INTEGER | Auto-increment primary key |
| user1_id | INTEGER | First trader's Discord ID |
| user2_id | INTEGER | Second trader's Discord ID |
| user1_confirmed | INTEGER | User 1 confirmation (0/1) |
| user2_confirmed | INTEGER | User 2 confirmation (0/1) |
| created_at | TIMESTAMP | Trade session start time |
| status | TEXT | Trade status (Default: 'active') |

### trade_items
Cards and puzzle pieces included in active trades.

| Column | Type | Description |
|--------|------|-------------|
| item_id | INTEGER | Auto-increment primary key |
| trade_id | INTEGER | Trade session ID (Foreign Key → trades) |
| user_id | INTEGER | Owner's Discord ID |
| item_type | TEXT | Type: 'card' or 'puzzle_piece' |
| item_id_str | TEXT | Card ID or puzzle piece ID |
| quantity | INTEGER | Quantity offered (Default: 1) |

### spawn_channel
Server-specific spawn channel configuration.

| Column | Type | Description |
|--------|------|-------------|
| guild_id | INTEGER | Discord server ID (Primary Key) |
| channel_id | INTEGER | Spawn channel ID |

### last_claim
Cooldown tracking for `/gpkclaim` command.

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Discord user ID (Primary Key) |
| last_claim | TIMESTAMP | Last claim timestamp |

### last_daily
Cooldown tracking for `/gpkdaily` command.

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Discord user ID (Primary Key) |
| last_daily | TIMESTAMP | Last daily claim timestamp |

## Rarity System

Cards are categorized into rarity tiers that affect B variant drop rates and puzzle piece chances:

| Tier | Series | B Variant % | Puzzle Piece % |
|------|--------|-------------|----------------|
| Epic | wb | 15% | 25% |
| Legendary | fb1, fb2, fb3 | 10% | 20% |
| Ultra Rare | os3, os4, os6, os7 | 8% | 15% |
| Rare | os8-os15, tv_* | 6% | 12% |
| Uncommon | os1, os2, os5 | 5% | 10% |
| Common | (base) | 3% | 8% |

## Level System

Players level up based on XP earned from activities:

| Level | XP Required |
|-------|-------------|
| 1 | 0 |
| 2 | 100 |
| 3 | 250 |
| 4 | 450 |
| 5+ | Previous + (level * 150) |

**XP Sources**:
- Daily claim: 50 XP
- Catch card: 10 XP
- New unique card: 20 XP bonus
- Open pack: 25 XP
- Craft B variant: 100 XP
- Complete trade: 50 XP

## Backup and Maintenance

### Creating Backups
```bash
# Manual backup
cp gpkdex.db gpkdex_backup_$(date +%Y%m%d).db

# With WAL files
cp gpkdex.db* gpkdex_backup_$(date +%Y%m%d)/
```

### Vacuum Database
Periodically optimize the database:
```bash
sqlite3 gpkdex.db "VACUUM;"
```

### Check Integrity
```bash
sqlite3 gpkdex.db "PRAGMA integrity_check;"
```

## Performance Considerations

- WAL mode allows multiple readers with one writer
- Indexes on user_id and card_id speed up inventory queries
- 30-second timeout prevents deadlocks under high concurrency
- Busy timeout allows waiting for locks instead of immediate failure

## Migration Notes

When adding new series or features:
1. Cards are automatically added via `init_db()` on bot startup
2. Existing user data is preserved
3. New tables should use `CREATE TABLE IF NOT EXISTS`
4. Add appropriate indexes for query performance
