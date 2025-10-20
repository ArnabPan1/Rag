from qdrant_client import AsyncQdrantClient, models
import yaml
import asyncio

class QuadrantRetrieval:
    def __init__(self):
        config = yaml.safe_load(open("config.yaml"))
        self.host = config['indexing']['quadrant_host']
        self.port =  config['indexing']['quadrant_port']
        self.collection_name = config['indexing']['collection_name']
        self.retrival_config = config['retrival']
        self.filename = config['filename']
        self.dense_model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.sparse_model_name = "prithivida/Splade_PP_en_v1"
        self.dense_vector_name = "dense"
        self.sparse_vector_name = "sparse"
    
    async def get_client(self):
        client = AsyncQdrantClient(host=self.host, 
                              port=self.port)
        return client
    
    async def search(self, text,query_filter):
        client = await self.get_client()
        search_result = await client.query_points(
            collection_name=self.collection_name,
            query=models.FusionQuery(
                fusion=models.Fusion.RRF  # we are using reciprocal rank fusion here
            ),
            prefetch=[
                models.Prefetch(
                    query=models.Document(text=text, model=self.dense_model_name),
                    using=self.dense_vector_name,
                ),
                models.Prefetch(
                    query=models.Document(text=text, model=self.sparse_model_name),
                    using=self.sparse_vector_name,
                ),
            ],
            query_filter=query_filter,
            limit=self.retrival_config['topn'] ,
        )
    
        # Select and return metadata
        # response = [point.payload['text'] for point in search_result.points]
        metadata = [dict(point) for point in search_result.points]
        return metadata
    
    async def close_client(self):
        client = await self.get_client()
        await client.close()
    
    async def create_serach_filter(self, user_id):
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="user_id", 
                    match=models.MatchValue(value=user_id)
                )
            ]
        )
    async def process_search(self, text, user_id):
        print("searching for ---",text)
        query_filter = await self.create_serach_filter(user_id)
        metadata = await self.search(text, query_filter)
        print("result len---",len(metadata))
        return metadata


if __name__ == "__main__":
    qd = QuadrantRetrieval()
    user_id = "alice"
    text = "Amazon q3 report"
    metadata = asyncio.run(qd.process_search(text, user_id))
    print(metadata)

