import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import asyncio
import random
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('gpkdex')

import database as db
from cards import (
    load_cards_to_db, get_random_card, get_random_cards, get_random_card_by_variant,
    get_card_display_name, get_card_rarity_name, get_rarity_color,
    get_craft_cost, get_card_image_path, find_card_by_name
)
from puzzles import (
    load_puzzles_to_db, get_puzzle_rarity_name, get_puzzle_rarity_color,
    get_puzzle_image_path, get_piece_image_path, get_puzzle_preview_path,
    get_piece_label, PUZZLE_PIECE_XP, PUZZLE_COMPLETE_XP
)

load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', 0))  # Your Discord user ID
IMAGES_PATH = os.getenv('IMAGES_PATH', '/var/www/html/escapethetube/gpkdex/')

DAILY_BASE_COINS = int(os.getenv('DAILY_BASE_COINS', 1500))
DAILY_LEVEL_BONUS = int(os.getenv('DAILY_LEVEL_BONUS', 150))
PACK_COST = int(os.getenv('PACK_COST', 5000))
CARDS_PER_PACK = int(os.getenv('CARDS_PER_PACK', 4))
SPAWN_CATCH_BASE = int(os.getenv('SPAWN_CATCH_BASE_COINS', 50))
SPAWN_CATCH_LEVEL_BONUS = int(os.getenv('SPAWN_CATCH_LEVEL_BONUS', 10))

# Rarity-based catch coin multipliers (base × multiplier)
# Epic > Legendary > Ultra Rare > Rare > Uncommon > Common
# B variants get 2x multiplier on top
CATCH_RARITY_MULTIPLIERS = {
    'epic': 20,       # White Border Error
    'legendary': 10,  # Flashback series
    'ultra_rare': 5,  # OS 1-3
    'rare': 3,        # OS 4-6, TV series
    'uncommon': 2,    # OS 7-10
    'common': 1,      # OS 11-15
}
CATCH_B_VARIANT_MULTIPLIER = 2  # B variants worth 2x more

# Mass spawn settings (rare bonus event)
MASS_SPAWN_CHANCE = 0.05  # 5% chance for mass spawn instead of single
# Weighted chances for number of cards: 3 (common), 4 (rare), 5 (super rare)
MASS_SPAWN_WEIGHTS = {3: 70, 4: 25, 5: 5}  # 70% for 3, 25% for 4, 5% for 5

DAILY_XP = int(os.getenv('DAILY_XP', 50))
PACK_XP = int(os.getenv('PACK_XP', 25))
CATCH_XP = int(os.getenv('CATCH_XP', 10))
NEW_CARD_XP = int(os.getenv('NEW_CARD_XP', 20))
NEW_CARD_COINS = int(os.getenv('NEW_CARD_COINS', 200))
CRAFT_B_XP = int(os.getenv('CRAFT_B_XP', 100))

# Puzzle settings
PUZZLE_PIECE_CHANCE = 0.50  # 50% chance to get a puzzle piece in a pack
PUZZLE_SPAWN_CHANCE = 0.05  # 5% chance for a puzzle piece to spawn instead of a card
PUZZLE_CLAIM_CHANCE = 0.03  # 3% base chance for puzzle piece from /gpkclaim
PUZZLE_LEVELED_CLAIM_BASE = 0.05  # 5% base chance for puzzle piece from /gpkleveledclaim
PUZZLE_LEVELED_CLAIM_PER_LEVEL = 0.02  # +2% per level for puzzle piece from /gpkleveledclaim

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Track last activity time per guild (for activity-based spawning)
guild_last_activity = {}
SPAWN_COOLDOWN_MINUTES = 15  # Spawn every 15 minutes if there's activity


