"""``/projects/{project}/knowledge/search`` and ``/projects/{project}/brain/backlinks``: the
project's hub searched over the AGH-391 index, and the documents linking to one of its notes
(AGH-393, D-search-route, D-backlinks-route). Each read syncs the hub's rows first; the only
write is that sync of rows derived from the checkout (AM-2)."""

from typing import Annotated

from fastapi import APIRouter, Query

from agent_hub.api.dependencies import KnowledgeReadsDep
from agent_hub.api.rfc9457 import InvalidParameterError
from agent_hub.api.routes.projects import NotePathParam, ProjectPath
from agent_hub.api.schemas import PROBLEM_RESPONSES
from agent_hub.core.knowledge.knowledge_index import KINDS, Kind
from agent_hub.core.knowledge.knowledge_reads import KnowledgeSearch, NoteBacklinks
from agent_hub.core.knowledge.search_query import MAX_RESULTS, query_words

router = APIRouter(tags=["knowledge"], responses=PROBLEM_RESPONSES)

MAX_QUERY_CHARS = 500
NO_WORDS = "the query has no words"

QueryParam = Annotated[str, Query(min_length=1, max_length=MAX_QUERY_CHARS)]
KindsParam = Annotated[list[Kind] | None, Query(max_length=len(KINDS))]
ResultLimitParam = Annotated[int, Query(ge=1, le=MAX_RESULTS)]


@router.get("/projects/{project}/knowledge/search")
def search_project_knowledge(
    project: ProjectPath,
    reads: KnowledgeReadsDep,
    *,
    q: QueryParam,
    kind: KindsParam = None,
    limit: ResultLimitParam = MAX_RESULTS,
) -> KnowledgeSearch:
    """The hub's notes and repo docs holding every word of ``q``, best first, after the index
    is brought up to date with the checkout; ``q``'s words only, never search syntax."""
    if not query_words(q):
        raise InvalidParameterError(parameter="q", reason=NO_WORDS)
    return reads.search(project, query=q, kinds=tuple(kind or ()), limit=limit)


@router.get("/projects/{project}/brain/backlinks")
def get_brain_backlinks(
    project: ProjectPath, path: NotePathParam, reads: KnowledgeReadsDep
) -> NoteBacklinks:
    """The documents linking to the note at ``path`` under ``brain/``, by path, at most 100,
    with the full count; the note need not exist."""
    return reads.backlinks(project, path)
