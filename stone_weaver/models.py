from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Chapter(Base):
    """一个回目。version 区分文本来源（gongban 公版 / guiyou 癸酉本）。"""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    num: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text)

    events: Mapped[list[Event]] = relationship(back_populates="chapter", cascade="all, delete-orphan")

    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.content.split("\n") if p.strip()]


class Character(Base):
    """人物对象：姓名、别名、归属、首次出场回。"""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    gender: Mapped[str | None] = mapped_column(String(10))
    clan: Mapped[str | None] = mapped_column(String(20))  # 贾/王/史/薛 ...
    house: Mapped[str | None] = mapped_column(String(50))  # 荣国府/宁国府/大观园 ...
    first_chapter: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="story")  # story=故事人物 / reference=典故引用
    source_version: Mapped[str | None] = mapped_column(String(30))  # 底本（gongban_rb=draft / unified=正式）
    summary: Mapped[str | None] = mapped_column(Text)


class Relationship(Base):
    """人物间关系（有向），如 贾宝玉 -(夫妻)-> 林黛玉。"""

    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))  # 夫妻/父子/主仆 ...
    chapter: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(String(300))

    source: Mapped[Character] = relationship(foreign_keys=[source_id])
    target: Mapped[Character] = relationship(foreign_keys=[target_id])


class Location(Base):
    """地点：园内建筑 / 府邸 / 外部空间。"""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    kind: Mapped[str | None] = mapped_column(String(20))  # 府邸/园景/寺庙/街市 ...
    description: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    """情节事件：挂靠在某一回下，参与者为人物，地点为位置。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text)
    participants: Mapped[list] = mapped_column(JSON, default=list)  # character ids
    location: Mapped[str | None] = mapped_column(String(100))

    chapter: Mapped[Chapter] = relationship(back_populates="events")


class CharacterState(Base):
    """人物动态状态快照：某回时点该人物的存活/位置/特殊状态。

    叙事引擎的最小单元——生成器输入、校验器依据、80→81 衔接的关键。
    只写入有变化的回（未变不重复写），查询取 chapter<=N 的最新一条。
    """

    __tablename__ = "character_states"
    __table_args__ = (UniqueConstraint("character_id", "chapter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[str | None] = mapped_column(String(100))  # 大观园/狱神庙/瓜洲/雪中…
    status: Mapped[str | None] = mapped_column(String(50))  # 出家/发配/病重/被掳/流落…
    note: Mapped[str | None] = mapped_column(String(300))  # 变更说明（来源事件）

    character: Mapped[Character] = relationship()


class EventEdge(Base):
    """情节图有向边：事件节点之间的因果/时序/冲突关系。"""

    __tablename__ = "event_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    to_event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # causal / temporal / conflict
    note: Mapped[str | None] = mapped_column(String(300))

    from_event: Mapped[Event] = relationship(foreign_keys=[from_event_id])
    to_event: Mapped[Event] = relationship(foreign_keys=[to_event_id])


class Arc(Base):
    """情节弧：高层目标序列（叙事引擎的剧本）。

    beats 为 JSON 数组：[{scene, goal, characters, constraints, expected_out}, ...]
    """

    __tablename__ = "arcs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20))  # guihui_v3 / custom ...
    beats: Mapped[list] = mapped_column(JSON, default=list)
    source_chapter_range: Mapped[str | None] = mapped_column(String(20))  # "81-108"


class GeneratedChapter(Base):
    """引擎产出回目：情节弧驱动的重建/续写结果。"""

    __tablename__ = "generated_chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    arc_id: Mapped[int | None] = mapped_column(ForeignKey("arcs.id"))
    num: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / reviewed
    review_note: Mapped[str | None] = mapped_column(Text)