def get_card_catch_coins(card: dict, user_level: int) -> int:
    """Calculate catch coins based on card rarity and user level."""
    from cards import is_white_border_series, is_flashback_series, is_tv_series

    series = card['series']
    variant = card['variant']

    # Determine rarity tier
    if is_white_border_series(series):
        rarity = 'epic'
    elif is_flashback_series(series):
        rarity = 'legendary'
    elif is_tv_series(series):
        rarity = 'rare'
    elif series.startswith('os'):
        series_num = int(series.replace('os', ''))
        if series_num <= 3:
            rarity = 'ultra_rare'
        elif series_num <= 6:
            rarity = 'rare'
        elif series_num <= 10:
            rarity = 'uncommon'
        else:
            rarity = 'common'
    else:
        rarity = 'common'

    # Calculate base coins with rarity multiplier
    multiplier = CATCH_RARITY_MULTIPLIERS.get(rarity, 1)
    base_coins = SPAWN_CATCH_BASE + (user_level * SPAWN_CATCH_LEVEL_BONUS)
    coins = base_coins * multiplier

    # B variants worth more
    if variant == 'b':
        coins *= CATCH_B_VARIANT_MULTIPLIER

    return coins

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f"IMAGES_PATH: {IMAGES_PATH}")
    await db.init_db()
    cards_count = await load_cards_to_db(IMAGES_PATH)
    logger.info(f"Loaded {cards_count} cards")

    # Load puzzles
    puzzles_count, pieces_count = await load_puzzles_to_db(IMAGES_PATH)
    logger.info(f"Loaded {puzzles_count} puzzles with {pieces_count} pieces")

    # Verify cards in database
    all_cards = await db.get_all_cards()
    logger.info(f"Total cards in database: {len(all_cards)}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Start activity-based spawn loop only (no timer-based spawns)
    activity_spawn_loop.start()


# ============== GLOBAL ERROR HANDLER ==============
GPK_ERROR_MESSAGES = [
    "Command Error: Oops! Adam Bomb just exploded the command. Try again!",
    "Command Error: Leaky Lindsay spilled something on our servers. Give it another shot!",
    "Command Error: Messy Tessie made a mess of that one. Please try again!",
    "Command Error: Barfin' Barbara didn't like that. Try again later!",
    "Command Error: Potty Scotty flushed something important. Oops!",
    "Command Error: Busted Bob broke something. We're duct-taping it back together!",
    "Command Error: Dead Ted couldn't handle that request. He'll respawn soon!",
    "Command Error: Nasty Nick did something nasty to your command. Try again!",
]

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handle all slash command errors gracefully."""
    logger.error(f"Command error in {interaction.command.name if interaction.command else 'unknown'}: {error}")

    # Determine the error message
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        cooldown_msgs = [
            f"Whoa there Speedy Spencer! This command is on cooldown. Try again in **{error.retry_after:.1f}** seconds!",
            f"Slow down there Rapid Randy! This command is on cooldown. Try again in **{error.retry_after:.1f}** seconds!",
        ]
        message = random.choice(cooldown_msgs)
    elif isinstance(error, discord.app_commands.MissingPermissions):
        message = "Sorry! You don't have permission to use this command."
    else:
        message = random.choice(GPK_ERROR_MESSAGES)

    # Try to respond (handle both deferred and non-deferred states)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except:
        pass  # Can't respond at all (interaction expired)


# ============== DAILY COMMAND ==============
@bot.tree.command(name="gpkdaily", description="Claim your daily GPK coins and XP!")
async def gpkdaily(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)

    # Check cooldown (24 hours)
    if user['last_daily']:
        last_daily = datetime.fromisoformat(user['last_daily'])
        next_daily = last_daily + timedelta(hours=24)
        if datetime.utcnow() < next_daily:
            remaining = next_daily - datetime.utcnow()
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            await interaction.response.send_message(
                f"You've already claimed your daily! Come back in **{hours}h {minutes}m**",
                ephemeral=True
            )
            return

    # Calculate rewards
    coin_reward = DAILY_BASE_COINS + (user['level'] * DAILY_LEVEL_BONUS)

    # Update user
    await db.add_coins(interaction.user.id, coin_reward)
    leveled_up, new_level = await db.add_xp(interaction.user.id, DAILY_XP)
    await db.update_user(interaction.user.id, last_daily=datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="Daily Reward Claimed!",
        color=0x2ECC71
    )
    embed.add_field(name="Coins", value=f"+{coin_reward:,}", inline=True)
    embed.add_field(name="XP", value=f"+{DAILY_XP}", inline=True)

    if leveled_up:
        embed.add_field(name="LEVEL UP!", value=f"You are now level {new_level}!", inline=False)

    embed.set_footer(text=f"Level {new_level} bonus: +{user['level'] * DAILY_LEVEL_BONUS} coins")
    await interaction.response.send_message(embed=embed)

# ============== OPEN PACK COMMAND ==============
class PackConfirmView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.confirmed = False

    @discord.ui.button(label="Yes, Open Pack", style=discord.ButtonStyle.green, emoji="📦")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your pack confirmation!", ephemeral=True)
            return
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your pack confirmation!", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Pack opening cancelled.", embed=None, view=None)

    async def on_timeout(self):
        self.stop()


class GiveConfirmView(discord.ui.View):
    def __init__(self, user_id: int, gift_type: str, amount_or_card: str, recipient_name: str):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.gift_type = gift_type  # 'card' or 'coins'
        self.amount_or_card = amount_or_card
        self.recipient_name = recipient_name
        self.confirmed = False

    @discord.ui.button(label="Yes, Send Gift", style=discord.ButtonStyle.green, emoji="🎁")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your gift confirmation!", ephemeral=True)
            return
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your gift confirmation!", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(content="Gift cancelled.", embed=None, view=None)

    async def on_timeout(self):
        self.stop()


@bot.tree.command(name="gpkopen", description="Open a GPK card pack!")
async def gpkopen(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)

    if user['coins'] < PACK_COST:
        await interaction.response.send_message(
            f"You need **{PACK_COST:,}** coins to open a pack! You have **{user['coins']:,}** coins.",
            ephemeral=True
        )
        return

    # Show confirmation
    embed = discord.Embed(
        title="Open a Pack?",
        description=f"This will deduct **{PACK_COST:,} coins** from your balance.\n\n"
                    f"Your balance: **{user['coins']:,}** coins\n"
                    f"After opening: **{user['coins'] - PACK_COST:,}** coins",
        color=0xF39C12
    )
    view = PackConfirmView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # Wait for response
    await view.wait()

    if not view.confirmed:
        return

    # Re-check coins (in case they spent them while confirming)
    user = await db.get_user(interaction.user.id)
    if user['coins'] < PACK_COST:
        await interaction.edit_original_response(
            content=f"You no longer have enough coins! You have **{user['coins']:,}** coins.",
            embed=None, view=None
        )
        return

    await interaction.edit_original_response(content="Opening pack...", embed=None, view=None)

    # Deduct coins
    await db.add_coins(interaction.user.id, -PACK_COST)
    await db.update_user(interaction.user.id, total_packs_opened=user['total_packs_opened'] + 1)

    # Check for puzzle piece (50% chance to replace one card with a puzzle piece)
    got_puzzle_piece = random.random() < PUZZLE_PIECE_CHANCE
    puzzle_piece_info = None

    if got_puzzle_piece:
        puzzle, piece = await db.get_random_puzzle_piece()
        if puzzle and piece:
            puzzle_piece_info = (puzzle, piece)
            # Get one less card since we're adding a puzzle piece
            cards = await get_random_cards(CARDS_PER_PACK - 1)
        else:
            # No puzzles in database, get normal cards
            cards = await get_random_cards(CARDS_PER_PACK)
            got_puzzle_piece = False
    else:
        cards = await get_random_cards(CARDS_PER_PACK)

    total_xp = PACK_XP
    new_cards = []

    embed = discord.Embed(
        title=f"{interaction.user.display_name} Opened a Pack!",
        description=f"You got {len(cards)} card{'s' if len(cards) != 1 else ''}" + (" and a puzzle piece!" if got_puzzle_piece else "!"),
        color=0x3498DB
    )

    card_texts = []
    for card in cards:
        is_new = await db.add_card_to_inventory(interaction.user.id, card['card_id'])
        if is_new:
            total_xp += NEW_CARD_XP
            new_cards.append(card)

        name = get_card_display_name(card)
        rarity = get_card_rarity_name(card)
        new_tag = " **NEW!**" if is_new else ""

        # Special formatting for B cards
        if card['variant'] == 'b':
            card_texts.append(f"**{name}** - {rarity}{new_tag}")
        else:
            card_texts.append(f"{name} - {rarity}{new_tag}")

    embed.add_field(name="Cards", value='\n'.join(card_texts), inline=False)

    # Handle puzzle piece
    if got_puzzle_piece and puzzle_piece_info:
        puzzle, piece = puzzle_piece_info
        is_new_piece = await db.add_puzzle_piece_to_inventory(interaction.user.id, piece['piece_id'])
        total_xp += PUZZLE_PIECE_XP

        puzzle_rarity = get_puzzle_rarity_name(puzzle)
        new_tag = " **NEW!**" if is_new_piece else ""
        embed.add_field(
            name="Puzzle Piece!",
            value=f"**{puzzle['name']}** - Piece {get_piece_label(puzzle['puzzle_id'], piece['piece_number'])}\n{puzzle_rarity}{new_tag}",
            inline=False
        )

        # Check if puzzle is now complete
        if await db.check_puzzle_completion(interaction.user.id, puzzle['puzzle_id']):
            embed.add_field(
                name="PUZZLE READY!",
                value=f"You have all 18 pieces of **{puzzle['name']}**!\nUse `/gpkpuzzles` to complete it!",
                inline=False
            )

    # Award XP
    leveled_up, new_level = await db.add_xp(interaction.user.id, total_xp)

    embed.add_field(name="XP Earned", value=f"+{total_xp}", inline=True)

    if leveled_up:
        embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=True)

    updated_user = await db.get_user(interaction.user.id)
    embed.set_footer(text=f"Coins remaining: {updated_user['coins']:,}")

    await interaction.followup.send(embed=embed)

# ============== COLLECTION PAGINATION VIEW ==============
class CollectionView(discord.ui.View):
    def __init__(self, pages: list, target_user: discord.User, stats: dict):
        super().__init__(timeout=120)  # 2 minute timeout
        self.pages = pages
        self.current_page = 0
        self.target_user = target_user
        self.stats = stats
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= len(self.pages) - 1

    def get_embed(self):
        embed = discord.Embed(
            title=f"{self.target_user.display_name}'s Collection",
            color=0x9B59B6
        )

        embed.add_field(
            name="Overall Completion",
            value=f"**{self.stats['owned_unique']}** / **{self.stats['total_cards']}** ({self.stats['completion_percent']:.1f}%)",
            inline=False
        )

        # Add current page content
        embed.add_field(name="Cards", value=self.pages[self.current_page], inline=False)

        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Collection view closed.", embed=None, view=None)

# ============== COLLECTION COMMAND ==============
@bot.tree.command(name="gpkcollection", description="View GPK card collection")
@app_commands.describe(
    user="The user whose collection to view (optional)",
    series="Filter by series: os1-os15 (optional)"
)
async def gpkcollection(interaction: discord.Interaction, user: discord.User = None, series: str = None):
    await interaction.response.defer()

    # Default to the command user if no user specified
    target_user = user or interaction.user

    stats = await db.get_collection_stats(target_user.id)
    inventory = await db.get_inventory(target_user.id)

    # Filter by series if specified
    if series:
        series = series.lower()
        valid_series = [f'os{i}' for i in range(1, 16)] + ['fb1', 'fb2', 'fb3', 'wb', 'tv', 'tv_cartoon']
        if series not in valid_series:
            await interaction.followup.send("Invalid series! Use os1-os15, fb1-fb3, wb, or tv.", ephemeral=True)
            return
        # Normalize tv to tv_cartoon
        if series == 'tv':
            series = 'tv_cartoon'
        inventory = [item for item in inventory if item['series'] == series]

    if not inventory:
        embed = discord.Embed(
            title=f"{target_user.display_name}'s Collection",
            color=0x9B59B6
        )
        embed.add_field(
            name="Overall Completion",
            value=f"**{stats['owned_unique']}** / **{stats['total_cards']}** ({stats['completion_percent']:.1f}%)",
            inline=False
        )
        embed.add_field(name="Cards", value="No cards yet! Use `/gpkdaily` and `/gpkopen` to get started.", inline=False)
        await interaction.followup.send(embed=embed)
        return

    # Define series order by rarity (highest to lowest)
    def get_series_order(s):
        if s == 'wb':
            return (0, 0)  # Epic
        elif s.startswith('fb'):
            return (1, int(s[2]))  # Legendary (fb1, fb2, fb3)
        elif s.startswith('tv_'):
            return (3, 0)  # Rare - all TV series grouped together
        elif s.startswith('os'):
            num = int(s[2:])
            if num <= 3:
                return (2, num)  # Ultra Rare
            elif num <= 6:
                return (3, num)  # Rare
            elif num <= 10:
                return (4, num)  # Uncommon
            else:
                return (5, num)  # Common
        return (6, 0)

    def get_rarity_tag(s):
        if s == 'wb':
            return "⭐E"  # Epic
        elif s.startswith('fb'):
            return "⭐L"  # Legendary
        elif s.startswith('tv_'):
            return "⭐R"  # Rare - all TV series
        elif s.startswith('os'):
            num = int(s[2:])
            if num <= 3:
                return "⭐UR"  # Ultra Rare
            elif num <= 6:
                return "⭐R"  # Rare
            elif num <= 10:
                return "⭐UC"  # Uncommon
            else:
                return "C"  # Common (no star)
        return ""

    def get_series_display_name(s):
        if s == 'wb':
            return "White Border Errors"
        elif s.startswith('fb'):
            return f"Flashback {s[2]}"
        elif s.startswith('tv_'):
            return "Prime Slime TV"
        elif s.startswith('os'):
            return f"Series {s[2:]}"
        return s.upper()

    # Group all TV series under one key for display
    def get_series_group(s):
        if s.startswith('tv_'):
            return 'tv_all'
        return s

    # Get series completion data
    series_completion = await db.get_series_completion(target_user.id)

    # Aggregate TV series completion into one
    tv_total = 0
    tv_owned = 0
    for s, sc in series_completion.items():
        if s.startswith('tv_'):
            tv_total += sc['total']
            tv_owned += sc['owned']
    series_completion['tv_all'] = {'total': tv_total, 'owned': tv_owned}

    # Group cards by display group (combining all TV series)
    series_groups = {}
    for item in inventory:
        group = get_series_group(item['series'])
        if group not in series_groups:
            series_groups[group] = []
        series_groups[group].append(item)

    # Sort series by rarity order, then sort cards within each series
    sorted_series = sorted(series_groups.keys(), key=get_series_order)

    # Build page content with series headers
    page_lines = []
    for s in sorted_series:
        cards = sorted(series_groups[s], key=lambda x: (x['series'], x['number'], x['variant']))
        rarity_tag = get_rarity_tag(s)
        series_name = get_series_display_name(s)

        # Get completion for this series (use tv_all for combined TV)
        sc = series_completion.get(s, {'total': 0, 'owned': 0})
        header = f"**━━ {series_name} [{rarity_tag}] ({sc['owned']}/{sc['total']}) ━━**"
        page_lines.append(header)

        for item in cards:
            name = get_card_display_name(item)
            qty = f" x{item['quantity']}" if item['quantity'] > 1 else ""
            # Bold B variants
            if item['variant'] == 'b':
                page_lines.append(f"  **{name}**{qty}")
            else:
                page_lines.append(f"  {name}{qty}")

        page_lines.append("")  # Blank line between series

    # Split into pages (max ~12 lines per page to fit with headers)
    LINES_PER_PAGE = 12
    pages = []
    current_page = []
    current_lines = 0

    for line in page_lines:
        # If it's a header, try to keep at least a few cards with it
        if line.startswith("**━━"):
            # If current page is getting full, start new page for this series
            if current_lines > LINES_PER_PAGE - 3:
                if current_page:
                    pages.append('\n'.join(current_page))
                current_page = [line]
                current_lines = 1
            else:
                current_page.append(line)
                current_lines += 1
        elif line == "":
            # Skip trailing blank lines at page end
            if current_page and not current_page[-1] == "":
                current_page.append(line)
        else:
            current_page.append(line)
            current_lines += 1

            if current_lines >= LINES_PER_PAGE:
                pages.append('\n'.join(current_page))
                current_page = []
                current_lines = 0

    # Add remaining content
    if current_page:
        # Remove trailing blank line
        while current_page and current_page[-1] == "":
            current_page.pop()
        if current_page:
            pages.append('\n'.join(current_page))

    # If only one page, no need for pagination
    if len(pages) == 1:
        embed = discord.Embed(
            title=f"{target_user.display_name}'s Collection" + (f" ({series.upper()})" if series else ""),
            color=0x9B59B6
        )
        embed.add_field(
            name="Overall Completion",
            value=f"**{stats['owned_unique']}** / **{stats['total_cards']}** ({stats['completion_percent']:.1f}%)",
            inline=False
        )
        embed.add_field(name="Cards", value=pages[0], inline=False)
        await interaction.followup.send(embed=embed)
    else:
        # Use pagination view
        view = CollectionView(pages, target_user, stats)
        await interaction.followup.send(embed=view.get_embed(), view=view)

# ============== PROFILE COMMAND ==============
@bot.tree.command(name="gpkprofile", description="View GPK profile and stats")
@app_commands.describe(user="The user whose profile to view (optional)")
async def gpkprofile(interaction: discord.Interaction, user: discord.User = None):
    await interaction.response.defer()

    # Default to the command user if no user specified
    target_user = user or interaction.user

    db_user = await db.get_user(target_user.id)
    stats = await db.get_collection_stats(target_user.id)

    # Calculate XP to next level
    current_level_xp = db.xp_for_level(db_user['level'])
    next_level_xp = db.xp_for_level(db_user['level'] + 1)
    xp_progress = db_user['xp'] - current_level_xp
    xp_needed = next_level_xp - current_level_xp

    embed = discord.Embed(
        title=f"{target_user.display_name}'s Profile",
        color=0xE74C3C
    )

    embed.set_thumbnail(url=target_user.display_avatar.url)

    embed.add_field(name="Level", value=str(db_user['level']), inline=True)
    embed.add_field(name="XP", value=f"{xp_progress}/{xp_needed}", inline=True)
    embed.add_field(name="Coins", value=f"{db_user['coins']:,}", inline=True)

    embed.add_field(name="Collection", value=f"{stats['owned_unique']}/{stats['total_cards']} ({stats['completion_percent']:.1f}%)", inline=True)
    embed.add_field(name="Cards Collected", value=str(db_user['total_cards_collected']), inline=True)
    embed.add_field(name="Packs Opened", value=str(db_user['total_packs_opened']), inline=True)

    # Daily bonus info
    daily_coins = DAILY_BASE_COINS + (db_user['level'] * DAILY_LEVEL_BONUS)
    base_coins = SPAWN_CATCH_BASE + (db_user['level'] * SPAWN_CATCH_LEVEL_BONUS)
    embed.add_field(name="Daily Bonus", value=f"{daily_coins:,} coins", inline=True)
    embed.add_field(name="Card Bonus", value=f"{base_coins}+ coins\n(varies by rarity)", inline=True)

    await interaction.followup.send(embed=embed)

# ============== CRAFT COMMAND ==============
async def craftable_card_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for A cards the user can craft into B cards."""
    inventory = await db.get_inventory(interaction.user.id)
    choices = []
    current_lower = current.lower().replace(' ', '').replace('-', '')

    for item in inventory:
        # Only show A variants
        if item['variant'] != 'a':
            continue

        craft_cost = get_craft_cost(item['series'])

        # Format: OS2-85A (quantity)
        card_id = f"{item['series'].upper()}-{item['number']}A"
        card_name = get_card_display_name(item)
        search_str = card_id.lower().replace('-', '')

        # Match if current text is in the card ID or name
        if current_lower in search_str or current_lower in card_name.lower():
            can_craft = item['quantity'] >= craft_cost
            status = "Ready!" if can_craft else f"Need {craft_cost}"
            display = f"{card_id} - {card_name.split('(')[0].strip()} ({item['quantity']}/{craft_cost} - {status})"
            # Truncate if too long (Discord limit is 100 chars)
            if len(display) > 100:
                display = display[:97] + "..."
            choices.append(app_commands.Choice(name=display, value=card_id))

        if len(choices) >= 25:  # Discord limit
            break

    return choices


@bot.tree.command(name="gpkcraft", description="Trade GPK A cards for a B card")
@app_commands.describe(
    card="The A card to craft (e.g., OS2-85A)"
)
async def gpkcraft(interaction: discord.Interaction, card: str):
    # Parse the card identifier
    series, number, variant = parse_card_identifier(card)

    # Also try finding by name if parsing failed
    if not series:
        found_series, found_number, found_variant = find_card_by_name(card)
        if found_series:
            series = found_series
            number = found_number
        else:
            await interaction.response.send_message(
                f"Invalid card format! Use format like `OS2-85A` or a card name.",
                ephemeral=True
            )
            return

    # Get the A card
    a_card = await db.get_card_by_name(series, number, 'a')
    if not a_card:
        await interaction.response.send_message(
            f"Card {series.upper()}-{number}A doesn't exist!",
            ephemeral=True
        )
        return

    # Get the B card
    b_card = await db.get_card_by_name(series, number, 'b')
    if not b_card:
        await interaction.response.send_message(
            f"Card {series.upper()}-{number}B doesn't exist!",
            ephemeral=True
        )
        return

    craft_cost = get_craft_cost(series)

    # Check inventory
    inventory = await db.get_inventory(interaction.user.id)
    user_a_card = next((i for i in inventory if i['card_id'] == a_card['card_id']), None)

    if not user_a_card or user_a_card['quantity'] < craft_cost:
        current = user_a_card['quantity'] if user_a_card else 0
        await interaction.response.send_message(
            f"You need **{craft_cost}** copies of {get_card_display_name(a_card)} to craft the B version.\n"
            f"You currently have **{current}**.",
            ephemeral=True
        )
        return

    # Perform the craft
    success = await db.remove_cards_from_inventory(interaction.user.id, a_card['card_id'], craft_cost)
    if not success:
        await interaction.response.send_message("Something went wrong!", ephemeral=True)
        return

    is_new = await db.add_card_to_inventory(interaction.user.id, b_card['card_id'])
    leveled_up, new_level = await db.add_xp(interaction.user.id, CRAFT_B_XP)

    embed = discord.Embed(
        title="Card Crafted!",
        description=f"You traded {craft_cost}x {get_card_display_name(a_card)} for:",
        color=get_rarity_color(b_card)
    )

    embed.add_field(name="Received", value=f"**{get_card_display_name(b_card)}** - {get_card_rarity_name(b_card)}", inline=False)
    embed.add_field(name="XP", value=f"+{CRAFT_B_XP}", inline=True)

    if is_new:
        embed.add_field(name="", value="**NEW CARD!**", inline=True)

    if leveled_up:
        embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

    # Show image
    image_path = await get_card_image_path(b_card, IMAGES_PATH)
    if os.path.exists(image_path):
        file = discord.File(image_path, filename=b_card['filename'])
        embed.set_image(url=f"attachment://{b_card['filename']}")
        await interaction.response.send_message(embed=embed, file=file)
    else:
        await interaction.response.send_message(embed=embed)


@gpkcraft.autocomplete('card')
async def gpkcraft_autocomplete(interaction: discord.Interaction, current: str):
    return await craftable_card_autocomplete(interaction, current)


# ============== SHOW COMMAND ==============
@bot.tree.command(name="gpkshow", description="Display a GPK card from your collection")
@app_commands.describe(
    card="The card (e.g., OS2-85A or OS12-465B)"
)
async def gpkshow(interaction: discord.Interaction, card: str):
    # Parse the card identifier
    series, number, variant = parse_card_identifier(card)
    if not series:
        await interaction.response.send_message(
            f"Invalid card format! Use format like `OS2-85A` or `OS12-465B`",
            ephemeral=True
        )
        return

    card_data = await db.get_card_by_name(series, number, variant)
    if not card_data:
        await interaction.response.send_message(
            f"Card {series.upper()}-{number}{variant.upper()} doesn't exist!",
            ephemeral=True
        )
        return

    # Check if user owns it
    inventory = await db.get_inventory(interaction.user.id)
    owned = next((i for i in inventory if i['card_id'] == card_data['card_id']), None)

    if not owned:
        await interaction.response.send_message(
            f"You don't own {get_card_display_name(card_data)}!",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=get_card_display_name(card_data),
        description=f"**{get_card_rarity_name(card_data)}**",
        color=get_rarity_color(card_data)
    )

    embed.add_field(name="Owned", value=f"{owned['quantity']}x", inline=True)
    embed.set_footer(text=f"Showing {interaction.user.display_name}'s card")

    image_path = await get_card_image_path(card_data, IMAGES_PATH)
    if os.path.exists(image_path):
        file = discord.File(image_path, filename=card_data['filename'])
        embed.set_image(url=f"attachment://{card_data['filename']}")
        await interaction.response.send_message(embed=embed, file=file)
    else:
        await interaction.response.send_message(embed=embed)

@gpkshow.autocomplete('card')
async def gpkshow_card_autocomplete(interaction: discord.Interaction, current: str):
    return await owned_card_autocomplete(interaction, current)

# ============== SYNC COMMAND ==============
@bot.tree.command(name="gpksync", description="Sync bot commands with Discord (Admin only)")
@app_commands.default_permissions(administrator=True)
async def gpksync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        await interaction.followup.send(f"Synced {len(synced)} command(s) successfully!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Failed to sync: {e}", ephemeral=True)


# ============== SET SPAWN CHANNEL COMMAND ==============
@bot.tree.command(name="gpksetspawn", description="Set the channel for GPK card spawns (Admin only)")
@app_commands.describe(channel="The channel for card spawns")
@app_commands.default_permissions(administrator=True)
async def gpksetspawn(interaction: discord.Interaction, channel: discord.TextChannel):
    await db.set_spawn_channel(interaction.guild_id, channel.id)

    embed = discord.Embed(
        title="Spawn Channel Set!",
        description=f"Cards will now spawn in {channel.mention}",
        color=0x2ECC71
    )

    await interaction.response.send_message(embed=embed)

# ============== CLAIM COMMAND (hourly random card) ==============
@bot.tree.command(name="gpkclaim", description="Claim a free random card (once per hour)")
async def gpkclaim(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)

    # Check cooldown (1 hour)
    if user.get('last_claim'):
        last_claim = datetime.fromisoformat(user['last_claim'])
        next_claim = last_claim + timedelta(hours=1)
        if datetime.utcnow() < next_claim:
            remaining = next_claim - datetime.utcnow()
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            await interaction.response.send_message(
                f"You already claimed this hour! Come back in **{minutes}m {seconds}s**",
                ephemeral=True
            )
            return

    await interaction.response.defer()

    # Update last claim time
    await db.update_user(interaction.user.id, last_claim=datetime.utcnow().isoformat())

    # Small chance for puzzle piece instead of card
    if random.random() < PUZZLE_CLAIM_CHANCE:
        puzzle, piece = await db.get_random_puzzle_piece()
        if puzzle and piece:
            # Add puzzle piece to inventory
            is_new = await db.add_puzzle_piece_to_inventory(interaction.user.id, piece['piece_id'])
            xp_reward = PUZZLE_PIECE_XP
            leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

            embed = discord.Embed(
                title="Hourly Claim - Puzzle Piece!",
                description=f"{interaction.user.mention} found a puzzle piece!",
                color=get_puzzle_rarity_color(puzzle)
            )

            embed.add_field(
                name="Puzzle Piece",
                value=f"**{puzzle['name']}** - Piece {get_piece_label(puzzle['puzzle_id'], piece['piece_number'])}\n{get_puzzle_rarity_name(puzzle)}",
                inline=True
            )
            embed.add_field(name="XP", value=f"+{xp_reward}", inline=True)

            if is_new:
                embed.add_field(name="", value="**NEW PIECE!**", inline=False)

            if leveled_up:
                embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

            image_path = await get_piece_image_path(piece, puzzle, IMAGES_PATH)
            if os.path.exists(image_path):
                file = discord.File(image_path, filename=piece['filename'])
                embed.set_image(url=f"attachment://{piece['filename']}")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send(embed=embed)
            return

    # Get a random card
    card = await get_random_card()
    if not card:
        await interaction.followup.send("No cards available!", ephemeral=True)
        return

    # Add to inventory
    is_new = await db.add_card_to_inventory(interaction.user.id, card['card_id'])

    # Calculate rewards based on card rarity
    user = await db.get_user(interaction.user.id)
    coin_reward = get_card_catch_coins(card, user['level']) + (NEW_CARD_COINS if is_new else 0)
    xp_reward = CATCH_XP + (NEW_CARD_XP if is_new else 0)

    await db.add_coins(interaction.user.id, coin_reward)
    leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

    embed = discord.Embed(
        title="Hourly Card Claimed!",
        description=f"{interaction.user.mention} claimed a card!",
        color=get_rarity_color(card)
    )

    embed.add_field(name="Card", value=f"**{get_card_display_name(card)}**\n{get_card_rarity_name(card)}", inline=True)
    embed.add_field(name="Rewards", value=f"+{coin_reward} coins\n+{xp_reward} XP", inline=True)

    if is_new:
        embed.add_field(name="", value="**NEW CARD!**", inline=False)

    if leveled_up:
        embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

    image_path = await get_card_image_path(card, IMAGES_PATH)
    if os.path.exists(image_path):
        file = discord.File(image_path, filename=card['filename'])
        embed.set_image(url=f"attachment://{card['filename']}")
        await interaction.followup.send(embed=embed, file=file)
    else:
        await interaction.followup.send(embed=embed)

# ============== LEVELED CLAIM COMMAND (12-hour with level bonus) ==============
@bot.tree.command(name="gpkleveledclaim", description="Claim a card with level-boosted B and puzzle piece chance (every 12 hours)")
async def gpkleveledclaim(interaction: discord.Interaction):
    user = await db.get_user(interaction.user.id)

    # Check cooldown (12 hours)
    if user.get('last_leveled_claim'):
        last_claim = datetime.fromisoformat(user['last_leveled_claim'])
        next_claim = last_claim + timedelta(hours=12)
        if datetime.utcnow() < next_claim:
            remaining = next_claim - datetime.utcnow()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await interaction.response.send_message(
                f"You already used your leveled claim! Come back in **{hours}h {minutes}m**",
                ephemeral=True
            )
            return

    await interaction.response.defer()

    # Update last leveled claim time
    await db.update_user(interaction.user.id, last_leveled_claim=datetime.utcnow().isoformat())

    level = user['level']

    # Calculate puzzle piece chance based on level
    # Base 5% + 2% per level, capped at 50%
    puzzle_chance = min(PUZZLE_LEVELED_CLAIM_BASE + (level * PUZZLE_LEVELED_CLAIM_PER_LEVEL), 0.50)

    # Check for puzzle piece first (level-boosted chance)
    if random.random() < puzzle_chance:
        puzzle, piece = await db.get_random_puzzle_piece()
        if puzzle and piece:
            # Add puzzle piece to inventory
            is_new = await db.add_puzzle_piece_to_inventory(interaction.user.id, piece['piece_id'])
            xp_reward = PUZZLE_PIECE_XP
            leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

            embed = discord.Embed(
                title="Leveled Claim - Puzzle Piece!",
                description=f"{interaction.user.mention} found a puzzle piece with their level bonus!",
                color=get_puzzle_rarity_color(puzzle)
            )

            embed.add_field(
                name="Puzzle Piece",
                value=f"**{puzzle['name']}** - Piece {get_piece_label(puzzle['puzzle_id'], piece['piece_number'])}\n{get_puzzle_rarity_name(puzzle)}",
                inline=True
            )
            embed.add_field(name="XP", value=f"+{xp_reward}", inline=True)
            embed.add_field(name="Puzzle Chance", value=f"{puzzle_chance*100:.0f}% (Level {level})", inline=True)

            if is_new:
                embed.add_field(name="", value="**NEW PIECE!**", inline=False)

            if leveled_up:
                embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

            image_path = await get_piece_image_path(piece, puzzle, IMAGES_PATH)
            if os.path.exists(image_path):
                file = discord.File(image_path, filename=piece['filename'])
                embed.set_image(url=f"attachment://{piece['filename']}")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send(embed=embed)
            return

    # Calculate B card chance based on level
    # Base 5% + 2% per level, capped at 50%
    b_chance = min(0.05 + (level * 0.02), 0.50)

    # Decide if we get a B card
    if random.random() < b_chance:
        # Get a random B card
        card = await get_random_card_by_variant('b')
    else:
        # Get a random A card
        card = await get_random_card_by_variant('a')

    if not card:
        # Fallback to any random card
        card = await get_random_card()

    if not card:
        await interaction.followup.send("No cards available!", ephemeral=True)
        return

    # Add to inventory
    is_new = await db.add_card_to_inventory(interaction.user.id, card['card_id'])

    # Calculate rewards based on card rarity
    coin_reward = get_card_catch_coins(card, level) + (NEW_CARD_COINS if is_new else 0)
    xp_reward = CATCH_XP + (NEW_CARD_XP if is_new else 0)

    await db.add_coins(interaction.user.id, coin_reward)
    leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

    embed = discord.Embed(
        title="Leveled Claim!",
        description=f"{interaction.user.mention} used their level-boosted claim!",
        color=get_rarity_color(card)
    )

    embed.add_field(name="Card", value=f"**{get_card_display_name(card)}**\n{get_card_rarity_name(card)}", inline=True)
    embed.add_field(name="Rewards", value=f"+{coin_reward} coins\n+{xp_reward} XP", inline=True)
    embed.add_field(name="B Card Chance", value=f"{b_chance*100:.0f}% (Level {level})", inline=True)

    if is_new:
        embed.add_field(name="", value="**NEW CARD!**", inline=False)

    if leveled_up:
        embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

    image_path = await get_card_image_path(card, IMAGES_PATH)
    if os.path.exists(image_path):
        file = discord.File(image_path, filename=card['filename'])
        embed.set_image(url=f"attachment://{card['filename']}")
        await interaction.followup.send(embed=embed, file=file)
    else:
        await interaction.followup.send(embed=embed)

# ============== CATCH COMMAND ==============
@bot.tree.command(name="gpkcatch", description="Catch a spawned GPK card or puzzle piece!")
async def gpkcatch(interaction: discord.Interaction):
    spawn = await db.get_active_spawn(interaction.guild_id)

    if not spawn:
        await interaction.response.send_message(
            "There's nothing to catch right now!",
            ephemeral=True
        )
        return

    # Claim the spawn
    await db.claim_spawn(spawn['id'], interaction.user.id)

    # Check if it's a puzzle piece spawn or card spawn
    if spawn.get('piece_id'):
        # Puzzle piece spawn
        piece = await db.get_puzzle_piece_by_id(spawn['piece_id'])
        puzzle = await db.get_puzzle_by_id(piece['puzzle_id'])

        # Add to inventory
        is_new = await db.add_puzzle_piece_to_inventory(interaction.user.id, piece['piece_id'])

        # Calculate rewards
        user = await db.get_user(interaction.user.id)
        coin_reward = SPAWN_CATCH_BASE + (user['level'] * SPAWN_CATCH_LEVEL_BONUS)
        xp_reward = PUZZLE_PIECE_XP

        await db.add_coins(interaction.user.id, coin_reward)
        leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

        embed = discord.Embed(
            title="Puzzle Piece Caught!",
            description=f"{interaction.user.mention} caught a puzzle piece!",
            color=get_puzzle_rarity_color(puzzle)
        )

        embed.add_field(
            name="Puzzle Piece",
            value=f"**{puzzle['name']}** - Piece {get_piece_label(puzzle['puzzle_id'], piece['piece_number'])}\n{get_puzzle_rarity_name(puzzle)}",
            inline=True
        )
        embed.add_field(name="Rewards", value=f"+{coin_reward} coins\n+{xp_reward} XP", inline=True)

        if is_new:
            embed.add_field(name="", value="**NEW PIECE!**", inline=False)

        if leveled_up:
            embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

        await interaction.response.send_message(embed=embed)
    else:
        # Card spawn
        card = await db.get_card_by_id(spawn['card_id'])

        # Add to inventory
        is_new = await db.add_card_to_inventory(interaction.user.id, card['card_id'])

        # Calculate rewards based on card rarity
        user = await db.get_user(interaction.user.id)
        coin_reward = get_card_catch_coins(card, user['level']) + (NEW_CARD_COINS if is_new else 0)
        xp_reward = CATCH_XP + (NEW_CARD_XP if is_new else 0)

        await db.add_coins(interaction.user.id, coin_reward)
        leveled_up, new_level = await db.add_xp(interaction.user.id, xp_reward)

        embed = discord.Embed(
            title="Card Caught!",
            description=f"{interaction.user.mention} caught a card!",
            color=get_rarity_color(card)
        )

        embed.add_field(name="Card", value=f"**{get_card_display_name(card)}**\n{get_card_rarity_name(card)}", inline=True)
        embed.add_field(name="Rewards", value=f"+{coin_reward} coins\n+{xp_reward} XP", inline=True)

        if is_new:
            embed.add_field(name="", value="**NEW CARD!**", inline=False)

        if leveled_up:
            embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=False)

        await interaction.response.send_message(embed=embed)

