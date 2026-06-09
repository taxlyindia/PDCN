import re
import uuid


def slugify(text: str) -> str:
    """Convert company name to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text


def make_unique_slug(company_name: str, db) -> str:
    """Generate a unique slug for a tenant."""
    from app.models import Tenant
    base = slugify(company_name)[:80]
    slug = base
    counter = 1
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug
