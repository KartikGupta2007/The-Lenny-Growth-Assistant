"""Content-generation skills, each grounded in retrieved evidence."""

from app.skills.html_page import generate_html_page
from app.skills.ship30 import generate_ship30_essay

__all__ = ["generate_html_page", "generate_ship30_essay"]