# ============== LEADERBOARD COMMAND ==============
@bot.tree.command(name="gpkleaderboard", description="View the top GPK collectors")
async def gpkleaderboard(interaction: discord.Interaction):
    await interaction.response.defer()  # Defer because fetching users takes time

    leaders = await db.get_leaderboard(10)

    if not leaders:
        await interaction.followup.send("No collectors yet!", ephemeral=True)
        return

    embed = discord.Embed(
        title="Top Collectors",
        color=0xFFD700
    )

    leaderboard_text = []
    for i, leader in enumerate(leaders, 1):
        try:
            user = await bot.fetch_user(leader['user_id'])
            name = user.display_name
        except:
            name = f"User {leader['user_id']}"

        medal = ""
        if i == 1:
            medal = ""
        elif i == 2:
            medal = ""
        elif i == 3:
            medal = ""

        leaderboard_text.append(
            f"{medal}**{i}.** {name} - {leader['unique_cards']} cards (Lvl {leader['level']})"
        )

    embed.description = '\n'.join(leaderboard_text)
    await interaction.followup.send(embed=embed)

# ============== SPAWN SYSTEM ==============
async def do_spawn(guild_id: int):
    """Spawn a card (or mass spawn) in the guild's spawn channel."""
    logger.info(f"do_spawn called for guild {guild_id}")
    settings = await db.get_server_settings(guild_id)

    if not settings['spawn_channel_id']:
        logger.warning("No spawn channel set!")
        return

    channel = bot.get_channel(settings['spawn_channel_id'])
    if not channel:
        logger.warning(f"Could not find channel {settings['spawn_channel_id']}")
        return

    # Check for unclaimed spawn
    existing = await db.get_active_spawn(guild_id)
    if existing:
        logger.info("Existing spawn found, skipping")
        return

    # Check for mass spawn (rare bonus event)
    if random.random() < MASS_SPAWN_CHANCE:
        await do_mass_spawn(guild_id, channel)
        return

    # Check for puzzle piece spawn (rare)
    if random.random() < PUZZLE_SPAWN_CHANCE:
        puzzle, piece = await db.get_random_puzzle_piece()
        if puzzle and piece:
            await do_puzzle_spawn(guild_id, channel, puzzle, piece)
            return

    # Get random card
    card = await get_random_card()
    if not card:
        logger.warning("No card returned from get_random_card!")
        return

    logger.info(f"Spawning card: {card['filename']}")

    embed = discord.Embed(
        title="A wild card appeared!",
        description=f"Use `/gpkcatch` to grab it!",
        color=get_rarity_color(card)
    )

    embed.add_field(name="Card", value=f"**{get_card_display_name(card)}**\n{get_card_rarity_name(card)}", inline=False)

    image_path = await get_card_image_path(card, IMAGES_PATH)
    logger.info(f"Image path: {image_path}")
    logger.info(f"Image exists: {os.path.exists(image_path)}")

    try:
        if os.path.exists(image_path):
            logger.info("Sending with image...")
            file = discord.File(image_path, filename=card['filename'])
            embed.set_image(url=f"attachment://{card['filename']}")
            message = await channel.send(embed=embed, file=file)
        else:
            logger.info("Sending without image...")
            message = await channel.send(embed=embed)

        logger.info(f"Message sent! ID: {message.id}")
        await db.create_spawn(guild_id, channel.id, card['card_id'], message.id)
        logger.info("Spawn recorded in database")

    except Exception as e:
        logger.error(f"Error spawning card: {e}", exc_info=True)


