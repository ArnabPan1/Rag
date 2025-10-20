from openai import AsyncOpenAI
from prompts import a_gen_system_prompt, a_gen_user_prompt
from prompts import q_breakdown_system_prompt, q_breakdown_user_prompt
from retrieval import QuadrantRetrieval
from typing import AsyncGenerator
import asyncio, json
import yaml
import pandas as pd
from utils import parse_reasoning_and_output,parse_reasoning_and_queries
from redis_conversation_manager import AsyncConversationStore
from retrieval import QuadrantRetrieval

class EarningConversation:
    def __init__(self):
        """
        Initialize the EarningConversation class.
        """
        config = yaml.safe_load(open("config.yaml"))
        self.openai_config = config['openai']
        self.qd = QuadrantRetrieval()
        
    
    async def get_client(self):
        """
        Initialize the OpenAI client.
        """
        self.vllm_api_url = self.openai_config['vllm_api_url']
        self.api_key = self.openai_config['api_key']
        self.model = self.openai_config['model']
        client = AsyncOpenAI(
            base_url=self.vllm_api_url,  # or your ngrok URL
            api_key=self.api_key
        )
        return client

    async def llm_call(self, client, conversation):
        """
        Make a call to the OpenAI API.
        """
        self.max_tokens = self.openai_config['max_tokens']
        self.temperature = self.openai_config['temperature']
        self.top_p = self.openai_config['top_p']
        self.frequency_penalty = self.openai_config['frequency_penalty']
        self.presence_penalty = self.openai_config['presence_penalty']
        response = await client.chat.completions.create(
            model=self.model,
            messages=conversation,
            # tools=tools,
            # tool_choice="auto",
            max_tokens = self.max_tokens,
            temperature = self.temperature,
            top_p = self.top_p,
            frequency_penalty = self.frequency_penalty,
            presence_penalty = self.presence_penalty
        )
        return response
    
    async def stream_llm_call(self, client, conversation):
        """
        Streams model output token-by-token.
        Returns the full accumulated message once complete.
        """
        self.max_tokens = self.openai_config['max_tokens']
        self.temperature = self.openai_config['temperature']
        self.top_p = self.openai_config['top_p']
        self.frequency_penalty = self.openai_config['frequency_penalty']
        self.presence_penalty = self.openai_config['presence_penalty']

        response_text = ""
        stream = await client.chat.completions.create(
            model=self.model,
            messages=conversation,
            stream=True,  # enable streaming
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            frequency_penalty=self.frequency_penalty,
            presence_penalty=self.presence_penalty
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta
            # print("delta----",delta)
            if delta and delta.content:
                token = delta.content
                response_text += token
                yield token  # stream each token live

        # return response_text
    
    async def create_conversation_with_history(self, user_id, user_query, retrieved_text_chunks, redis_store):
        """
        Create a conversation with history.
        """
        history = await redis_store.load(user_id)
        #print("history---------",history)
        messages = [{"role": "system", "content": a_gen_system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": a_gen_user_prompt.format(user_query=user_query, retrieved_text_chunks=retrieved_text_chunks)})
        return messages
    
    async def start_process_with_history(self, user_id, user_query, retrieved_text_chunks, redis_store):
        """
        Start the conversation with history.
        """
        client = await self.get_client()
        conversation = await self.create_conversation_with_history(user_id, user_query, retrieved_text_chunks, redis_store)
        # print("conversation---------",conversation)
        response = await self.llm_call(client, conversation)
        reasoning, answer = await self.process_response(response.choices[0].message.content)
        await redis_store.append(user_id, "user", user_query)
        await redis_store.append(user_id, "assistant", answer)
        return answer
    
    async def start_process_with_history_stream(self, user_id, user_query, retrieved_text_chunks, redis_store):
        """
        Creates conversation with history and yields streamed LLM output.
        """
        client = await self.get_client()
        conversation = await self.create_conversation_with_history(user_id, user_query, retrieved_text_chunks, redis_store)

        # print("conversation---------", conversation)

        response_text = ""
        async for token in self.stream_llm_call(client, conversation):
            response_text += token
            yield token  # yield as stream to caller

        # once complete, parse and store
        print("final response_text---------",response_text)
        # reasoning, answer = await self.process_response(response_text)
        # print("reasoning---------",reasoning)
        # print("answer---------",answer)
        await redis_store.append(user_id, "user", user_query)
        await redis_store.append(user_id, "assistant", response_text)

        # return answer  # returned only at the end
    
    async def process_response(self, response):
        reasoning, answer = parse_reasoning_and_output(response)
        return reasoning, answer

    async def process_q_breakdown_response(self, user_query):
        reasoning, queries = parse_reasoning_and_queries(user_query)
        return queries
    
    async def retrive_context_for_multiple_queries_stream(
        self, user_id: str, user_query: str, redis_store
    ) -> AsyncGenerator[str, None]:
        """
        Async generator that:
         1) runs query breakdown LLM (and saves q_breakdown history in redis)
         2) runs retrieval for top 3 expanded queries in parallel
         3) yields metadata_list (one event)
         4) streams assistant tokens from start_process_with_history_stream as token events
         5) yields final done event with parsed answer and metadata_list again for finality
        """
        # 1) Generate query breakdown (same as before)
        client = await self.get_client()
        redis_id = f"{user_id}_q_breakdown"
        history = await redis_store.load(redis_id)

        messages = [{"role": "system", "content": q_breakdown_system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": q_breakdown_user_prompt.format(user_query=user_query)})

        response = await self.llm_call(client, messages)
        breakdown_content = response.choices[0].message.content
        queries = await self.process_q_breakdown_response(breakdown_content)
        queries = queries[0:3]  # keep first 3

        await redis_store.append(redis_id, "user", user_query)
        await redis_store.append(redis_id, "assistant", breakdown_content)

        tasks = [self.qd.process_search(query, user_id) for query in queries]
        results = await asyncio.gather(*tasks)  # results: list of lists (or dfs) depending on qd

        all_df_list = [pd.DataFrame(i) for i in results if i]
        if all_df_list:
            df = pd.concat(all_df_list, ignore_index=True)
        else:
            df = pd.DataFrame(columns=["score", "payload"])

        if "score" in df.columns and len(df) > 0:
            top_5 = df.sort_values("score", ascending=False).head(5)
        else:
            top_5 = df.head(5)

        metadata_list = []
        if not top_5.empty and "payload" in top_5.columns:
            metadata_list = top_5["payload"].tolist()
        else:
            for res in results:
                if isinstance(res, list):
                    for item in res:
                        # item might be dict-like
                        if isinstance(item, dict) and "payload" in item:
                            metadata_list.append(item["payload"])

        if metadata_list:
            retrieved_text_chunks = "\n".join([m.get("text", "") for m in metadata_list if isinstance(m, dict)])
        else:
            retrieved_text_chunks = ""

        print("len of retrieved_text_chunks--",len(retrieved_text_chunks))
        sanitized_metadata = []
        for d in metadata_list:
            if isinstance(d, dict):
                copyd = dict(d)  # shallow copy
                copyd.pop("text", None)
                sanitized_metadata.append(copyd)
            else:
                sanitized_metadata.append(d)
        print("len of metadata list--",len(sanitized_metadata))
        metadata_event = {
            "type": "metadata",
            "queries": queries,
            "metadata": sanitized_metadata,
        }
        yield f"data: {json.dumps(metadata_event, ensure_ascii=False)}\n\n"

        print("now calling llm for ans generation")
        async for token in self.start_process_with_history_stream(user_id, user_query, retrieved_text_chunks, redis_store):
            token_event = {"type": "token", "token": token}
            yield f"data: {json.dumps(token_event, ensure_ascii=False)}\n\n"
        
        convo = await redis_store.load(user_id)
        final_answer = ""
        for msg in reversed(convo):
            if msg.get("role") == "assistant":
                final_answer = msg.get("content", "")
                break

        done_event = {
            "type": "done",
            "answer": final_answer,
            "metadata": sanitized_metadata
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
        