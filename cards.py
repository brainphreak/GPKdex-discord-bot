import os
import json
import random
import aiosqlite
from database import DATABASE_PATH

# Load card names from JSON file
CARD_NAMES_PATH = os.path.join(os.path.dirname(__file__), 'card_names.json')
CARD_NAMES = {}

def load_card_names():
    """Load card names from JSON file."""
    global CARD_NAMES
    try:
        with open(CARD_NAMES_PATH, 'r') as f:
            CARD_NAMES = json.load(f)
    except Exception as e:
        print(f"Warning: Could not load card names: {e}")
        CARD_NAMES = {}

# Load names on module import
load_card_names()

# Card rarity configuration - Series 1 is rarest, Series 15 is most common
# Rarity tiers: Epic (White Border), Legendary (Flashback), Ultra Rare (1-3), Rare (4-6), Uncommon (7-10), Common (11-15)
SERIES_CONFIG = {
    # Epic tier (White Border Error) - rarest of all, no B variants
    'wb': {
        'a_weight': 0.25,
        'b_weight': 0,  # No B variants exist
        'craft_cost': 30,
        'start': 1,
        'end': 80,
        'display_name': 'White Border Error',
        'no_b_variant': True
    },
    # Legendary tier (Flashback Series) - rarer than Ultra Rare
    'fb1': {
        'a_weight': 0.5,
        'b_weight': 0.01,
        'craft_cost': 25,
        'start': 1,
        'end': 80,
        'display_name': 'Flashback 1'
    },
    'fb2': {
        'a_weight': 0.5,
        'b_weight': 0.01,
        'craft_cost': 25,
        'start': 1,
        'end': 80,
        'display_name': 'Flashback 2'
    },
    'fb3': {
        'a_weight': 0.5,
        'b_weight': 0.01,
        'craft_cost': 25,
        'start': 1,
        'end': 80,
        'display_name': 'Flashback 3'
    },
    # Ultra Rare tier (Series 1-3)
    'os1': {
        'a_weight': 1.0,
        'b_weight': 0.02,
        'craft_cost': 20,
        'start': 1,
        'end': 41
    },
    'os2': {
        'a_weight': 1.5,
        'b_weight': 0.03,
        'craft_cost': 18,
        'start': 42,
        'end': 83
    },
    'os3': {
        'a_weight': 2.0,
        'b_weight': 0.04,
        'craft_cost': 16,
        'start': 84,
        'end': 124
    },
    # Rare tier (Series 4-6)
    'os4': {
        'a_weight': 3.0,
        'b_weight': 0.06,
        'craft_cost': 14,
        'start': 125,
        'end': 166
    },
    'os5': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 167,
        'end': 206
    },
    'os6': {
        'a_weight': 5.0,
        'b_weight': 0.10,
        'craft_cost': 10,
        'start': 207,
        'end': 250
    },
    # Uncommon tier (Series 7-10)
    'os7': {
        'a_weight': 6.0,
        'b_weight': 0.15,
        'craft_cost': 8,
        'start': 251,
        'end': 292
    },
    'os8': {
        'a_weight': 7.0,
        'b_weight': 0.20,
        'craft_cost': 7,
        'start': 293,
        'end': 334
    },
    'os9': {
        'a_weight': 8.0,
        'b_weight': 0.25,
        'craft_cost': 6,
        'start': 335,
        'end': 378
    },
    'os10': {
        'a_weight': 9.0,
        'b_weight': 0.30,
        'craft_cost': 5,
        'start': 379,
        'end': 417
    },
    # Common tier (Series 11-15)
    'os11': {
        'a_weight': 10.0,
        'b_weight': 0.40,
        'craft_cost': 5,
        'start': 418,
        'end': 459
    },
    'os12': {
        'a_weight': 11.0,
        'b_weight': 0.50,
        'craft_cost': 5,
        'start': 460,
        'end': 500
    },
    'os13': {
        'a_weight': 12.0,
        'b_weight': 0.60,
        'craft_cost': 5,
        'start': 501,
        'end': 540
    },
    'os14': {
        'a_weight': 13.0,
        'b_weight': 0.70,
        'craft_cost': 5,
        'start': 541,
        'end': 580
    },
    'os15': {
        'a_weight': 14.0,
        'b_weight': 0.80,
        'craft_cost': 5,
        'start': 581,
        'end': 620
    },
    # Prime Slime TV Series - Rare tier
    'tv_streaming': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 5,
        'display_name': 'Streaming TV'
    },
    'tv_syndicated': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 8,
        'display_name': 'Syndicated TV'
    },
    'tv_scifi': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 10,
        'display_name': 'Sci-Fi TV'
    },
    'tv_reboot': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 8,
        'display_name': 'Reboot TV'
    },
    'tv_reality': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 12,
        'display_name': 'Reality TV'
    },
    'tv_news': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 6,
        'display_name': 'News TV'
    },
    'tv_latenight': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 4,
        'display_name': 'Late Night TV'
    },
    'tv_horror': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 8,
        'display_name': 'Horror TV'
    },
    'tv_gameshow': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 5,
        'display_name': 'Game Show TV'
    },
    'tv_food': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 8,
        'display_name': 'Food TV'
    },
    'tv_drama': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 5,
        'display_name': 'Drama TV'
    },
    'tv_daytime': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 5,
        'display_name': 'Daytime TV'
    },
    'tv_crime': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 6,
        'display_name': 'Crime TV'
    },
    'tv_comedy': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 5,
        'display_name': 'Comedy TV'
    },
    'tv_comicbook': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 8,
        'display_name': 'Comic Book TV'
    },
    'tv_classicrerun': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 10,
        'display_name': 'Classic Rerun TV'
    },
    'tv_cartoon': {
        'a_weight': 4.0,
        'b_weight': 0.08,
        'craft_cost': 12,
        'start': 1,
        'end': 7,
        'display_name': 'Cartoon TV'
    },
    'tv_bomb': {
        'a_weight': 3.0,  # Slightly rarer
        'b_weight': 0.06,
        'craft_cost': 14,
        'start': 1,
        'end': 2,
        'display_name': 'Adam Bomb TV'
    }
}