async def do_puzzle_spawn(guild_id: int, channel, puzzle: dict, piece: dict):
    """Spawn a puzzle piece in the guild's spawn channel."""
    logger.info(f"Spawning puzzle piece: {puzzle['name']} piece #{piece['piece_number']}")

    embed = discord.Embed(
        title="A wild puzzle piece appeared!",
        description=f"Use `/gpkcatch` to grab it!",
        color=get_puzzle_rarity_color(puzzle)
    )

    embed.add_field(
        name="Puzzle Piece",
        value=f"**{puzzle['name']}** - Piece {get_piece_label(puzzle['puzzle_id'], piece['piece_number'])}\n{get_puzzle_rarity_name(puzzle)}",
        inline=False
    )

    image_path = await get_piece_image_path(piece, puzzle, IMAGES_PATH)
    logger.info(f"Puzzle piece image path: {image_path}")

    try:
        if os.path.exists(image_path):
            file = discord.File(image_path, filename=piece['filename'])
            embed.set_image(url=f"attachment://{piece['filename']}")
            message = await channel.send(embed=embed, file=file)
        else:
            message = await channel.send(embed=embed)

        logger.info(f"Puzzle piece message sent! ID: {message.id}")
        await db.create_puzzle_spawn(guild_id, channel.id, piece['piece_id'], message.id)
        logger.info("Puzzle spawn recorded in database")

    except Exception as e:
        logger.error(f"Error spawning puzzle piece: {e}", exc_info=True)

async def do_mass_spawn(guild_id: int, channel):
    """Spawn multiple cards at once as a bonus event."""
    # Weighted random selection: 3 cards (70%), 4 cards (25%), 5 cards (5%)
    num_cards = random.choices(
        list(MASS_SPAWN_WEIGHTS.keys()),
        weights=list(MASS_SPAWN_WEIGHTS.values())
    )[0]
    cards = await get_random_cards(num_cards)

    if not cards:
        logger.warning("No cards for mass spawn!")
        return

    logger.info(f"MASS SPAWN: {num_cards} cards for guild {guild_id}")

    # Announcement embed
    announce_embed = discord.Embed(
        title="A pack has been opened!",
        description=f"**{num_cards} cards** have appeared!\nUse `/gpkcatch` to grab them one at a time!",
        color=0xFFD700  # Gold color for special event
    )

    # List all cards in the pack
    card_list = []
    for card in cards:
        name = get_card_display_name(card)
        rarity = get_card_rarity_name(card)
        card_list.append(f"**{name}** - {rarity}")

    announce_embed.add_field(name="Cards", value='\n'.join(card_list), inline=False)

    try:
        await channel.send(embed=announce_embed)

        # Create spawns for each card (they'll be caught one at a time)
        for card in cards:
            image_path = await get_card_image_path(card, IMAGES_PATH)

            embed = discord.Embed(
                title="Catch me!",
                description=f"Use `/gpkcatch` to grab this card!",
                color=get_rarity_color(card)
            )
            embed.add_field(name="Card", value=f"**{get_card_display_name(card)}**\n{get_card_rarity_name(card)}", inline=False)

            if os.path.exists(image_path):
                file = discord.File(image_path, filename=card['filename'])
                embed.set_image(url=f"attachment://{card['filename']}")
                message = await channel.send(embed=embed, file=file)
            else:
                message = await channel.send(embed=embed)

            await db.create_spawn(guild_id, channel.id, card['card_id'], message.id)

        logger.info(f"Mass spawn complete: {num_cards} cards spawned")

    except Exception as e:
        logger.error(f"Error in mass spawn: {e}", exc_info=True)

# ============== ACTIVITY-BASED SPAWN SYSTEM ==============
@bot.event
async def on_message(message):
    """Track activity and trigger spawns when chat happens."""
    # Ignore bot messages
    if message.author.bot:
        return

    # Check for spawn on activity
    if message.guild:
        await check_activity_spawn(message.guild.id)

    await bot.process_commands(message)

async def check_activity_spawn(guild_id: int):
    """Check if we should spawn a card based on chat activity."""
    now = datetime.utcnow()

    settings = await db.get_server_settings(guild_id)

    # Skip if no spawn channel set
    if not settings['spawn_channel_id']:
        return

    # Check if there's already an unclaimed spawn
    existing = await db.get_active_spawn(guild_id)
    if existing:
        return

    # Check last spawn time to enforce 15-minute cooldown (from database)
    last_spawn = settings.get('last_spawn_at')
    if last_spawn:
        # Parse the timestamp if it's a string
        if isinstance(last_spawn, str):
            last_spawn = datetime.fromisoformat(last_spawn.replace('Z', '+00:00').replace('+00:00', ''))
        elapsed = (now - last_spawn).total_seconds()
        if elapsed < SPAWN_COOLDOWN_MINUTES * 60:
            return

    # Spawn a card!
    await do_spawn(guild_id)
    await db.update_last_spawn_time(guild_id)
    logger.info(f"Activity spawn triggered for guild {guild_id}")

@tasks.loop(minutes=1)
async def activity_spawn_loop():
    """Placeholder loop - spawns now happen on message activity."""
    pass  # Spawns are now triggered directly by on_message

@activity_spawn_loop.before_loop
async def before_activity_spawn_loop():
    await bot.wait_until_ready()

# ============== FORCE SPAWN COMMAND (Bot Owner Only) ==============
@bot.tree.command(name="gpkforcespawn", description="Force spawn a GPK card (Bot Owner only)")
@app_commands.default_permissions(administrator=True)
async def gpkforcespawn(interaction: discord.Interaction):
    # Bot owner check
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("This command is only available to the bot owner.", ephemeral=True)
        return

    settings = await db.get_server_settings(interaction.guild_id)

    if not settings['spawn_channel_id']:
        await interaction.response.send_message(
            "No spawn channel set! Use `/gpksetspawn` first.",
            ephemeral=True
        )
        return

    # Check for existing spawn
    existing = await db.get_active_spawn(interaction.guild_id)
    if existing:
        await interaction.response.send_message(
            "There's already an unclaimed card! Catch it first.",
            ephemeral=True
        )
        return

    await interaction.response.send_message("Spawning a card...", ephemeral=True)
    await do_spawn(interaction.guild_id)
    await db.update_last_spawn_time(interaction.guild_id)

# ============== FORCE SPAWN PUZZLE COMMAND (Bot Owner Only) ==============
@bot.tree.command(name="gpkspawnpuzzle", description="Force spawn a puzzle piece (Bot Owner only)")
@app_commands.default_permissions(administrator=True)
async def gpkspawnpuzzle(interaction: discord.Interaction):
    # Bot owner check
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("This command is only available to the bot owner.", ephemeral=True)
        return

    settings = await db.get_server_settings(interaction.guild_id)

    if not settings['spawn_channel_id']:
        await interaction.response.send_message(
            "No spawn channel set! Use `/gpksetspawn` first.",
            ephemeral=True
        )
        return

    # Check for existing spawn
    existing = await db.get_active_spawn(interaction.guild_id)
    if existing:
        await interaction.response.send_message(
            "There's already an unclaimed spawn! Catch it first.",
            ephemeral=True
        )
        return

    # Get random puzzle piece
    puzzle, piece = await db.get_random_puzzle_piece()
    if not puzzle or not piece:
        await interaction.response.send_message(
            "No puzzles available in the database!",
            ephemeral=True
        )
        return

    channel = bot.get_channel(settings['spawn_channel_id'])
    if not channel:
        await interaction.response.send_message(
            "Spawn channel not found!",
            ephemeral=True
        )
        return

    await interaction.response.send_message("Spawning a puzzle piece...", ephemeral=True)
    await do_puzzle_spawn(interaction.guild_id, channel, puzzle, piece)
    await db.update_last_spawn_time(interaction.guild_id)


