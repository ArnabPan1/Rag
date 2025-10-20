import fitz  # PyMuPDF
from concurrent.futures import ThreadPoolExecutor, as_completed
import re, yaml, tqdm
import pandas as pd
from qdrant_client import QdrantClient, models

class QuadrantIndexer:
    def __init__(self):
        config = yaml.safe_load(open("config.yaml"))
        self.host = config['indexing']['quadrant_host']
        self.port =  config['indexing']['quadrant_port']
        self.collection_name = config['indexing']['collection_name']
        self.filename = config['filename']
        self.dense_model_name = "sentence-transformers/all-MiniLM-L6-v2"
        self.sparse_model_name = "prithivida/Splade_PP_en_v1"
        self.dense_vector_name = "dense"
        self.sparse_vector_name = "sparse"
    
    def get_client(self):
        client = QdrantClient(host=self.host, 
                              port=self.port)
        return client
    
    def create_index(self,client):
        
        if not client.collection_exists(self.collection_name):
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    self.dense_vector_name: models.VectorParams(
                        size=client.get_embedding_size(self.dense_model_name), 
                        distance=models.Distance.COSINE
                    )
                },  # size and distance are model dependent
                sparse_vectors_config={self.sparse_vector_name: models.SparseVectorParams()},
            )
        else:
            print(f"Collection already exists--{self.collection_name}")
    
    def upload_data(self, client):
        df = pd.read_csv(self.filename)
        df = df.fillna('')
        documents = []
        metadata = []
        for index, row in df.iterrows():
            description = str(row["text"])
            dense_document = models.Document(text=description, model=self.dense_model_name)
            sparse_document = models.Document(text=description, model=self.sparse_model_name)
            documents.append(
                {
                    self.dense_vector_name: dense_document,
                    self.sparse_vector_name: sparse_document,
                }
            )
            metadata.append(dict(row))
        client.upload_collection(
            collection_name=self.collection_name,
            vectors=tqdm.tqdm(documents),
            payload=metadata,
            # parallel=4,  # Use 4 CPU cores to encode data.
            # This will spawn a model per process, which might be memory expensive
            # Make sure that your system does not use swap, and reduce the amount
            # # of processes if it does. 
            # Otherwise, it might significantly slow down the process.
            # Requires wrapping code into if __name__ == '__main__' block
        )
    
    def process(self):
        client = self.get_client()
        self.create_index(client)
        self.upload_data(client)   
         
class EarningCallIndexer:
    def __init__(self):
        config = yaml.safe_load(open("config.yaml"))
        self.chunk_size = config["chunk_size"]
        self.overlap = config["overlap"]
        self.pdf_mapping = config["pdf_mapping"]
        self.filename = config["filename"]
    
    def recursive_word_safe_split(self,text, chunk_size=1000, overlap=100):
        """
        Split text into chunks word-safe, avoiding breaking words.
        Respects paragraphs -> sentences -> words.
        """
        text = text.replace('\n', ' ').strip()
        if len(text) <= chunk_size:
            return [text]

        # Split into sentences
        sentences = re.split(r'(?<=[.!?]) +', text)
        chunks = []
        buffer = ""

        for sent in sentences:
            if len(buffer) + len(sent) + 1 <= chunk_size:
                buffer += sent + " "
            else:
                if buffer.strip():
                    chunks.append(buffer.strip())
                buffer = sent + " "
        if buffer.strip():
            chunks.append(buffer.strip())

        # Apply overlap
        overlapped_chunks = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapped_chunks.append(chunk)
            else:
                prev = chunks[i - 1]
                overlap_text = prev[-overlap:] if overlap < len(prev) else prev
                overlapped_chunks.append(overlap_text + " " + chunk)

        return overlapped_chunks

    def recursive_split(self, text, size, overlap):
        if len(text) <= size:
            return [text]

        # Split into paragraphs
        paras = re.split(r'(?<=\n)\s*\n+', text)
        chunks, buffer = [], ""
        for para in paras:
            if len(buffer) + len(para) < size:
                buffer += para + "\n"
            else:
                chunks.append(buffer.strip())
                buffer = para + "\n"
        if buffer:
            chunks.append(buffer.strip())

        # Further split long chunks by sentences
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > size * 1.5:
                sentences = re.split(r'(?<=[.!?]) +', chunk)
                temp = ""
                for sent in sentences:
                    if len(temp) + len(sent) < size:
                        temp += sent + " "
                    else:
                        final_chunks.append(temp.strip())
                        temp = sent + " "
                if temp:
                    final_chunks.append(temp.strip())
            else:
                final_chunks.append(chunk)

        # Add overlap
        overlapped_chunks = []
        for i, ch in enumerate(final_chunks):
            if i > 0 and overlap > 0:
                prev = final_chunks[i - 1]
                overlap_text = prev[-overlap:]
                ch = overlap_text + " " + ch
            overlapped_chunks.append(ch.strip())

        return overlapped_chunks

    
    def extract_text(self, page):
        """Extract cleaned text from a single page."""
        text = page.get_text("text")
        text = re.sub(r'\s+', ' ', text).strip()
        return text
        
    def load_and_split_pdf(
        self,
        pdf_path: str,
        skip_first_n: int = 2,
        skip_last_m: int = 5,
        max_workers: int = 8,
        chunk_size: int = 1200,
        overlap: int = 200,
    ):
        # Load the PDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Determine which pages to process
        target_pages = list(range(skip_first_n, total_pages - skip_last_m))
        print("target_pages-------",target_pages)

        # Parallel extraction
        page_texts = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.extract_text, doc[i]): i for i in target_pages}
            for future in as_completed(futures):
                page_idx = futures[future]
                try:
                    text = future.result()
                    if text:
                        page_texts.append((page_idx, text))
                except Exception as e:
                    print(f"Error reading page {page_idx}: {e}")

        # Sort and join
        return page_texts
        # page_texts.sort(key=lambda x: x[0])
        # combined_text = "\n".join([t for _, t in page_texts])
        # chunks = self.recursive_split(combined_text, chunk_size, overlap)
        # return chunks
    

    def index_pdf(self):
        all_pdf_chunk_mapping = []
        for k, v in self.pdf_mapping.items():
            pdf_path = f"dataset/{k}.pdf"
            page_texts = self.load_and_split_pdf(pdf_path)
            chunk_mappings = []
            chunk_id = 0
            for page_idx, text in page_texts:
                chunks = self.recursive_word_safe_split(text, self.chunk_size, self.overlap)
                for chunk in chunks:
                    chunk_mappings.append({
                        "page": page_idx + 1,   # +1 for human-readable numbering
                        "chunk_id": chunk_id,
                        "text": chunk,
                        "user_id": v,
                        "pdf_name": k,
                    })
                    chunk_id += 1
            all_pdf_chunk_mapping.extend(chunk_mappings)
            print("len of all_pdf_chunk_mapping-----"), len(all_pdf_chunk_mapping)
        df = pd.DataFrame(all_pdf_chunk_mapping)
        df.to_csv(self.filename, index=False)
        

            

        


# Example usage:
if __name__ == "__main__":
    # chunks = EarningCallIndexer().load_and_split_pdf("dataset/2023_Q3_NVDA.pdf", skip_first_n=2, skip_last_m=5)
    # print(f"✅ Extracted {len(chunks)} chunks")
    # print(chunks[0][:400])
    # EarningCallIndexer().index_pdf()
    qd = QuadrantIndexer()
    qd.process()
