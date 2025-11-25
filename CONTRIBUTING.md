# Contributing to GPK Dex Bot

Thank you for considering contributing to the GPK Dex Bot! This document provides guidelines for contributing to the project.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected behavior vs actual behavior
- Screenshots if applicable
- Your environment (OS, Python version, etc.)

### Suggesting Features

Feature suggestions are welcome! Please open an issue with:
- A clear description of the feature
- Why this feature would be useful
- Any implementation ideas you might have

### Code Contributions

1. **Fork the repository** and create a new branch for your feature or bugfix
2. **Write clear, documented code** following the existing code style
3. **Test your changes** thoroughly
4. **Submit a pull request** with a clear description of your changes

### Code Style Guidelines

- Use meaningful variable and function names
- Add comments for complex logic
- Follow PEP 8 style guidelines for Python
- Keep functions focused on a single responsibility
- Use async/await properly for Discord.py commands

### Testing

Before submitting a pull request:
- Test all commands that might be affected by your changes
- Verify database operations work correctly
- Check for any error messages or warnings
- Test with multiple users if the change affects trading or interactions

### Database Changes

If your contribution modifies the database schema:
- Document the changes clearly
- Provide migration instructions if needed
- Test with existing data to ensure backward compatibility

### Adding New Cards or Series

When adding new card series:
1. Add card images to appropriate directory (`{series}_images/`)
2. Update database initialization in `database.py`
3. Update rarity multipliers in `bot.py` if needed
4. Update documentation in README.md

## Questions?

If you have questions about contributing, feel free to open an issue or reach out to the maintainers.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members