# ============== COMPARE COMMAND ==============
@bot.tree.command(name="gpkcompare", description="Compare your collection to another user")
@app_commands.describe(user="The user to compare with")
async def gpkcompare(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer()

    if user.id == interaction.user.id:
        await interaction.followup.send("You can't compare with yourself!", ephemeral=True)
        return

    # Get both inventories
    my_inventory = await db.get_inventory(interaction.user.id)
    their_inventory = await db.get_inventory(user.id)

    # Create sets of card IDs
    my_cards = {item['card_id'] for item in my_inventory}
    their_cards = {item['card_id'] for item in their_inventory}

    # Find differences
    i_have_they_dont = my_cards - their_cards
    they_have_i_dont = their_cards - my_cards
    we_both_have = my_cards & their_cards

    embed = discord.Embed(
        title=f"Collection Comparison",
        description=f"**{interaction.user.display_name}** vs **{user.display_name}**",
        color=0x3498DB
    )

    embed.add_field(
        name="Summary",
        value=f"You have: **{len(my_cards)}** unique cards\n"
              f"They have: **{len(their_cards)}** unique cards\n"
              f"Both have: **{len(we_both_have)}** cards in common",
        inline=False
    )

    # Cards you have that they don't
    if i_have_they_dont:
        cards_list = []
        for item in sorted(my_inventory, key=lambda x: (x['series'], x['number'], x['variant'])):
            if item['card_id'] in i_have_they_dont:
                name = get_card_display_name(item)
                if item['variant'] == 'b':
                    cards_list.append(f"**{name}**")
                else:
                    cards_list.append(name)

        # Truncate if too long
        display_list = cards_list[:15]
        remaining = len(cards_list) - 15
        text = '\n'.join(display_list)
        if remaining > 0:
            text += f"\n*...and {remaining} more*"

        embed.add_field(
            name=f"You have, they don't ({len(i_have_they_dont)})",
            value=text or "None",
            inline=True
        )
    else:
        embed.add_field(name=f"You have, they don't (0)", value="None", inline=True)

    # Cards they have that you don't
    if they_have_i_dont:
        cards_list = []
        for item in sorted(their_inventory, key=lambda x: (x['series'], x['number'], x['variant'])):
            if item['card_id'] in they_have_i_dont:
                name = get_card_display_name(item)
                if item['variant'] == 'b':
                    cards_list.append(f"**{name}**")
                else:
                    cards_list.append(name)

        # Truncate if too long
        display_list = cards_list[:15]
        remaining = len(cards_list) - 15
        text = '\n'.join(display_list)
        if remaining > 0:
            text += f"\n*...and {remaining} more*"

        embed.add_field(
            name=f"They have, you don't ({len(they_have_i_dont)})",
            value=text or "None",
            inline=True
        )
    else:
        embed.add_field(name=f"They have, you don't (0)", value="None", inline=True)

    await interaction.followup.send(embed=embed)

# ============== HELP PAGINATION VIEW ==============
class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.current_page = 0
        self.pages = self.build_pages()
        self.update_buttons()

    def build_pages(self):
        """Build all help pages."""
        pages = []

        # Page 1: Command List
        embed1 = discord.Embed(
            title="GPK Dex Commands",
            description="Collect Garbage Pail Kids cards!",
            color=0x3498DB
        )
        commands_list = [
            ("`/gpkdaily`", "Claim your daily coins and XP (24h)"),
            ("`/gpkclaim`", "Claim a free random card (1h)"),
            ("`/gpkleveledclaim`", "Level-boosted B chance claim (12h)"),
            ("`/gpkopen`", f"Open a pack ({PACK_COST:,} coins, {CARDS_PER_PACK} cards)"),
            ("`/gpkcatch`", "Catch a spawned card"),
            ("`/gpkcollection`", "View your card collection"),
            ("`/gpkpuzzles`", "View puzzle progress and complete puzzles"),
            ("`/gpkprofile`", "View stats, level, XP, and coins"),
            ("`/gpkshow`", "Display a card you own"),
            ("`/gpkcraft`", "Trade A cards for a B card"),
            ("`/gpktrade`", "Trade cards with another user"),
            ("`/gpkcompare`", "Compare collections with another user"),
            ("`/gpkleaderboard`", "View top collectors"),
        ]
        for cmd, desc in commands_list:
            embed1.add_field(name=cmd, value=desc, inline=False)
        pages.append(embed1)

        # Page 2: Rewards & Economy
        embed2 = discord.Embed(
            title="Rewards & Economy",
            description="How to earn coins and XP",
            color=0x2ECC71
        )
        embed2.add_field(
            name="/gpkdaily Rewards",
            value=f"**Base:** {DAILY_BASE_COINS:,} coins + {DAILY_XP} XP\n"
                  f"**Level Bonus:** +{DAILY_LEVEL_BONUS} coins per level\n"
                  f"• Level 5 = {DAILY_BASE_COINS + 5*DAILY_LEVEL_BONUS:,} coins\n"
                  f"• Level 10 = {DAILY_BASE_COINS + 10*DAILY_LEVEL_BONUS:,} coins",
            inline=False
        )
        embed2.add_field(
            name="/gpkclaim & /gpkcatch Rewards",
            value=f"**Base Coins:** {SPAWN_CATCH_BASE} (+{SPAWN_CATCH_LEVEL_BONUS}/level)\n"
                  f"**Rarity Multipliers:** Epic 20x, Legendary 10x, Ultra Rare 5x, Rare 3x, Uncommon 2x, Common 1x\n"
                  f"**B Variant:** 2x coin bonus\n"
                  f"**New Card Bonus:** +{NEW_CARD_COINS} coins, +{NEW_CARD_XP} XP",
            inline=False
        )
        embed2.add_field(
            name="/gpkopen Rewards",
            value=f"**Cost:** {PACK_COST:,} coins\n"
                  f"**Cards:** {CARDS_PER_PACK} per pack\n"
                  f"**XP:** +{PACK_XP} XP (+{NEW_CARD_XP} per new card)",
            inline=False
        )
        pages.append(embed2)

        # Page 3: Leveled Claim Details
        embed3 = discord.Embed(
            title="Leveled Claim Details",
            description="/gpkleveledclaim - Special claim with level-boosted B card chance!",
            color=0xFFD700
        )
        embed3.add_field(name="Cooldown", value="12 hours", inline=True)
        embed3.add_field(name="Rewards", value=f"Coins by rarity\n+{CATCH_XP} XP (+{NEW_CARD_XP} if new)", inline=True)
        embed3.add_field(
            name="B Card Chance Formula",
            value="**5% + (2% × Level)**, capped at 50%",
            inline=False
        )
        embed3.add_field(
            name="B Chance by Level",
            value="• Level 1: 7%\n"
                  "• Level 5: 15%\n"
                  "• Level 10: 25%\n"
                  "• Level 15: 35%\n"
                  "• Level 20: 45%\n"
                  "• Level 23+: 50% (max)",
            inline=True
        )
        embed3.add_field(
            name="How It Works",
            value="Your level determines if you get a B or A card. "
                  "Then a random card of that type is selected using normal series rarity.",
            inline=False
        )
        pages.append(embed3)

        # Page 4: Card Rarity & Crafting
        embed4 = discord.Embed(
            title="Card Rarity & Crafting",
            description="Understanding card rarity and how to craft B cards",
            color=0x9B59B6
        )
        embed4.add_field(
            name="Rarity Tiers (37 Series)",
            value="• **Epic:** White Border Error (rarest - no B cards!)\n"
                  "• **Legendary:** Flashback 1-3\n"
                  "• **Ultra Rare:** Series 1-3\n"
                  "• **Rare:** Series 4-6, TV Series (17 sets)\n"
                  "• **Uncommon:** Series 7-10\n"
                  "• **Common:** Series 11-15",
            inline=False
        )
        embed4.add_field(
            name="B Variant Drop Rates",
            value="B cards are MUCH rarer than A cards!\n"
                  "• **Legendary B:** ~0.02% (extremely rare)\n"
                  "• **Ultra Rare B:** ~0.5-1%\n"
                  "• **Rare B:** ~1.5-2.5%\n"
                  "• **Uncommon B:** ~4-8%\n"
                  "• **Common B:** ~10-20%",
            inline=True
        )
        embed4.add_field(
            name="Craft Costs (/gpkcraft)",
            value="Trade A cards for the matching B:\n"
                  "• **White Border:** No B cards exist!\n"
                  "• **Flashback 1-3:** 25 A → 1 B\n"
                  "• **Series 1:** 20 A → 1 B\n"
                  "• **Series 2:** 18 A → 1 B\n"
                  "• **Series 3:** 16 A → 1 B",
            inline=True
        )
        embed4.add_field(
            name="Craft Costs (continued)",
            value="• **Series 4-6, TV Series:** 10-14 A → 1 B\n"
                  "• **Series 7-9:** 6-8 A → 1 B\n"
                  "• **Series 10-15:** 5 A → 1 B\n"
                  f"**XP Reward:** +{CRAFT_B_XP} XP per craft",
            inline=True
        )
        embed4.add_field(
            name="Craft by Name",
            value="You can craft using card names!\n"
                  "`/gpkcraft series:\"Adam Bomb\"` or `/gpkcraft os1 8`",
            inline=False
        )
        pages.append(embed4)

        # Page 5: Spawn System
        embed5 = discord.Embed(
            title="Spawn System",
            description="How cards spawn in the channel",
            color=0xE74C3C
        )
        embed5.add_field(
            name="How Spawns Work",
            value="• Cards spawn when there's chat activity\n"
                  "• 15 minute cooldown between spawns\n"
                  "• First person to `/gpkcatch` gets the card\n"
                  "• Bot monitors all channels, spawns in the set channel",
            inline=False
        )
        embed5.add_field(
            name="Mass Spawns (Rare!)",
            value="5% chance for a pack to open, spawning multiple cards!\n"
                  "• **3 cards:** 70% of mass spawns\n"
                  "• **4 cards:** 25% of mass spawns\n"
                  "• **5 cards:** 5% of mass spawns (super rare!)",
            inline=False
        )
        embed5.add_field(
            name="Admin Commands",
            value="`/gpksetspawn [channel]` - Set spawn channel",
            inline=False
        )
        pages.append(embed5)

        # Page 6: Leveling System
        embed6 = discord.Embed(
            title="Leveling System",
            description="How to level up and earn XP",
            color=0x9B59B6
        )
        embed6.add_field(
            name="XP Sources",
            value=f"• `/gpkdaily`: +{DAILY_XP} XP\n"
                  f"• `/gpkopen`: +{PACK_XP} XP (+{NEW_CARD_XP} per new card)\n"
                  f"• `/gpkcatch`: +{CATCH_XP} XP (+{NEW_CARD_XP} if new)\n"
                  f"• `/gpkclaim`: +{CATCH_XP} XP (+{NEW_CARD_XP} if new)\n"
                  f"• `/gpkleveledclaim`: +{CATCH_XP} XP (+{NEW_CARD_XP} if new)\n"
                  f"• `/gpkcraft`: +{CRAFT_B_XP} XP per B card crafted",
            inline=False
        )
        embed6.add_field(
            name="XP Required Per Level",
            value="• Level 1 → 2: 500 XP\n"
                  "• Level 2 → 3: 1,000 more (1,500 total)\n"
                  "• Level 3 → 4: 1,500 more (3,000 total)\n"
                  "• Level 4 → 5: 2,000 more (5,000 total)\n"
                  "• Level 5 → 6: 2,500 more (7,500 total)\n"
                  "*Each level needs 500 more XP than the last*",
            inline=True
        )
        embed6.add_field(
            name="Level Benefits",
            value=f"• +{DAILY_LEVEL_BONUS} daily coins per level\n"
                  f"• +{SPAWN_CATCH_LEVEL_BONUS} card coins per level\n"
                  "• +2% B card chance on `/gpkleveledclaim`",
            inline=True
        )
        pages.append(embed6)

        # Page 7: Puzzles
        embed7 = discord.Embed(
            title="Puzzle System",
            description="Collect puzzle pieces and complete puzzles for rewards!",
            color=0xE91E63
        )
        embed7.add_field(
            name="How Puzzles Work",
            value=f"• **{int(PUZZLE_PIECE_CHANCE*100)}% chance** to get a puzzle piece in each pack\n"
                  "• Each puzzle has **18 pieces** to collect\n"
                  "• Collect all 18 pieces to complete a puzzle\n"
                  "• Use `/gpkpuzzles` to view progress and complete puzzles",
            inline=False
        )
        embed7.add_field(
            name="Puzzle Rarity",
            value="• **Ultra Rare:** Leaky Lindsay / Messy Tessie\n"
                  "• **Rare:** Live Mike / Jolted Joel\n"
                  "• **Uncommon:** U.S. Arnie / Snooty Sam\n"
                  "• **Common:** Mugged Marcus / Kayo'd Cody",
            inline=True
        )
        embed7.add_field(
            name="Rewards",
            value=f"• Puzzle piece: +{PUZZLE_PIECE_XP} XP\n"
                  f"• Complete puzzle: +{PUZZLE_COMPLETE_XP} XP\n"
                  "• Completing uses 1 of each piece",
            inline=True
        )
        embed7.add_field(
            name="Completing Puzzles",
            value="When you have all 18 pieces of a puzzle:\n"
                  "1. Use `/gpkpuzzles` command\n"
                  "2. Navigate to the completed puzzle\n"
                  "3. Click the **Complete** button\n"
                  "4. One of each piece is consumed\n"
                  "5. You receive the completed puzzle card!",
            inline=False
        )
        pages.append(embed7)

        # Page 8: Trading System
        embed8 = discord.Embed(
            title="Trading System",
            description="Trade cards with other collectors!",
            color=0x00CED1
        )
        embed8.add_field(
            name="Trade & Gift Commands",
            value="`/gpktrade @user` - Start a trade with someone\n"
                  "`/gpktrade` - Check your active trade\n"
                  "`/gpktradeadd` - Add a card to your offer\n"
                  "`/gpktraderemove` - Remove a card from your offer\n"
                  "`/gpktradeaddpiece` - Add a puzzle piece to offer\n"
                  "`/gpktraderemovepiece` - Remove a puzzle piece\n"
                  "`/gpktradecancel` - Cancel your active trade\n"
                  "`/gpkgivecard @user` - Give a card to someone\n"
                  "`/gpkgivecoins @user` - Give coins to someone",
            inline=False
        )
        embed8.add_field(
            name="How Trading Works",
            value="1. **Start:** Use `/gpktrade @user` to begin\n"
                  "2. **Add Items:** Both users add cards/pieces simultaneously\n"
                  "3. **Lock:** Click 'Lock Proposal' when your offer is ready\n"
                  "4. **Wait:** 15 second delay before other user can lock\n"
                  "5. **Confirm:** Both users click 'Confirm Trade' to complete\n"
                  "6. **Done:** Items are exchanged and both get a DM!",
            inline=False
        )
        embed8.add_field(
            name="Trade Rules",
            value="• Trade both cards AND puzzle pieces!\n"
                  "• Both users can add items at the same time\n"
                  "• 15 second delay between locks to review changes\n"
                  "• Either player can cancel anytime\n"
                  "• Items verified before trade completes",
            inline=False
        )
        pages.append(embed8)

        return pages

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= len(self.pages) - 1

    def get_embed(self):
        embed = self.pages[self.current_page].copy()
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)}")
        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Help closed.", embed=None, view=None)

