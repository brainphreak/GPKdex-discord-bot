"""Puzzle system for GPK Dex."""

import os
import aiosqlite
from database import DATABASE_PATH

# Puzzle configuration
# Rarity: lower weight = rarer (like cards)
# Piece order maps original card numbers to piece positions 1-18 (top-left to bottom-right, 6 columns x 3 rows)
# piece_labels contains the display labels for each piece (e.g., "55LL", "122B")
PUZZLE_CONFIG = {
    1: {
        'name': 'Leaky Lindsay / Messy Tessie',
        'description': 'Series 2 puzzle featuring Leaky Lindsay and Messy Tessie',
        'rarity_weight': 1.0,  # Rarest
        'pieces': 18,
        'folder': 'puzzle1',
        'preview_filename': 'puzzle1_preview.jpg',
        'piece_order': [55, 66, 75, 56, 67, 76, 57, 68, 77, 58, 69, 78, 59, 70, 79, 60, 71, 80],
        'piece_labels': ['55LL', '66LL', '75LL', '56LL', '67LL', '76LL', '57LL', '68LL', '77LL', '58LL', '69LL', '78LL', '59LL', '70LL', '79LL', '60LL', '71LL', '80LL']
    },
    2: {
        'name': 'Live Mike / Jolted Joel',
        'description': 'Series 2 puzzle featuring Live Mike and Jolted Joel',
        'rarity_weight': 2.0,
        'pieces': 18,
        'folder': 'puzzle2',
        'preview_filename': 'puzzle2_preview.jpg',
        'piece_order': [55, 66, 75, 56, 67, 76, 57, 68, 77, 58, 69, 78, 59, 70, 79, 60, 71, 80],
        'piece_labels': ['55LM', '66LM', '75LM', '56LM', '67LM', '76LM', '57LM', '68LM', '77LM', '58LM', '69LM', '78LM', '59LM', '70LM', '79LM', '60LM', '71LM', '80LM']
    },
    3: {
        'name': 'U.S. Arnie / Snooty Sam',
        'description': 'Series 3 puzzle featuring U.S. Arnie and Snooty Sam',
        'rarity_weight': 3.0,
        'pieces': 18,
        'folder': 'puzzle3',
        'preview_filename': 'puzzle3_preview.jpg',
        'piece_order': [94, 92, 85, 89, 88, 93, 90, 121, 122, 95, 101, 123, 112, 103, 115, 114, 124, 107],
        'piece_labels': ['94A', '92A', '85A', '89A', '88A', '93A', '90A', '121A', '122A', '95A', '101A', '123A', '112A', '103A', '115A', '114A', '124A', '107A']
    },
    4: {
        'name': 'Mugged Marcus / Kayo\'d Cody',
        'description': 'Series 3 puzzle featuring Mugged Marcus and Kayo\'d Cody',
        'rarity_weight': 4.0,  # Most common
        'pieces': 18,
        'folder': 'puzzle4',
        'preview_filename': 'puzzle4_preview.jpg',
        'piece_order': [94, 92, 85, 89, 88, 93, 90, 121, 122, 95, 101, 123, 112, 103, 115, 114, 124, 107],
        'piece_labels': ['94B', '92B', '85B', '89B', '88B', '93B', '90B', '121B', '122B', '95B', '101B', '123B', '112B', '103B', '115B', '114B', '124B', '107B']
    }
}


def get_piece_label(puzzle_id: int, piece_number: int) -> str:
    """Get the display label for a puzzle piece (e.g., '122B' instead of '#9')."""
    config = PUZZLE_CONFIG.get(puzzle_id)
    if config and 'piece_labels' in config:
        # piece_number is 1-indexed, array is 0-indexed
        if 1 <= piece_number <= len(config['piece_labels']):
            return config['piece_labels'][piece_number - 1]
    return f"#{piece_number}"

# XP rewards for puzzle activities
PUZZLE_PIECE_XP = 5  # XP for getting a puzzle piece
PUZZLE_COMPLETE_XP = 200  # XP for completing a puzzle


async def load_puzzles_to_db(images_base_path: str):
    """Load puzzle definitions and pieces into database."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        puzzles_added = 0
        pieces_added = 0

        for puzzle_num, config in PUZZLE_CONFIG.items():
            folder_name = f"{config['folder']}_images"
            folder_path = os.path.join(images_base_path, folder_name)

            # Insert puzzle
            complete_filename = f"{config['folder']}_complete.jpg"

            try:
                await db.execute('''
                    INSERT OR IGNORE INTO puzzles (name, description, rarity_weight, pieces_required, complete_filename)
                    VALUES (?, ?, ?, ?, ?)
                ''', (config['name'], config['description'], config['rarity_weight'], config['pieces'], complete_filename))
                puzzles_added += 1
            except Exception as e:
                print(f"Error adding puzzle {config['name']}: {e}")
                continue

            # Get the puzzle_id
            cursor = await db.execute('SELECT puzzle_id FROM puzzles WHERE name = ?', (config['name'],))
            row = await cursor.fetchone()
            if not row:
                continue
            puzzle_id = row[0]

            # Insert pieces
            for piece_num in range(1, config['pieces'] + 1):
                filename = f"{config['folder']}_piece{piece_num}.jpg"

                try:
                    await db.execute('''
                        INSERT OR IGNORE INTO puzzle_pieces (puzzle_id, piece_number, filename)
                        VALUES (?, ?, ?)
                    ''', (puzzle_id, piece_num, filename))
                    pieces_added += 1
                except Exception as e:
                    print(f"Error adding piece {filename}: {e}")

        await db.commit()
        print(f"Loaded {puzzles_added} puzzles with {pieces_added} pieces into database")
        return puzzles_added, pieces_added


def get_puzzle_rarity_name(puzzle: dict) -> str:
    """Get rarity tier name for a puzzle."""
    weight = puzzle['rarity_weight']

    if weight <= 1.0:
        return "ULTRA RARE"
    elif weight <= 2.0:
        return "Rare"
    elif weight <= 3.0:
        return "Uncommon"
    else:
        return "Common"


def get_puzzle_rarity_color(puzzle: dict) -> int:
    """Get embed color based on puzzle rarity."""
    weight = puzzle['rarity_weight']

    if weight <= 1.0:
        return 0xFFD700  # Gold - Ultra Rare
    elif weight <= 2.0:
        return 0x9B59B6  # Purple - Rare
    elif weight <= 3.0:
        return 0x3498DB  # Blue - Uncommon
    else:
        return 0x2ECC71  # Green - Common


async def get_puzzle_image_path(puzzle: dict, images_base_path: str) -> str:
    """Get the full path to a completed puzzle's image."""
    # Determine folder from puzzle name or ID
    puzzle_id = puzzle['puzzle_id']
    folder_name = f"puzzle{puzzle_id}_images"
    return os.path.join(images_base_path, folder_name, puzzle['complete_filename'])


async def get_piece_image_path(piece: dict, puzzle: dict, images_base_path: str) -> str:
    """Get the full path to a puzzle piece's image."""
    puzzle_id = puzzle['puzzle_id']
    folder_name = f"puzzle{puzzle_id}_images"
    return os.path.join(images_base_path, folder_name, piece['filename'])


def get_puzzle_preview_path(puzzle_id: int, images_base_path: str) -> str:
    """Get the full path to a puzzle's preview image (shows numbered grid)."""
    config = PUZZLE_CONFIG.get(puzzle_id)
    if not config or not config.get('preview_filename'):
        return None
    folder_name = f"{config['folder']}_images"
    return os.path.join(images_base_path, folder_name, config['preview_filename'])
