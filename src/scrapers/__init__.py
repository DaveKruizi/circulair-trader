from .marktplaats_lego import scrape_all_sets as scrape_marktplaats_lego
from .vinted_lego import scrape_all_sets as scrape_vinted_lego

__all__ = [
    "scrape_marktplaats_lego",
    "scrape_vinted_lego",
]