# ============== PUZZLES COMMAND ==============
class PuzzleView(discord.ui.View):
    def __init__(self, user_id: int, progress: list, images_path: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.progress = progress
        self.images_path = images_path
        self.current_puzzle = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_puzzle == 0
        self.next_button.disabled = self.current_puzzle >= len(self.progress) - 1

        # Update complete button
        current = self.progress[self.current_puzzle]
        can_complete = current['owned_pieces'] >= current['total_pieces']
        self.complete_button.disabled = not can_complete
        if can_complete:
            self.complete_button.style = discord.ButtonStyle.success
        else:
            self.complete_button.style = discord.ButtonStyle.secondary

    def get_embed_and_file(self):
        """Returns (embed, file) tuple - file may be None if no preview available."""
        current = self.progress[self.current_puzzle]
        puzzle = current['puzzle']

        # Create progress bar
        owned = current['owned_pieces']
        total = current['total_pieces']
        filled = int((owned / total) * 10)
        progress_bar = "█" * filled + "░" * (10 - filled)

        embed = discord.Embed(
            title=f"Puzzle: {puzzle['name']}",
            description=puzzle['description'] or "",
            color=get_puzzle_rarity_color(puzzle)
        )

        embed.add_field(
            name="Progress",
            value=f"{progress_bar} {owned}/{total} pieces",
            inline=False
        )

        embed.add_field(
            name="Rarity",
            value=get_puzzle_rarity_name(puzzle),
            inline=True
        )

        embed.add_field(
            name="Times Completed",
            value=str(current['times_completed']),
            inline=True
        )

        # Show which pieces are owned
        if current['owned_piece_numbers']:
            owned_nums = sorted([int(n) for n in current['owned_piece_numbers']])
            missing_nums = [i for i in range(1, 19) if i not in owned_nums]
            puzzle_id = puzzle['puzzle_id']

            if len(missing_nums) <= 6:
                embed.add_field(
                    name="Missing Pieces",
                    value=', '.join(get_piece_label(puzzle_id, n) for n in missing_nums) or "None!",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Owned Pieces",
                    value=', '.join(get_piece_label(puzzle_id, n) for n in owned_nums[:12]) + ("..." if len(owned_nums) > 12 else ""),
                    inline=False
                )

        if owned >= total:
            embed.add_field(
                name="READY TO COMPLETE!",
                value="Click the Complete button to finish this puzzle!",
                inline=False
            )

        embed.set_footer(text=f"Puzzle {self.current_puzzle + 1} of {len(self.progress)} | Preview shows piece positions")

        # Try to attach preview image
        file = None
        preview_path = get_puzzle_preview_path(puzzle['puzzle_id'], self.images_path)
        if preview_path and os.path.exists(preview_path):
            filename = os.path.basename(preview_path)
            file = discord.File(preview_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")

        return embed, file

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="◀")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your puzzle view!", ephemeral=True)
            return
        self.current_puzzle -= 1
        self.update_buttons()
        embed, file = self.get_embed_and_file()
        if file:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.secondary, emoji="✅")
    async def complete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your puzzle view!", ephemeral=True)
            return

        current = self.progress[self.current_puzzle]
        puzzle = current['puzzle']

        # Try to complete the puzzle
        success = await db.complete_puzzle(self.user_id, puzzle['puzzle_id'])

        if success:
            # Award XP
            leveled_up, new_level = await db.add_xp(self.user_id, PUZZLE_COMPLETE_XP)

            # Refresh progress
            self.progress = await db.get_puzzle_progress(self.user_id)
            self.update_buttons()

            embed = discord.Embed(
                title="Puzzle Completed!",
                description=f"You completed **{puzzle['name']}**!",
                color=0xFFD700
            )
            embed.add_field(name="XP Earned", value=f"+{PUZZLE_COMPLETE_XP}", inline=True)

            if leveled_up:
                embed.add_field(name="LEVEL UP!", value=f"Level {new_level}!", inline=True)

            # Try to show the completed puzzle image
            image_path = await get_puzzle_image_path(puzzle, self.images_path)
            if os.path.exists(image_path):
                file = discord.File(image_path, filename=puzzle['complete_filename'])
                embed.set_image(url=f"attachment://{puzzle['complete_filename']}")
                await interaction.response.send_message(embed=embed, file=file)
            else:
                await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Could not complete puzzle. Are you missing pieces?", ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="▶")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your puzzle view!", ephemeral=True)
            return
        self.current_puzzle += 1
        self.update_buttons()
        embed, file = self.get_embed_and_file()
        if file:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[file])
        else:
            await interaction.response.edit_message(embed=embed, view=self, attachments=[])

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="✖")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your puzzle view!", ephemeral=True)
            return
        await interaction.response.edit_message(content="Puzzles view closed.", embed=None, view=None, attachments=[])


