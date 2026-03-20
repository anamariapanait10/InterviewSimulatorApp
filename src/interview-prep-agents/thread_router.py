import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agent_framework import AgentSession

logger = logging.getLogger("interview-prep-agents")


class _ThreadAgentState:
    def __init__(self, agent: Any):
        self.agent = agent
        self.lock = asyncio.Lock()


class ThreadScopedAgentRouter:
    """Route runs to per-thread workflow agents for multi-user concurrency."""

    def __init__(self, agent_factory: Callable[[], Awaitable[Any]]):
        self.id: str = f"thread-router-{uuid.uuid4().hex[:8]}"
        self.name: str | None = "Interview Coach Router"
        self.description: str | None = "Routes AG-UI runs to thread-scoped workflow agents"
        self._agent_factory = agent_factory
        self._agents_by_thread: dict[str, _ThreadAgentState] = {}
        self._registry_lock = asyncio.Lock()

    async def _get_or_create_thread_agent(self, thread_id: str) -> _ThreadAgentState:
        existing = self._agents_by_thread.get(thread_id)
        if existing is not None:
            return existing

        async with self._registry_lock:
            existing = self._agents_by_thread.get(thread_id)
            if existing is not None:
                return existing

            logger.debug("creating workflow for thread_id=%s", thread_id)
            agent = await self._agent_factory()
            state = _ThreadAgentState(agent)
            self._agents_by_thread[thread_id] = state
            return state

    async def _refresh_thread_agent(self, thread_id: str) -> _ThreadAgentState:
        async with self._registry_lock:
            logger.warning("rebuilding workflow for thread_id=%s", thread_id)
            agent = await self._agent_factory()
            state = _ThreadAgentState(agent)
            self._agents_by_thread[thread_id] = state
            return state

    @staticmethod
    def _resolve_thread_id(session: AgentSession | None) -> str:
        if session is not None:
            metadata = getattr(session, "metadata", None)
            if isinstance(metadata, dict):
                value = metadata.get("ag_ui_thread_id")
                if isinstance(value, str) and value:
                    return value

            service_session_id = getattr(session, "service_session_id", None)
            if isinstance(service_session_id, str) and service_session_id:
                return service_session_id

        return "default"

    async def _run_stream_for_thread(
        self,
        messages: Any,
        *,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        thread_id = self._resolve_thread_id(session)
        thread_state = await self._get_or_create_thread_agent(thread_id)

        async with thread_state.lock:
            pending = getattr(thread_state.agent, "pending_requests", None)
            if isinstance(pending, dict) and pending:
                logger.debug("clearing %s pending requests for thread_id=%s", len(pending), thread_id)
                pending.clear()

            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                try:
                    stream = thread_state.agent.run(messages, stream=True, session=session, **kwargs)
                    async for update in stream:
                        yield update
                    return
                except RuntimeError as exc:
                    if "Workflow is already running" not in str(exc) or attempt == max_attempts:
                        if "Workflow is already running" not in str(exc):
                            raise
                        break

                    delay_s = 0.2
                    logger.warning(
                        "workflow finalizing for thread_id=%s; retrying in %.2fs (attempt %s/%s)",
                        thread_id,
                        delay_s,
                        attempt,
                        max_attempts,
                    )
                    await asyncio.sleep(delay_s)

            # Last resort: replace stuck workflow instance for this thread.
            # Context is preserved by backend history replay.
            thread_state = await self._refresh_thread_agent(thread_id)
            stream = thread_state.agent.run(messages, stream=True, session=session, **kwargs)
            async for update in stream:
                yield update

    async def _run_non_stream_for_thread(
        self,
        messages: Any,
        *,
        session: AgentSession | None = None,
        **kwargs: Any,
    ) -> Any:
        thread_id = self._resolve_thread_id(session)
        thread_state = await self._get_or_create_thread_agent(thread_id)

        async with thread_state.lock:
            pending = getattr(thread_state.agent, "pending_requests", None)
            if isinstance(pending, dict) and pending:
                logger.debug("clearing %s pending requests for thread_id=%s", len(pending), thread_id)
                pending.clear()

            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                try:
                    return await thread_state.agent.run(messages, stream=False, session=session, **kwargs)
                except RuntimeError as exc:
                    if "Workflow is already running" not in str(exc) or attempt == max_attempts:
                        if "Workflow is already running" not in str(exc):
                            raise
                        break

                    delay_s = 0.2
                    logger.warning(
                        "workflow finalizing for thread_id=%s (non-stream); retrying in %.2fs (attempt %s/%s)",
                        thread_id,
                        delay_s,
                        attempt,
                        max_attempts,
                    )
                    await asyncio.sleep(delay_s)

            thread_state = await self._refresh_thread_agent(thread_id)
            return await thread_state.agent.run(messages, stream=False, session=session, **kwargs)

    def run(self, messages: Any = None, *, stream: bool = False, session: AgentSession | None = None, **kwargs: Any) -> Any:
        if stream:
            return self._run_stream_for_thread(messages, session=session, **kwargs)
        return self._run_non_stream_for_thread(messages, session=session, **kwargs)

    def create_session(self, **kwargs: Any) -> AgentSession:
        return AgentSession(**kwargs)

    def get_session(self, *, service_session_id: str, **kwargs: Any) -> AgentSession:
        return AgentSession(service_session_id=service_session_id, **kwargs)
