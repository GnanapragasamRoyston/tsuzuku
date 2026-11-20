"""Tables catalog et mart, en LECTURE (créées par pipeline/src/tsuzuku_pipeline/db/*.sql).

Ces classes décrivent les colonnes que l'API lit ; elles ne servent jamais à créer les tables.
"""

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Media(Base):
    __tablename__ = "media"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    mal_id: Mapped[int | None] = mapped_column(Integer)
    anilist_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    title_alt: Mapped[str | None] = mapped_column(Text)
    synopsis: Mapped[str | None] = mapped_column(Text)
    episodes: Mapped[int | None] = mapped_column(Integer)
    chapters: Mapped[int | None] = mapped_column(Integer)
    airing_status: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str | None] = mapped_column(Text)
    duration_min: Mapped[float | None] = mapped_column(Float)
    start_year: Mapped[int | None] = mapped_column(Integer)
    creators: Mapped[list[str]] = mapped_column(ARRAY(Text))
    source: Mapped[str | None] = mapped_column(Text)
    age_rating: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    popularity: Mapped[int | None] = mapped_column(Integer)
    data_source: Mapped[str] = mapped_column(Text)


class Genre(Base):
    __tablename__ = "genre"
    __table_args__ = {"schema": "catalog"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class MediaGenre(Base):
    __tablename__ = "media_genre"
    __table_args__ = {"schema": "catalog"}

    media_id: Mapped[int] = mapped_column(ForeignKey("catalog.media.id"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(ForeignKey("catalog.genre.id"), primary_key=True)


class DropCurve(Base):
    __tablename__ = "drop_curve"
    __table_args__ = {"schema": "mart"}

    media_id: Mapped[int] = mapped_column(ForeignKey("catalog.media.id"), primary_key=True)
    episode: Mapped[int] = mapped_column(Integer, primary_key=True)
    nb_drops: Mapped[int] = mapped_column(Integer)
    cumulative_share: Mapped[float] = mapped_column(Float)


class CriticalEpisode(Base):
    __tablename__ = "critical_episode"
    __table_args__ = {"schema": "mart"}

    media_id: Mapped[int] = mapped_column(ForeignKey("catalog.media.id"), primary_key=True)
    critical_episode: Mapped[int] = mapped_column(Integer)
    critical_drop_share: Mapped[float] = mapped_column(Float)
    initial_drop_risk: Mapped[float | None] = mapped_column(Float)
    point_of_no_return: Mapped[int | None] = mapped_column(Integer)
    nb_drops: Mapped[int] = mapped_column(Integer)
    nb_completed: Mapped[int] = mapped_column(Integer)
    drop_rate: Mapped[float] = mapped_column(Float)
