"""Shared article scope for feeds, dashboards, trends and summaries."""
from sqlalchemy import or_, select

from ..models import Article, ArticleProfile, ProfileDashboard


def profile_scope(profile_ids):
    return or_(Article.profile_id.in_(profile_ids), Article.id.in_(
        select(ArticleProfile.article_id).where(ArticleProfile.profile_id.in_(profile_ids))))


def dashboard_scope(set_id):
    links = select(ProfileDashboard.profile_id).where(ProfileDashboard.set_id == set_id)
    return or_(~select(ProfileDashboard.profile_id).where(ProfileDashboard.set_id == set_id).exists(),
               profile_scope(links))
