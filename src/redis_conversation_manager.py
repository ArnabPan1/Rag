import redis.asyncio as aioredis
import asyncio
import json

class AsyncConversationStore:
    def __init__(self, host="localhost", port=6379, db=0, limit=10):
        self.redis = aioredis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.limit = limit

    async def load(self, user_id: str):
        data = await self.redis.get(user_id)
        return json.loads(data) if data else []

    async def save(self, user_id: str, conversation):
        if len(conversation) > self.limit:
            conversation = conversation[-self.limit:]
        await self.redis.set(user_id, json.dumps(conversation))

    async def append(self, user_id: str, role: str, content: str):
        convo = await self.load(user_id)
        convo.append({"role": role, "content": content})
        await self.save(user_id, convo)

    async def delete(self, user_id: str):
        await self.redis.delete(user_id)

# # --- Example async usage ---
# async def main():
#     store = AsyncConversationStore()
#     user_id = "user_123"
    
#     await store.append(user_id, "user", "Hello async!")
#     await store.append(user_id, "assistant", "Hi, this is async Redis!")
    
#     convo = await store.load(user_id)
#     print(convo)

# asyncio.run(main())
