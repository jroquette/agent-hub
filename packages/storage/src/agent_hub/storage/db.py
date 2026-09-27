"""SQLAlchemy Core metadata: the single place where tables are declared."""

from sqlalchemy import MetaData

# Empty on purpose: the baseline schema has no tables; the events table lands with the collector.
metadata = MetaData()
