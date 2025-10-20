from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import redis.asyncio as aioredis
import json
from typing import Any, Dict, List
# from conversation import EarningConversation
from conversation_streaming import EarningConversation
from retrieval import QuadrantRetrieval
from redis_conversation_manager import AsyncConversationStore
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
ec = EarningConversation()
redis_store = AsyncConversationStore()

@app.post("/chat/")
async def chat(user_id: str, user_query: str):
    async def event_generator():
        async for chunk in ec.retrive_context_for_multiple_queries_stream(user_id, user_query, redis_store):
            yield chunk

    return StreamingResponse(event_generator(), media_type="text/event-stream")

