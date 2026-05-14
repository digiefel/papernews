"""HN-style ranking. Computed in Python — SQLite's ORM has no clean power operator."""

GRAVITY = 1.8


def hot_score(vote_count, created, now):
    age_hours = (now - created).total_seconds() / 3600
    return (vote_count + 1) / ((age_hours + 2) ** GRAVITY)