# Calculate total weights for normalization
TOTAL_A_WEIGHT = sum(cfg['a_weight'] * (cfg['end'] - cfg['start'] + 1) for cfg in SERIES_CONFIG.values())
TOTAL_B_WEIGHT = sum(cfg['b_weight'] * (cfg['end'] - cfg['start'] + 1) for cfg in SERIES_CONFIG.values())
TOTAL_WEIGHT = TOTAL_A_WEIGHT + TOTAL_B_WEIGHT

async def load_cards_to_db(images_base_path: str):
    """Scan image folders and load cards into database."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cards_added = 0

        for series, config in SERIES_CONFIG.items():
            folder_name = f"{series}_images"
            folder_path = os.path.join(images_base_path, folder_name)

            if not os.path.exists(folder_path):
                print(f"Warning: Folder {folder_path} not found")
                continue

            for num in range(config['start'], config['end'] + 1):
                for variant in ['a', 'b']:
                    filename = f"{series}_{num}{variant}.jpg"
                    filepath = os.path.join(folder_path, filename)

                    if os.path.exists(filepath):
                        weight = config['a_weight'] if variant == 'a' else config['b_weight']
                        craft_cost = config['craft_cost'] if variant == 'b' else 0

                        try:
                            await db.execute('''
                                INSERT OR IGNORE INTO cards (series, number, variant, filename, rarity_weight, craft_cost)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (series, num, variant, filename, weight, craft_cost))
                            cards_added += 1
                        except Exception as e:
                            print(f"Error adding card {filename}: {e}")

        await db.commit()
        print(f"Loaded {cards_added} cards into database")
        return cards_added


def is_tv_series(series: str) -> bool:
    """Check if a series is a TV series."""
    return series.startswith('tv_')


def is_flashback_series(series: str) -> bool:
    """Check if a series is a Flashback series (Legendary tier)."""
    return series.startswith('fb')


def is_white_border_series(series: str) -> bool:
    """Check if a series is White Border Error (Epic tier)."""
    return series == 'wb'

async def get_random_card():
    """Get a random card based on rarity weights."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Get all cards with weights
        cursor = await db.execute('SELECT * FROM cards')
        cards = [dict(row) for row in await cursor.fetchall()]

        if not cards:
            return None

        # Weighted random selection
        total = sum(card['rarity_weight'] for card in cards)
        r = random.uniform(0, total)
        cumulative = 0

        for card in cards:
            cumulative += card['rarity_weight']
            if r <= cumulative:
                return card

        return cards[-1]  # Fallback

async def get_random_cards(count: int):
    """Get multiple random cards for a pack."""
    cards = []
    for _ in range(count):
        card = await get_random_card()
        if card:
            cards.append(card)
    return cards

def find_card_by_name(name: str):
    """Find a card's series and number by its character name."""
    name_lower = name.lower().strip()

    for series, numbers in CARD_NAMES.items():
        for number, variants in numbers.items():
            if variants.get('a', '').lower() == name_lower:
                return series, int(number), 'a'
            if variants.get('b', '').lower() == name_lower:
                return series, int(number), 'b'

    # Try partial match
    for series, numbers in CARD_NAMES.items():
        for number, variants in numbers.items():
            if name_lower in variants.get('a', '').lower():
                return series, int(number), 'a'
            if name_lower in variants.get('b', '').lower():
                return series, int(number), 'b'

    return None, None, None

