import re

def parse_reasoning_and_output(assistant_resposne):
    response = assistant_resposne

    # Match Reasoning until Answer: appears (flexible whitespace)
    reasoning = re.search(r"Reasoning:\s*(.*?)(?=\s*Answer:)", response, re.DOTALL)
    # Match Answer: until end of string
    answer = re.search(r"Answer:\s*(.*)", response, re.DOTALL)

    reasoning_text = reasoning.group(1).strip() if reasoning else None
    answer_text = answer.group(1).strip() if answer else None
    return reasoning_text, answer_text


def parse_reasoning_and_queries(assistant_resposne):
    response = assistant_resposne

    # reasoning = re.search(r"Reasoning:\s*(.*?)(?=Answer:)", response, re.S).group(1).strip()
    # queries = re.findall(r"- (.*)", response)

    reasoning = re.search(r"Reasoning:\s*(.*?)(?=Answer:)", response, re.S).group(1).strip()
    queries = re.findall(r"\d+\.\s*(.*)", response)

    return reasoning, queries