@bot.tree.command(name="gpkpuzzles", description="View your puzzle collection progress")
async def gpkpuzzles(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    progress = await db.get_puzzle_progress(interaction.user.id)

    if not progress:
        await interaction.followup.send("No puzzles available yet!", ephemeral=True)
        return

    view = PuzzleView(interaction.user.id, progress, IMAGES_PATH)
    embed, file = view.get_embed_and_file()
    if file:
        await interaction.followup.send(embed=embed, view=view, file=file, ephemeral=True)
    else:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ============== TRADE SYSTEM ==============

def get_puzzle_piece_display_name(piece: dict) -> str:
    """Get display name for a puzzle piece."""
    puzzle_id = piece.get('puzzle_id')
    piece_number = piece['piece_number']
    label = get_piece_label(puzzle_id, piece_number) if puzzle_id else f"#{piece_number}"
    return f"{piece['puzzle_name']} Piece {label}"


TRADE_LOCK_DELAY = 15  # Seconds before second user can lock after first user locks


class LiveTradeView(discord.ui.View):
    """Live trade view that both users interact with simultaneously."""

    def __init__(self, trade_id: int, initiator_id: int, partner_id: int, channel=None):
        super().__init__(timeout=600)  # 10 minute timeout
        self.trade_id = trade_id
        self.initiator_id = initiator_id
        self.partner_id = partner_id
        self.channel = channel
        self.message = None  # Will be set after sending
        self.auto_update_task = None
        self.stopped = False

    def is_participant(self, user_id: int) -> bool:
        return user_id in (self.initiator_id, self.partner_id)

    async def start_auto_update(self, message):
        """Start the auto-update loop."""
        self.message = message
        self.auto_update_task = asyncio.create_task(self._auto_update_loop())

    async def _auto_update_loop(self):
        """Update the trade view every 15 seconds."""
        while not self.stopped:
            await asyncio.sleep(15)
            if self.stopped:
                break
            try:
                trade = await db.get_trade(self.trade_id)
                if not trade or trade['status'] in ('completed', 'cancelled'):
                    self.stopped = True
                    break
                self.update_buttons(trade)
                embed = await self.get_embed()
                await self.message.edit(embed=embed, view=self)
            except Exception as e:
                logger.error(f"Error in trade auto-update: {e}")
                break

    def stop_auto_update(self):
        """Stop the auto-update loop."""
        self.stopped = True
        if self.auto_update_task:
            self.auto_update_task.cancel()

    async def on_timeout(self):
        """Called when the view times out."""
        self.stop_auto_update()

    async def get_embed(self):
        trade = await db.get_trade(self.trade_id)
        if not trade:
            return discord.Embed(title="Trade Not Found", color=0xE74C3C)

        try:
            initiator = await bot.fetch_user(self.initiator_id)
            partner = await bot.fetch_user(self.partner_id)
        except:
            return discord.Embed(title="Error fetching users", color=0xE74C3C)

        initiator_name = initiator.display_name
        partner_name = partner.display_name

        # Get all items
        init_cards = await db.get_trade_items(self.trade_id, self.initiator_id)
        init_puzzles = await db.get_trade_puzzle_items(self.trade_id, self.initiator_id)
        part_cards = await db.get_trade_items(self.trade_id, self.partner_id)
        part_puzzles = await db.get_trade_puzzle_items(self.trade_id, self.partner_id)

        def build_offer(card_items, puzzle_items):
            parts = []
            if card_items:
                parts.extend([f"**{get_card_display_name(item)}** x{item['quantity']}" for item in card_items])
            if puzzle_items:
                parts.extend([f"**{get_puzzle_piece_display_name(item)}** x{item['quantity']}" for item in puzzle_items])
            return '\n'.join(parts) if parts else "*No items yet*"

        # Determine status
        init_locked = trade.get('initiator_locked_at') is not None
        part_locked = trade.get('partner_locked_at') is not None
        init_confirmed = trade.get('initiator_confirmed', 0) == 1
        part_confirmed = trade.get('partner_confirmed', 0) == 1
        both_locked = init_locked and part_locked

        if trade['status'] == 'completed':
            color = 0x00FF00  # Green
            status_text = "TRADE COMPLETED"
        elif trade['status'] == 'cancelled':
            color = 0xFF0000  # Red
            status_text = "TRADE CANCELLED"
        elif both_locked:
            color = 0xFFD700  # Gold
            if init_confirmed and part_confirmed:
                status_text = "Both confirmed - Executing trade..."
            elif init_confirmed:
                status_text = f"{initiator_name} confirmed. Waiting for {partner_name} to confirm."
            elif part_confirmed:
                status_text = f"{partner_name} confirmed. Waiting for {initiator_name} to confirm."
            else:
                status_text = "Both proposals LOCKED. Click 'Confirm Trade' to complete."
        elif init_locked:
            color = 0xFFA500  # Orange
            status_text = f"{initiator_name} has LOCKED their proposal. Waiting for {partner_name} to lock."
        elif part_locked:
            color = 0xFFA500  # Orange
            status_text = f"{partner_name} has LOCKED their proposal. Waiting for {initiator_name} to lock."
        else:
            color = 0x3498DB  # Blue
            status_text = "Both users can add cards. Lock your proposal when ready."

        embed = discord.Embed(
            title=f"Trade: {initiator_name} & {partner_name}",
            description=f"Use `/gpktradeadd` and `/gpktraderemove` to modify your offer.\nThis window updates every 15 seconds.",
            color=color
        )

        # Show offers with lock status
        init_status = " LOCKED" if init_locked else ""
        part_status = " LOCKED" if part_locked else ""

        embed.add_field(
            name=f"{initiator_name}'s Offer{init_status}",
            value=build_offer(init_cards, init_puzzles)[:1024],
            inline=True
        )
        embed.add_field(
            name=f"{partner_name}'s Offer{part_status}",
            value=build_offer(part_cards, part_puzzles)[:1024],
            inline=True
        )

        embed.add_field(name="Status", value=status_text, inline=False)

        # Instructions
        if not both_locked:
            embed.set_footer(text="Add cards with /gpktradeadd | Lock when ready | 15s delay between locks")
        else:
            embed.set_footer(text="Both locked! Confirm to complete the trade.")

        return embed

    def update_buttons(self, trade: dict):
        """Update button states based on trade status."""
        init_locked = trade.get('initiator_locked_at') is not None
        part_locked = trade.get('partner_locked_at') is not None
        both_locked = init_locked and part_locked

        if trade['status'] in ('completed', 'cancelled'):
            # Disable all buttons
            self.lock_button.disabled = True
            self.confirm_button.disabled = True
            self.cancel_button.disabled = True
            self.lock_button.label = "Trade Ended"
            self.confirm_button.style = discord.ButtonStyle.secondary
        elif both_locked:
            # Both locked - show confirm button
            self.lock_button.disabled = True
            self.lock_button.label = "Both Locked"
            self.confirm_button.disabled = False
            self.confirm_button.style = discord.ButtonStyle.success
        else:
            # Still in adding phase
            self.lock_button.disabled = False
            self.lock_button.label = "Lock Proposal"
            self.confirm_button.disabled = True
            self.confirm_button.style = discord.ButtonStyle.secondary

    @discord.ui.button(label="Lock Proposal", style=discord.ButtonStyle.primary, row=0)
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_participant(interaction.user.id):
            await interaction.response.send_message("This isn't your trade!", ephemeral=True)
            return

        trade = await db.get_trade(self.trade_id)
        if not trade:
            await interaction.response.send_message("Trade not found!", ephemeral=True)
            return

        is_initiator = interaction.user.id == self.initiator_id
        my_locked = trade.get('initiator_locked_at') if is_initiator else trade.get('partner_locked_at')
        other_locked_at = trade.get('partner_locked_at') if is_initiator else trade.get('initiator_locked_at')

        # Already locked?
        if my_locked:
            await interaction.response.send_message("You've already locked your proposal!", ephemeral=True)
            return

        # Check 15 second delay if other user locked first
        if other_locked_at:
            # Parse the timestamp
            if isinstance(other_locked_at, str):
                other_locked_time = datetime.fromisoformat(other_locked_at.replace('Z', '+00:00').replace('+00:00', ''))
            else:
                other_locked_time = other_locked_at

            now = datetime.utcnow()
            elapsed = (now - other_locked_time).total_seconds()

            if elapsed < TRADE_LOCK_DELAY:
                remaining = int(TRADE_LOCK_DELAY - elapsed)
                await interaction.response.send_message(
                    f"Please wait {remaining} more seconds to ensure you see the latest trade updates before locking.",
                    ephemeral=True
                )
                return

        # Check user has items to trade
        my_cards = await db.get_trade_items(self.trade_id, interaction.user.id)
        my_puzzles = await db.get_trade_puzzle_items(self.trade_id, interaction.user.id)

        if not my_cards and not my_puzzles:
            await interaction.response.send_message("You must add at least one item before locking!", ephemeral=True)
            return

        # Lock the proposal
        updated_trade = await db.lock_trade_proposal(self.trade_id, interaction.user.id)

        # Update the view
        self.update_buttons(updated_trade)
        embed = await self.get_embed()

        await interaction.response.edit_message(embed=embed, view=self)

        # Notify user
        both_locked = updated_trade.get('initiator_locked_at') and updated_trade.get('partner_locked_at')
        if both_locked:
            await interaction.followup.send(
                "Your proposal is locked. Both users are now locked. Click 'Confirm Trade' to complete!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "Your proposal is locked. Waiting for the other user to lock their proposal.",
                ephemeral=True
            )

    @discord.ui.button(label="Confirm Trade", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_participant(interaction.user.id):
            await interaction.response.send_message("This isn't your trade!", ephemeral=True)
            return

        trade = await db.get_trade(self.trade_id)
        if not trade:
            await interaction.response.send_message("Trade not found!", ephemeral=True)
            return

        # Must be locked
        if trade['status'] != 'locked':
            await interaction.response.send_message("Both users must lock their proposals first!", ephemeral=True)
            return

        is_initiator = interaction.user.id == self.initiator_id
        my_confirmed = trade.get('initiator_confirmed', 0) if is_initiator else trade.get('partner_confirmed', 0)

        if my_confirmed:
            await interaction.response.send_message("You've already confirmed!", ephemeral=True)
            return

        # Confirm
        updated_trade = await db.confirm_trade(self.trade_id, interaction.user.id)

        # Check if both confirmed
        if updated_trade.get('initiator_confirmed') and updated_trade.get('partner_confirmed'):
            # Execute the trade
            success = await db.execute_trade(self.trade_id)

            if success:
                await db.update_trade_status(self.trade_id, 'completed')
                self.stop_auto_update()  # Stop auto-updating
                # Update embed to show completed
                trade = await db.get_trade(self.trade_id)
                self.update_buttons(trade)
                embed = await self.get_embed()
                await interaction.response.edit_message(embed=embed, view=self)

                # Send ephemeral completion message to the user who confirmed
                try:
                    initiator = await bot.fetch_user(self.initiator_id)
                    partner = await bot.fetch_user(self.partner_id)
                    other_name = partner.display_name if interaction.user.id == self.initiator_id else initiator.display_name
                    await interaction.followup.send(
                        f"Trade completed! Items have been exchanged with **{other_name}**.",
                        ephemeral=True
                    )
                except:
                    pass
            else:
                await db.cancel_trade(self.trade_id)
                self.stop_auto_update()  # Stop auto-updating
                await interaction.response.edit_message(
                    content="Trade failed! One or both users no longer have the required items.",
                    embed=None,
                    view=None
                )
        else:
            # Still waiting for other user
            self.update_buttons(updated_trade)
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(
                "You've confirmed! Waiting for the other user to confirm.",
                ephemeral=True
            )

    @discord.ui.button(label="Cancel Trade", style=discord.ButtonStyle.danger, row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_participant(interaction.user.id):
            await interaction.response.send_message("This isn't your trade!", ephemeral=True)
            return

        await db.cancel_trade(self.trade_id)
        self.stop_auto_update()  # Stop auto-updating

        trade = await db.get_trade(self.trade_id)
        self.update_buttons(trade)
        embed = await self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_participant(interaction.user.id):
            await interaction.response.send_message("This isn't your trade!", ephemeral=True)
            return

        trade = await db.get_trade(self.trade_id)
        if trade:
            self.update_buttons(trade)
        embed = await self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)


@bot.tree.command(name="gpktrade", description="Start or manage a trade with another user")
@app_commands.describe(user="The user to trade with (leave empty to check existing trade)")
async def gpktrade(interaction: discord.Interaction, user: discord.User = None):
    await interaction.response.defer()

    # Check for existing active trade
    existing = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)

    if existing:
        # Show the live trade view for existing trade
        trade = existing
        view = LiveTradeView(trade['trade_id'], trade['initiator_id'], trade['partner_id'], interaction.channel)
        view.update_buttons(trade)
        embed = await view.get_embed()
        message = await interaction.followup.send(embed=embed, view=view)
        await view.start_auto_update(message)
        return

    # No existing trade - need a partner to start new one
    if not user:
        await interaction.followup.send(
            "You don't have an active trade. Use `/gpktrade @user` to start a new trade!",
            ephemeral=True
        )
        return

    if user.id == interaction.user.id:
        await interaction.followup.send("You can't trade with yourself!", ephemeral=True)
        return

    if user.bot:
        await interaction.followup.send("You can't trade with bots!", ephemeral=True)
        return

    # Check if partner has an active trade
    partner_trade = await db.get_active_trade_for_user(user.id, interaction.guild_id)
    if partner_trade:
        await interaction.followup.send(
            f"{user.display_name} is already in an active trade!",
            ephemeral=True
        )
        return

    # Create new trade
    trade_id = await db.create_trade(interaction.user.id, user.id, interaction.guild_id)

    # Create and send the live trade view (public so both users can see it)
    trade = await db.get_trade(trade_id)
    view = LiveTradeView(trade_id, interaction.user.id, user.id, interaction.channel)
    view.update_buttons(trade)
    embed = await view.get_embed()

    message = await interaction.followup.send(
        content=f"{interaction.user.mention} has started a trade with {user.mention}!\nBoth users can add cards using `/gpktradeadd`. Lock your proposal when ready.",
        embed=embed,
        view=view
    )
    await view.start_auto_update(message)


def parse_card_identifier(card_id: str):
    """Parse a card identifier like 'OS2-85A', 'FB1-5A', 'WB-10A', 'TV-6B' into (series, number, variant)."""
    import re
    card_id = card_id.lower().replace(' ', '').replace('-', '')

    # Match OS series: OS2-85A, os9-367a, etc.
    # Series is 1-15, so match os followed by 1-9 or 10-15
    match = re.match(r'^(os(?:1[0-5]|[1-9]))(\d+)([ab])$', card_id)
    if match:
        return match.group(1), int(match.group(2)), match.group(3)

    # Match Flashback series: FB1-5A, fb2_10b, etc.
    match = re.match(r'^(fb[123])(\d+)([ab])$', card_id)
    if match:
        return match.group(1), int(match.group(2)), match.group(3)

    # Match White Border: WB-10A, wb_5a, etc.
    match = re.match(r'^(wb)(\d+)([a])$', card_id)  # WB only has A variants
    if match:
        return match.group(1), int(match.group(2)), match.group(3)

    # Match TV Cartoon: TV-6A, tv_cartoon_6b, tv6a, etc.
    match = re.match(r'^(tv|tvcartoon|tv_cartoon)(\d+)([ab])$', card_id)
    if match:
        return 'tv_cartoon', int(match.group(2)), match.group(3)

    return None, None, None


async def owned_card_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for cards the user owns."""
    inventory = await db.get_inventory(interaction.user.id)
    choices = []
    current_lower = current.lower().replace(' ', '').replace('-', '')

    for item in inventory:
        # Format: OS2-85A (quantity)
        card_id = f"{item['series'].upper()}-{item['number']}{item['variant'].upper()}"
        card_name = get_card_display_name(item)
        search_str = card_id.lower().replace('-', '')

        # Match if current text is in the card ID or name
        if current_lower in search_str or current_lower in card_name.lower():
            display = f"{card_id} - {card_name.split('(')[0].strip()} (x{item['quantity']})"
            # Truncate if too long (Discord limit is 100 chars)
            if len(display) > 100:
                display = display[:97] + "..."
            choices.append(app_commands.Choice(name=display, value=card_id))

        if len(choices) >= 25:  # Discord limit
            break

    return choices


@bot.tree.command(name="gpktradeadd", description="Add a card to your trade offer")
@app_commands.describe(
    card="The card (e.g., OS2-85A or OS12-465B)",
    quantity="How many to add (default 1)"
)
async def gpktradeadd(interaction: discord.Interaction, card: str, quantity: int = 1):
    # Parse the card identifier
    series, number, variant = parse_card_identifier(card)
    if not series:
        await interaction.response.send_message(
            f"Invalid card format! Use format like `OS2-85A` or `OS12-465B`",
            ephemeral=True
        )
        return

    # Check for active trade
    trade = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)
    if not trade:
        await interaction.response.send_message("You don't have an active trade!", ephemeral=True)
        return

    # Check if user's proposal is locked
    is_initiator = trade['initiator_id'] == interaction.user.id
    my_locked = trade.get('initiator_locked_at') if is_initiator else trade.get('partner_locked_at')
    if my_locked:
        await interaction.response.send_message("Your proposal is locked! You can't add more cards.", ephemeral=True)
        return

    # Get the card
    card_data = await db.get_card_by_name(series, number, variant)
    if not card_data:
        await interaction.response.send_message(f"Card {series.upper()}-{number}{variant.upper()} doesn't exist!", ephemeral=True)
        return

    # Check ownership
    owned = await db.get_user_card_quantity(interaction.user.id, card_data['card_id'])
    if owned < 1:
        await interaction.response.send_message(f"You don't own {get_card_display_name(card_data)}!", ephemeral=True)
        return

    # Check how many already in trade
    my_items = await db.get_trade_items(trade['trade_id'], interaction.user.id)
    in_trade = sum(i['quantity'] for i in my_items if i['card_id'] == card_data['card_id'])

    if in_trade + quantity > owned:
        await interaction.response.send_message(
            f"You only have {owned} of this card and {in_trade} are already in the trade!",
            ephemeral=True
        )
        return

    await db.add_trade_item(trade['trade_id'], interaction.user.id, card_data['card_id'], quantity)
    await interaction.response.send_message(
        f"Added {quantity}x **{get_card_display_name(card_data)}** to your trade offer!",
        ephemeral=True
    )

@gpktradeadd.autocomplete('card')
async def gpktradeadd_card_autocomplete(interaction: discord.Interaction, current: str):
    return await owned_card_autocomplete(interaction, current)


@bot.tree.command(name="gpktraderemove", description="Remove a card from your trade offer")
@app_commands.describe(
    card="The card (e.g., OS2-85A or OS12-465B)",
    quantity="How many to remove (default 1)"
)
async def gpktraderemove(interaction: discord.Interaction, card: str, quantity: int = 1):
    # Parse the card identifier
    series, number, variant = parse_card_identifier(card)
    if not series:
        await interaction.response.send_message(
            f"Invalid card format! Use format like `OS2-85A` or `OS12-465B`",
            ephemeral=True
        )
        return

    trade = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)
    if not trade:
        await interaction.response.send_message("You don't have an active trade!", ephemeral=True)
        return

    # Check if user's proposal is locked
    is_initiator = trade['initiator_id'] == interaction.user.id
    my_locked = trade.get('initiator_locked_at') if is_initiator else trade.get('partner_locked_at')
    if my_locked:
        await interaction.response.send_message("Your proposal is locked! You can't remove cards.", ephemeral=True)
        return

    card_data = await db.get_card_by_name(series, number, variant)
    if not card_data:
        await interaction.response.send_message(f"Card {series.upper()}-{number}{variant.upper()} doesn't exist!", ephemeral=True)
        return

    await db.remove_trade_item(trade['trade_id'], interaction.user.id, card_data['card_id'], quantity)
    await interaction.response.send_message(
        f"Removed {quantity}x **{get_card_display_name(card_data)}** from your trade offer!",
        ephemeral=True
    )

@gpktraderemove.autocomplete('card')
async def gpktraderemove_card_autocomplete(interaction: discord.Interaction, current: str):
    return await owned_card_autocomplete(interaction, current)


@bot.tree.command(name="gpktradeaddpiece", description="Add a puzzle piece to your trade offer")
@app_commands.describe(
    puzzle="The puzzle number (1-4)",
    piece="The piece number (1-18)",
    quantity="How many to add (default 1)"
)
async def gpktradeaddpiece(interaction: discord.Interaction, puzzle: int, piece: int, quantity: int = 1):
    # Check for active trade
    trade = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)
    if not trade:
        await interaction.response.send_message("You don't have an active trade!", ephemeral=True)
        return

    # Validate puzzle and piece numbers
    if puzzle < 1 or puzzle > 4:
        await interaction.response.send_message("Puzzle must be 1-4!", ephemeral=True)
        return
    if piece < 1 or piece > 18:
        await interaction.response.send_message("Piece must be 1-18!", ephemeral=True)
        return

    # Check if user's proposal is locked
    is_initiator = trade['initiator_id'] == interaction.user.id
    my_locked = trade.get('initiator_locked_at') if is_initiator else trade.get('partner_locked_at')
    if my_locked:
        await interaction.response.send_message("Your proposal is locked! You can't add more pieces.", ephemeral=True)
        return

    # Get the puzzle piece
    pieces = await db.get_puzzle_pieces(puzzle)
    target_piece = None
    for p in pieces:
        if p['piece_number'] == piece:
            target_piece = p
            break

    if not target_piece:
        await interaction.response.send_message(f"Puzzle {puzzle} piece #{piece} doesn't exist!", ephemeral=True)
        return

    # Check ownership
    owned = await db.get_user_puzzle_piece_quantity(interaction.user.id, target_piece['piece_id'])
    if owned < 1:
        piece_label = get_piece_label(puzzle, piece)
        await interaction.response.send_message(f"You don't own Puzzle {puzzle} Piece {piece_label}!", ephemeral=True)
        return

    # Check how many already in trade
    my_items = await db.get_trade_puzzle_items(trade['trade_id'], interaction.user.id)
    in_trade = sum(i['quantity'] for i in my_items if i['piece_id'] == target_piece['piece_id'])

    if in_trade + quantity > owned:
        await interaction.response.send_message(
            f"You only have {owned} of this piece and {in_trade} are already in the trade!",
            ephemeral=True
        )
        return

    await db.add_trade_puzzle_item(trade['trade_id'], interaction.user.id, target_piece['piece_id'], quantity)

    # Get puzzle name for display
    puzzle_info = await db.get_puzzle_by_id(puzzle)
    puzzle_name = puzzle_info['name'] if puzzle_info else f"Puzzle {puzzle}"
    piece_label = get_piece_label(puzzle, piece)

    await interaction.response.send_message(
        f"Added {quantity}x **{puzzle_name} Piece {piece_label}** to your trade offer!",
        ephemeral=True
    )


@bot.tree.command(name="gpktraderemovepiece", description="Remove a puzzle piece from your trade offer")
@app_commands.describe(
    puzzle="The puzzle number (1-4)",
    piece="The piece number (1-18)",
    quantity="How many to remove (default 1)"
)
async def gpktraderemovepiece(interaction: discord.Interaction, puzzle: int, piece: int, quantity: int = 1):
    trade = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)
    if not trade:
        await interaction.response.send_message("You don't have an active trade!", ephemeral=True)
        return

    # Validate puzzle and piece numbers
    if puzzle < 1 or puzzle > 4:
        await interaction.response.send_message("Puzzle must be 1-4!", ephemeral=True)
        return
    if piece < 1 or piece > 18:
        await interaction.response.send_message("Piece must be 1-18!", ephemeral=True)
        return

    # Check if user's proposal is locked
    is_initiator = trade['initiator_id'] == interaction.user.id
    my_locked = trade.get('initiator_locked_at') if is_initiator else trade.get('partner_locked_at')
    if my_locked:
        await interaction.response.send_message("Your proposal is locked! You can't remove pieces.", ephemeral=True)
        return

    # Get the puzzle piece
    pieces = await db.get_puzzle_pieces(puzzle)
    target_piece = None
    for p in pieces:
        if p['piece_number'] == piece:
            target_piece = p
            break

    if not target_piece:
        await interaction.response.send_message(f"Puzzle {puzzle} piece #{piece} doesn't exist!", ephemeral=True)
        return

    await db.remove_trade_puzzle_item(trade['trade_id'], interaction.user.id, target_piece['piece_id'], quantity)

    puzzle_info = await db.get_puzzle_by_id(puzzle)
    puzzle_name = puzzle_info['name'] if puzzle_info else f"Puzzle {puzzle}"
    piece_label = get_piece_label(puzzle, piece)

    await interaction.response.send_message(
        f"Removed {quantity}x **{puzzle_name} Piece {piece_label}** from your trade offer!",
        ephemeral=True
    )


@bot.tree.command(name="gpktradecancel", description="Cancel your active trade")
async def gpktradecancel(interaction: discord.Interaction):
    trade = await db.get_active_trade_for_user(interaction.user.id, interaction.guild_id)
    if not trade:
        await interaction.response.send_message("You don't have an active trade to cancel!", ephemeral=True)
        return

    await db.cancel_trade(trade['trade_id'])
    await interaction.response.send_message("Trade cancelled!", ephemeral=True)


# ============== GIFT COMMANDS ==============
@bot.tree.command(name="gpkgivecard", description="Give a card to another user")
@app_commands.describe(
    user="The user to give the card to",
    card="The card to give (e.g., OS2-85A, FB1-5B, WB-10A, TV-6A)",
    quantity="Number of cards to give (default: 1)"
)
@app_commands.autocomplete(card=owned_card_autocomplete)
async def gpkgivecard(interaction: discord.Interaction, user: discord.User, card: str, quantity: int = 1):
    # Can't give to yourself
    if user.id == interaction.user.id:
        await interaction.response.send_message("You can't give cards to yourself!", ephemeral=True)
        return

    # Can't give to bots
    if user.bot:
        await interaction.response.send_message("You can't give cards to bots!", ephemeral=True)
        return

    # Validate quantity
    if quantity < 1:
        await interaction.response.send_message("Quantity must be at least 1!", ephemeral=True)
        return

    # Parse the card identifier
    series, number, variant = parse_card_identifier(card)
    if not series:
        await interaction.response.send_message(
            f"Invalid card format! Use format like `OS2-85A`, `FB1-5B`, `WB-10A`, or `TV-6A`",
            ephemeral=True
        )
        return

    # Get the card from database
    card_data = await db.get_card_by_name(series, number, variant)
    if not card_data:
        await interaction.response.send_message(f"Card {series.upper()}-{number}{variant.upper()} doesn't exist!", ephemeral=True)
        return

    # Check ownership
    owned = await db.get_user_card_quantity(interaction.user.id, card_data['card_id'])
    if owned < quantity:
        if owned == 0:
            await interaction.response.send_message(f"You don't own {get_card_display_name(card_data)}!", ephemeral=True)
        else:
            await interaction.response.send_message(f"You only have {owned} of this card!", ephemeral=True)
        return

    # Show confirmation
    card_display = get_card_display_name(card_data)
    qty_text = f"{quantity}x " if quantity > 1 else ""
    embed = discord.Embed(
        title="🎁 Give Card?",
        description=f"Are you sure you want to give **{qty_text}{card_display}** to **{user.display_name}**?\n\n"
                    f"You currently own: **{owned}** of this card\n"
                    f"After giving: **{owned - quantity}** remaining",
        color=0x9B59B6
    )

    view = GiveConfirmView(interaction.user.id, 'card', card_display, user.display_name)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    await view.wait()
    if not view.confirmed:
        return

    # Re-check ownership (in case they traded/gave it away while confirming)
    owned = await db.get_user_card_quantity(interaction.user.id, card_data['card_id'])
    if owned < quantity:
        await interaction.edit_original_response(
            content=f"You no longer have enough of this card! You have {owned}.",
            embed=None, view=None
        )
        return

    # Ensure recipient exists in database
    await db.get_user(user.id)

    # Transfer the card(s)
    success = await db.remove_cards_from_inventory(interaction.user.id, card_data['card_id'], quantity)
    if not success:
        await interaction.edit_original_response(
            content="Failed to remove card from your inventory!",
            embed=None, view=None
        )
        return

    for _ in range(quantity):
        await db.add_card_to_inventory(user.id, card_data['card_id'])

    # Success message
    qty_text = f"{quantity}x " if quantity > 1 else ""
    embed = discord.Embed(
        title="🎁 Gift Sent!",
        description=f"You gave **{qty_text}{card_display}** to **{user.display_name}**!",
        color=0x2ECC71
    )
    await interaction.edit_original_response(embed=embed, view=None)

    # Notify in channel (visible only to recipient)
    try:
        notify_embed = discord.Embed(
            title="🎁 You Received a Gift!",
            description=f"**{interaction.user.display_name}** gave you **{qty_text}{card_display}**!",
            color=0x2ECC71
        )
        await interaction.channel.send(embed=notify_embed, content=f"{user.mention}", delete_after=30)
    except:
        pass


@bot.tree.command(name="gpkgivecoins", description="Give coins to another user")
@app_commands.describe(
    user="The user to give coins to",
    amount="Amount of coins to give"
)
async def gpkgivecoins(interaction: discord.Interaction, user: discord.User, amount: int):
    # Can't give to yourself
    if user.id == interaction.user.id:
        await interaction.response.send_message("You can't give coins to yourself!", ephemeral=True)
        return

    # Can't give to bots
    if user.bot:
        await interaction.response.send_message("You can't give coins to bots!", ephemeral=True)
        return

    # Validate amount
    if amount < 1:
        await interaction.response.send_message("Amount must be at least 1 coin!", ephemeral=True)
        return

    # Check if user has enough coins
    giver = await db.get_user(interaction.user.id)
    if giver['coins'] < amount:
        await interaction.response.send_message(
            f"You don't have enough coins! You have **{giver['coins']:,}** coins.",
            ephemeral=True
        )
        return

    # Show confirmation
    embed = discord.Embed(
        title="🎁 Give Coins?",
        description=f"Are you sure you want to give **{amount:,} coins** to **{user.display_name}**?\n\n"
                    f"Your balance: **{giver['coins']:,}** coins\n"
                    f"After giving: **{giver['coins'] - amount:,}** coins",
        color=0xF1C40F
    )

    view = GiveConfirmView(interaction.user.id, 'coins', str(amount), user.display_name)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    await view.wait()
    if not view.confirmed:
        return

    # Re-check balance (in case they spent coins while confirming)
    giver = await db.get_user(interaction.user.id)
    if giver['coins'] < amount:
        await interaction.edit_original_response(
            content=f"You no longer have enough coins! You have {giver['coins']:,} coins.",
            embed=None, view=None
        )
        return

    # Ensure recipient exists in database
    await db.get_user(user.id)

    # Transfer the coins
    await db.add_coins(interaction.user.id, -amount)
    await db.add_coins(user.id, amount)

    # Success message
    embed = discord.Embed(
        title="🎁 Gift Sent!",
        description=f"You gave **{amount:,} coins** to **{user.display_name}**!",
        color=0x2ECC71
    )
    await interaction.edit_original_response(embed=embed, view=None)

    # Notify in channel (visible only to recipient)
    try:
        notify_embed = discord.Embed(
            title="🎁 You Received a Gift!",
            description=f"**{interaction.user.display_name}** gave you **{amount:,} coins**!",
            color=0x2ECC71
        )
        await interaction.channel.send(embed=notify_embed, content=f"{user.mention}", delete_after=30)
    except:
        pass


# ============== HELP COMMAND ==============
@bot.tree.command(name="gpkhelp", description="Show all GPK Dex commands and info")
async def gpkhelp(interaction: discord.Interaction):
    view = HelpView()
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

# Run the bot
if __name__ == '__main__':
    bot.run(TOKEN)