async def get_random_card_by_variant(variant: str):
    """Get a random card of a specific variant (a or b), weighted by rarity."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Get all cards of this variant
        cursor = await db.execute('SELECT * FROM cards WHERE variant = ?', (variant,))
        cards = [dict(row) for row in await cursor.fetchall()]

        if not cards:
            return None

        # Weighted random selection
        total = sum(card['rarity_weight'] for card in cards)
        r = random.uniform(0, total)
        cumulative = 0

        for card in cards:
            cumulative += card['rarity_weight']
            if r <= cumulative:
                return card

        return cards[-1]  # Fallback

def get_card_display_name(card: dict) -> str:
    """Get a display name for a card including the character name."""
    series = card['series']
    number = str(card['number'])
    variant = card['variant']

    series_upper = series.upper()
    variant_upper = variant.upper()
    card_id = f"{series_upper}-{number}{variant_upper}"

    # Look up the character name
    if series in CARD_NAMES and number in CARD_NAMES[series]:
        name = CARD_NAMES[series][number].get(variant, '')
        if name:
            return f"{name} ({card_id})"

    return card_id

def get_card_rarity_name(card: dict) -> str:
    """Get rarity tier name for a card, including the series."""
    series = card['series']
    variant = card['variant']

    # Handle White Border Error (Epic tier)
    if is_white_border_series(series):
        config = SERIES_CONFIG.get(series, {})
        display_name = config.get('display_name', 'White Border Error')
        return f"EPIC ({display_name})"

    # Handle Flashback series (Legendary tier)
    if is_flashback_series(series):
        config = SERIES_CONFIG.get(series, {})
        display_name = config.get('display_name', series.upper())
        series_label = f"{display_name} Variant" if variant == 'b' else display_name
        return f"LEGENDARY ({series_label})"

    # Handle TV series
    if is_tv_series(series):
        config = SERIES_CONFIG.get(series, {})
        display_name = config.get('display_name', series.replace('tv_', '').title())
        series_label = f"{display_name} Variant" if variant == 'b' else display_name
        return f"Rare ({series_label})"

    # Determine tier based on series
    # Ultra Rare: 1-3, Rare: 4-6, Uncommon: 7-10, Common: 11-15
    series_num = int(series.replace('os', ''))
    series_label = f"Series {series_num} Variant" if variant == 'b' else f"Series {series_num}"

    if series_num <= 3:
        return f"Ultra Rare ({series_label})"
    elif series_num <= 6:
        return f"Rare ({series_label})"
    elif series_num <= 10:
        return f"Uncommon ({series_label})"
    else:
        return f"Common ({series_label})"

def get_rarity_color(card: dict) -> int:
    """Get embed color based on rarity."""
    series = card['series']
    variant = card['variant']

    # Handle White Border Error - Epic color (white/silver shimmer)
    if is_white_border_series(series):
        return 0xFFFFFF  # White - Epic (only A variants exist)

    # Handle Flashback series - Legendary colors (rainbow/prismatic effect)
    if is_flashback_series(series):
        if variant == 'b':
            return 0xFF00FF  # Magenta - Legendary B
        else:
            return 0x00FFFF  # Cyan - Legendary A

    # Handle TV series - use Rare colors
    if is_tv_series(series):
        if variant == 'b':
            return 0x9B59B6  # Purple - Rare B
        else:
            return 0xE67E22  # Orange - Rare

    series_num = int(series.replace('os', ''))

    if variant == 'b':
        if series_num <= 3:
            return 0xFFD700  # Gold - Ultra Rare B
        elif series_num <= 6:
            return 0x9B59B6  # Purple - Rare B
        elif series_num <= 10:
            return 0x3498DB  # Blue - Uncommon B
        else:
            return 0x1ABC9C  # Teal - Common B
    else:
        if series_num <= 3:
            return 0xE74C3C  # Red - Ultra Rare
        elif series_num <= 6:
            return 0xE67E22  # Orange - Rare
        elif series_num <= 10:
            return 0x2ECC71  # Green - Uncommon
        else:
            return 0x95A5A6  # Gray - Common

def get_craft_cost(series: str) -> int:
    """Get the craft cost for a series."""
    return SERIES_CONFIG.get(series, {}).get('craft_cost', 5)

async def get_card_image_path(card: dict, images_base_path: str) -> str:
    """Get the full path to a card's image."""
    folder_name = f"{card['series']}_images"
    return os.path.join(images_base_path, folder_name, card['filename'])
