"""Recognize official Russian TV age-rating suffixes without matching movie titles.

A plus sign inside a title (e.g. «2+1», «16+1») is not an age rating.
Unparenthesized ratings must be separated from the title by whitespace;
parenthesized ratings can follow it directly.
"""
import re

# Supported ratings: 0+, 6+, 12+, 16+, 18+.
# Keep anchored to the end so arithmetic-looking names remain untouched.
AGE_RE = re.compile(
    r'(?:\s*\((?:0|6|12|16|18)\+\)|\s+(?:0|6|12|16|18)\+)\s*$'
)
