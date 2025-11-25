# Setting Up GitHub Repository

Follow these steps to add your GPK Dex Bot to GitHub.

## Prerequisites

- Git installed on your computer
- GitHub account created at https://github.com

## Step 1: Initialize Git Repository

Open terminal in your project directory and run:

```bash
cd /Users/brainphreak/garbagedex/gpkdex
git init
```

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Enter repository name: `gpkdex-bot` (or your preferred name)
3. Add description: "Discord bot for collecting and trading Garbage Pail Kids cards"
4. Choose **Public** or **Private**
5. **Do NOT** initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

## Step 3: Add Files to Git

```bash
# Add all files except those in .gitignore
git add .

# Create first commit
git commit -m "Initial commit: GPK Dex Discord bot with full documentation"
```

## Step 4: Connect to GitHub

Replace `YOUR_USERNAME` and `REPO_NAME` with your actual GitHub username and repository name:

```bash
# Add remote repository
git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Step 5: Verify Upload

1. Go to your GitHub repository URL
2. Verify all files are uploaded (except .env and other ignored files)
3. Check that README.md displays on the main page

## Important Notes

### Security

- **NEVER** commit your `.env` file with real credentials
- The `.gitignore` file prevents `.env` from being uploaded
- Always use `.env.example` for reference

### What Gets Uploaded

✅ Uploaded:
- bot.py
- database.py
- README.md
- CONTRIBUTING.md
- DATABASE.md
- .gitignore
- .env.example
- requirements.txt
- All card image directories

❌ NOT Uploaded (protected by .gitignore):
- .env (contains secrets)
- *.db (database files)
- __pycache__/ (Python cache)
- .DS_Store (Mac system files)

## Adding More Changes Later

After making changes to your code:

```bash
# Check what changed
git status

# Add changes
git add .

# Commit with message describing changes
git commit -m "Add new feature: X"

# Push to GitHub
git push
```

## Setting Up Repository Settings (Optional)

### Add Topics

In your GitHub repository:
1. Click the gear icon next to "About"
2. Add topics: `discord-bot`, `python`, `garbage-pail-kids`, `trading-cards`, `discord-py`

### Enable Issues

1. Go to Settings → Features
2. Check "Issues" to allow bug reports and feature requests

### Add Repository Description

Add this description in the About section:
```
A Discord bot for collecting and trading Garbage Pail Kids cards featuring multiple series, rarity tiers, puzzles, economy system, and player trading
```

## Collaborators

To add collaborators:
1. Go to Settings → Collaborators
2. Click "Add people"
3. Enter their GitHub username

## GitHub Actions (Optional)

You can set up automated testing using GitHub Actions. Create `.github/workflows/python-app.yml` for CI/CD.

## Need Help?

- GitHub Docs: https://docs.github.com
- Git Basics: https://git-scm.com/doc
- GitHub Desktop (GUI): https://desktop.github.com
